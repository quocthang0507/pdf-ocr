import re
from collections.abc import Sequence
from statistics import median

from src.constants import BlockType
from src.core.models import BoundingBox, OCRBlock, OCRPage

_LIST_MARKER_REGEX = re.compile(r"^([•\-\*\+–—]|\d+[\.\)]|[a-zA-Z][\.\)])\s+")
_CAPTION_REGEX = re.compile(
    r"^\s*(?:hình|bảng|biểu\s*đồ|sơ\s*đồ|figure|table|chart|diagram)"
    r"\s*(?:số\s*)?\d+(?:[\s:.)-]|$)",
    re.IGNORECASE,
)


class LayoutAnalyzer:
    """Sort page blocks by recursively cutting whitespace between regions."""

    def __init__(self, minimum_gap: float = 1.0) -> None:
        if minimum_gap < 0:
            raise ValueError("Khoảng trắng tối thiểu không được âm.")
        self._minimum_gap = float(minimum_gap)

    def analyze(
        self,
        page: OCRPage,
        merge_paragraphs: bool = True,
        *,
        reading_order: bool = True,
    ) -> OCRPage:
        """Return a new page whose blocks carry a contiguous reading order.

        With `reading_order` off the engine's own order is kept, so multi-column
        sorting is skipped; tables are still grouped into their own blocks.
        """
        if not isinstance(page, OCRPage):
            raise TypeError("page phải là đối tượng OCRPage.")
        page = self.classify_blocks(page)
        grouped = self.group_tables(page)
        if reading_order:
            blocks = self.sort_blocks(grouped.blocks)
        else:
            blocks = grouped.blocks
        if merge_paragraphs:
            blocks = self.merge_paragraphs(blocks)
        elif not reading_order:
            blocks = tuple(
                block.with_updates(reading_order=order)
                for order, block in enumerate(blocks)
            )
        return page.with_updates(blocks=blocks)

    def classify_blocks(self, page: OCRPage) -> OCRPage:
        """Label captions and typographically prominent headings when evidence exists.

        Text size comes from native PDF font metadata when available, or line
        height for scanned OCR. Pages without a clear size distinction remain
        ordinary text rather than receiving speculative heading labels.
        """
        candidates = [
            (index, block, self._text_size(block))
            for index, block in enumerate(page.blocks)
            if block.block_type is BlockType.TEXT
            and block.text
            and not _CAPTION_REGEX.match(block.text)
            and not any(
                self._center_in(block.bbox, table.bbox) for table in page.tables
            )
        ]
        sizes = [item[2] for item in candidates if item[2] > 0]
        lower_half = sorted(sizes)[: max(1, (len(sizes) + 1) // 2)]
        baseline = median(lower_half) if lower_half else 0.0
        blocks = list(page.blocks)
        for index, block in enumerate(blocks):
            if block.block_type is not BlockType.TEXT:
                continue
            if any(self._center_in(block.bbox, table.bbox) for table in page.tables):
                continue
            if _CAPTION_REGEX.match(block.text):
                blocks[index] = block.with_updates(block_type=BlockType.CAPTION)
                continue
            size = self._text_size(block)
            ratio = size / baseline if baseline else 0.0
            if ratio >= 1.8:
                block_type = BlockType.HEADING_1
            elif ratio >= 1.5:
                block_type = BlockType.HEADING_2
            elif ratio >= 1.3 and len(block.text) <= 200:
                block_type = BlockType.HEADING_3
            else:
                continue
            blocks[index] = block.with_updates(block_type=block_type)
        return page.with_updates(blocks=tuple(blocks))

    @staticmethod
    def _text_size(block: OCRBlock) -> float:
        font_sizes = [
            line.font_size
            for line in block.lines
            if line.font_size is not None and line.font_size > 0
        ]
        if font_sizes:
            return sum(font_sizes) / len(font_sizes)
        line_heights = [
            line.bbox.height for line in block.lines if line.bbox.height > 0
        ]
        return sum(line_heights) / len(line_heights) if line_heights else 0.0

    def group_tables(self, page: OCRPage) -> OCRPage:
        """Fold the text lines lying inside each detected table into one table block."""
        if not page.tables:
            return page
        blocks = list(page.blocks)
        for table in page.tables:
            inside = [
                block
                for block in blocks
                if block.block_type is not BlockType.TABLE
                and self._center_in(block.bbox, table.bbox)
            ]
            already = any(
                block.block_type is BlockType.TABLE
                and self._center_in(table.bbox, block.bbox)
                for block in blocks
            )
            if already:
                continue
            lines = tuple(line for block in inside for line in block.lines)
            first = min(
                (index for index, block in enumerate(blocks) if block in inside),
                default=len(blocks),
            )
            blocks = [block for block in blocks if block not in inside]
            blocks.insert(
                min(first, len(blocks)),
                OCRBlock(lines=lines, bbox=table.bbox, block_type=BlockType.TABLE),
            )
        return page.with_updates(blocks=tuple(blocks))

    @staticmethod
    def _center_in(inner: BoundingBox, outer: BoundingBox) -> bool:
        centre_x = (inner.x1 + inner.x2) / 2
        centre_y = (inner.y1 + inner.y2) / 2
        return outer.x1 <= centre_x <= outer.x2 and outer.y1 <= centre_y <= outer.y2

    def merge_paragraphs(self, blocks: Sequence[OCRBlock]) -> tuple[OCRBlock, ...]:
        """Group consecutive lines in reading order into paragraph blocks."""
        if any(not isinstance(block, OCRBlock) for block in blocks):
            raise TypeError("blocks chỉ được chứa đối tượng OCRBlock.")
        if len(blocks) < 2:
            return tuple(blocks)

        merged: list[OCRBlock] = []
        current = blocks[0]

        for next_block in blocks[1:]:
            if self._should_merge_blocks(current, next_block):
                current = self._combine_blocks(current, next_block)
            else:
                merged.append(current)
                current = next_block
        merged.append(current)

        return tuple(
            block.with_updates(reading_order=order)
            for order, block in enumerate(merged)
        )

    def _should_merge_blocks(self, current: OCRBlock, candidate: OCRBlock) -> bool:
        if (
            current.block_type != BlockType.TEXT
            or candidate.block_type != BlockType.TEXT
        ):
            return False

        b1 = current.lines[-1].bbox if current.lines else current.bbox
        b2 = candidate.lines[0].bbox if candidate.lines else candidate.bbox

        if b2.y1 < b1.y1 - 4.0:
            return False

        gap = b2.y1 - b1.y2
        line_height = max((b1.height + b2.height) / 2.0, 1.0)

        if gap > 1.8 * line_height or gap < -0.6 * line_height:
            return False

        overlap_x = min(b1.x2, b2.x2) - max(b1.x1, b2.x1)
        min_width = min(b1.width, b2.width)
        if min_width > 0 and (overlap_x / min_width) < 0.25:
            return False

        if abs(b1.x1 - b2.x1) > max(b1.width, b2.width) * 0.45:
            return False

        prev_text = current.lines[-1].text.strip() if current.lines else ""
        next_text = candidate.lines[0].text.strip() if candidate.lines else ""

        if not prev_text or not next_text:
            return False

        if bool(_LIST_MARKER_REGEX.match(next_text)):
            return False

        if prev_text.endswith(":"):
            return False

        if prev_text.endswith("-") and not prev_text.endswith(" -"):
            return True

        if prev_text.endswith((".", "!", "?", "...", "…”", '."')):
            col_width = max(current.bbox.width, candidate.bbox.width)
            if col_width > 0 and b1.width < 0.65 * col_width:
                return False
            if gap > 1.2 * line_height:
                return False

        return True

    @staticmethod
    def _combine_blocks(b1: OCRBlock, b2: OCRBlock) -> OCRBlock:
        combined_box = BoundingBox(
            min(b1.bbox.x1, b2.bbox.x1),
            min(b1.bbox.y1, b2.bbox.y1),
            max(b1.bbox.x2, b2.bbox.x2),
            max(b1.bbox.y2, b2.bbox.y2),
        )
        return b1.with_updates(
            lines=b1.lines + b2.lines,
            bbox=combined_box,
        )

    def sort_blocks(self, blocks: Sequence[OCRBlock]) -> tuple[OCRBlock, ...]:
        """Apply recursive XY-Cut, preferring column cuts over row cuts."""
        if any(not isinstance(block, OCRBlock) for block in blocks):
            raise TypeError("blocks chỉ được chứa đối tượng OCRBlock.")
        indexed = list(enumerate(blocks))
        ordered = self._order_around_spanning_blocks(indexed)
        return tuple(
            block.with_updates(reading_order=order)
            for order, (_, block) in enumerate(ordered)
        )

    def _order_around_spanning_blocks(
        self, blocks: list[tuple[int, OCRBlock]]
    ) -> list[tuple[int, OCRBlock]]:
        if len(blocks) < 2:
            return blocks
        left = min(block.bbox.x1 for _, block in blocks)
        right = max(block.bbox.x2 for _, block in blocks)
        page_span = right - left
        spanning = [item for item in blocks if item[1].bbox.width >= page_span * 0.8]
        has_column_candidate = any(
            block.bbox.width <= page_span * 0.65 for _, block in blocks
        )
        if not spanning or not has_column_candidate:
            return self._xy_cut(blocks)
        remaining = [item for item in blocks if item not in spanning]
        ordered: list[tuple[int, OCRBlock]] = []
        for span in sorted(spanning, key=self._fallback_key):
            split_y = (span[1].bbox.y1 + span[1].bbox.y2) / 2
            upper = [item for item in remaining if item[1].bbox.y2 <= split_y]
            ordered.extend(self._xy_cut(upper))
            ordered.append(span)
            remaining = [item for item in remaining if item not in upper]
        ordered.extend(self._xy_cut(remaining))
        return ordered

    def _xy_cut(self, blocks: list[tuple[int, OCRBlock]]) -> list[tuple[int, OCRBlock]]:
        if len(blocks) < 2:
            return blocks
        vertical = self._largest_gap(blocks, horizontal=False)
        if vertical is not None:
            left, right = self._partition(blocks, vertical, horizontal=False)
            return self._xy_cut(left) + self._xy_cut(right)
        horizontal = self._largest_gap(blocks, horizontal=True)
        if horizontal is not None:
            upper, lower = self._partition(blocks, horizontal, horizontal=True)
            return self._xy_cut(upper) + self._xy_cut(lower)
        return sorted(blocks, key=self._fallback_key)

    def _largest_gap(
        self, blocks: list[tuple[int, OCRBlock]], *, horizontal: bool
    ) -> float | None:
        intervals = sorted(
            (
                (block.bbox.y1, block.bbox.y2)
                if horizontal
                else (block.bbox.x1, block.bbox.x2)
            )
            for _, block in blocks
        )
        furthest_end = intervals[0][1]
        best_gap = self._minimum_gap
        cut: float | None = None
        for start, end in intervals[1:]:
            gap = start - furthest_end
            if gap > best_gap:
                best_gap = gap
                cut = furthest_end + gap / 2
            furthest_end = max(furthest_end, end)
        return cut

    @staticmethod
    def _partition(
        blocks: list[tuple[int, OCRBlock]], cut: float, *, horizontal: bool
    ) -> tuple[list[tuple[int, OCRBlock]], list[tuple[int, OCRBlock]]]:
        before: list[tuple[int, OCRBlock]] = []
        after: list[tuple[int, OCRBlock]] = []
        for item in blocks:
            box = item[1].bbox
            center = (box.y1 + box.y2) / 2 if horizontal else (box.x1 + box.x2) / 2
            (before if center < cut else after).append(item)
        return before, after

    @staticmethod
    def _fallback_key(item: tuple[int, OCRBlock]) -> tuple[float, float, int]:
        index, block = item
        return block.bbox.y1, block.bbox.x1, index

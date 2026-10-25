import re
from collections.abc import Sequence
from statistics import median

import numpy as np

from src.constants import BlockType
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage

_LIST_MARKER_REGEX = re.compile(r"^([•\-\*\+–—]|\d+[\.\)]|[a-zA-Z][\.\)])\s+")
_CAPTION_REGEX = re.compile(
    r"^\s*(?:hình|bảng|biểu\s*đồ|sơ\s*đồ|figure|table|chart|diagram)"
    r"\s*(?:số\s*)?\d+(?:[\s:.)-]|$)",
    re.IGNORECASE,
)


#: Share of the shorter box two boxes must overlap vertically to share a row.
_SAME_ROW_OVERLAP = 0.7
#: Extra size ratio a scanned line needs over the typical one to be a heading.
_BOX_HEIGHT_MARGIN = 0.2


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
        from_fonts = any(self._has_font_size(item[1]) for item in candidates)
        if from_fonts:
            lower_half = sorted(sizes)[: max(1, (len(sizes) + 1) // 2)]
            baseline = median(lower_half) if lower_half else 0.0
        else:
            # Scanned lines: box heights swing with accents and descenders, so
            # compare against the typical line and demand a clearer jump.
            baseline = median(sizes) if sizes else 0.0
        bump = 0.0 if from_fonts else _BOX_HEIGHT_MARGIN
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
            if ratio >= 1.8 + bump:
                block_type = BlockType.HEADING_1
            elif ratio >= 1.5 + bump:
                block_type = BlockType.HEADING_2
            elif ratio >= 1.3 + bump and len(block.text) <= 200:
                block_type = BlockType.HEADING_3
            else:
                continue
            blocks[index] = block.with_updates(block_type=block_type)
        return page.with_updates(blocks=tuple(blocks))

    @staticmethod
    def _has_font_size(block: OCRBlock) -> bool:
        return any(
            line.font_size is not None and line.font_size > 0 for line in block.lines
        )

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

        blocks = self.join_words_into_lines(blocks)
        if len(blocks) < 2:
            return tuple(
                block.with_updates(reading_order=order)
                for order, block in enumerate(blocks)
            )
        merged: list[OCRBlock] = []
        current = blocks[0]
        line_gap = self._typical_line_gap(blocks)

        for next_block in blocks[1:]:
            if self._should_merge_blocks(current, next_block, line_gap):
                current = self._combine_blocks(current, next_block)
            else:
                merged.append(current)
                current = next_block
        merged.append(current)

        return tuple(
            block.with_updates(reading_order=order)
            for order, block in enumerate(merged)
        )

    def join_words_into_lines(self, blocks: Sequence[OCRBlock]) -> tuple[OCRBlock, ...]:
        """Fold word-level boxes that sit side by side on one row into a line.

        Engines such as EasyOCR and PaddleOCR may return a box per word or
        phrase; without this each word became its own "paragraph".
        """
        joined: list[OCRBlock] = []
        for block in blocks:
            previous = joined[-1] if joined else None
            if previous is not None and self._continues_row(previous, block):
                joined[-1] = self._append_to_row(previous, block)
            else:
                joined.append(block)
        return tuple(joined)

    @staticmethod
    def _continues_row(current: OCRBlock, candidate: OCRBlock) -> bool:
        if (
            current.block_type is not BlockType.TEXT
            or candidate.block_type is not BlockType.TEXT
            or not current.lines
            or len(candidate.lines) != 1
        ):
            return False
        left, right = current.lines[-1].bbox, candidate.lines[0].bbox
        height = max(min(left.height, right.height), 1.0)
        overlap = min(left.y2, right.y2) - max(left.y1, right.y1)
        if overlap < 0.5 * height:
            return False
        gap = right.x1 - left.x2
        # Below half a line it is a word space; wider is a column gutter.
        return -0.2 * height <= gap < 0.5 * max(left.height, right.height)

    @staticmethod
    def _append_to_row(current: OCRBlock, candidate: OCRBlock) -> OCRBlock:
        last, word_line = current.lines[-1], candidate.lines[0]
        line_box = BoundingBox(
            min(last.bbox.x1, word_line.bbox.x1),
            min(last.bbox.y1, word_line.bbox.y1),
            max(last.bbox.x2, word_line.bbox.x2),
            max(last.bbox.y2, word_line.bbox.y2),
        )
        line = OCRLine(
            words=last.words + word_line.words,
            bbox=line_box,
            font_name=last.font_name,
            font_size=last.font_size,
        )
        block_box = BoundingBox(
            min(current.bbox.x1, candidate.bbox.x1),
            min(current.bbox.y1, candidate.bbox.y1),
            max(current.bbox.x2, candidate.bbox.x2),
            max(current.bbox.y2, candidate.bbox.y2),
        )
        return current.with_updates(lines=current.lines[:-1] + (line,), bbox=block_box)

    @staticmethod
    def _typical_line_gap(blocks: Sequence[OCRBlock]) -> float | None:
        """Median whitespace between consecutive lines stacked in one column.

        Paragraph breaks are judged against this rhythm rather than against the
        line height alone: a blank line on a densely set page is often less
        than two line heights tall, and used to be swallowed into one block.
        """
        gaps: list[float] = []
        for first, second in zip(blocks, blocks[1:], strict=False):
            if first.block_type is not BlockType.TEXT:
                continue
            b1 = first.lines[-1].bbox if first.lines else first.bbox
            b2 = second.lines[0].bbox if second.lines else second.bbox
            if min(b1.x2, b2.x2) - max(b1.x1, b2.x1) <= 0:
                continue
            gap = b2.y1 - b1.y2
            height = max((b1.height + b2.height) / 2.0, 1.0)
            if -0.6 * height <= gap <= 1.8 * height:
                gaps.append(max(gap, 0.0))
        if len(gaps) < 2:
            return None
        return float(median(gaps))

    @staticmethod
    def _is_shouted(text: str) -> bool:
        """An all-capitals line such as a national motto or a section title.

        Very short lines do not count: line recognisers sometimes return a
        two-word crop in capitals ("VỀ SỐ"). A stray misread lower-case letter
        ("HỘl") is tolerated.
        """
        letters = [char for char in text if char.isalpha()]
        if len(letters) < 8:
            return False
        upper = sum(1 for char in letters if char.isupper())
        return upper >= 0.9 * len(letters)

    @staticmethod
    def _starts_capitalised(text: str) -> bool:
        """A capital opening, ignoring the l/I mix-up common in OCR ("Iượng")."""
        if not text[:1].isupper():
            return False
        return not (text[0] == "I" and text[1:2].islower())

    def _should_merge_blocks(
        self,
        current: OCRBlock,
        candidate: OCRBlock,
        line_gap: float | None = None,
    ) -> bool:
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
        if line_gap is not None and gap > line_gap + 0.5 * line_height:
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

        if self._is_shouted(prev_text) != self._is_shouted(next_text):
            return False
        if self._is_shouted(prev_text) and self._is_shouted(next_text):
            return False

        if prev_text.endswith("-") and not prev_text.endswith(" -"):
            return True

        col_width = max(current.bbox.width, candidate.bbox.width)
        ends_short = col_width > 0 and b1.width < 0.65 * col_width
        if prev_text.endswith((".", "!", "?", "...", "…”", '."')):
            if ends_short:
                return False
            if gap > 1.2 * line_height:
                return False
        elif (
            ends_short
            and self._starts_capitalised(next_text)
            and not prev_text.endswith(",")
        ):
            # A line that stops well short of the column and is followed by a
            # capitalised one ends its paragraph ("Kính gửi: Phòng Kế toán").
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
        vertical = self._largest_gap(
            blocks, horizontal=False, minimum=self._gutter_width(blocks)
        )
        if vertical is not None:
            left, right = self._partition(blocks, vertical, horizontal=False)
            return self._xy_cut(left) + self._xy_cut(right)
        horizontal = self._largest_gap(blocks, horizontal=True)
        if horizontal is not None:
            upper, lower = self._partition(blocks, horizontal, horizontal=True)
            return self._xy_cut(upper) + self._xy_cut(lower)
        return self._row_order(blocks)

    @staticmethod
    def _row_order(
        blocks: list[tuple[int, OCRBlock]],
    ) -> list[tuple[int, OCRBlock]]:
        """Read blocks that no whitespace separates row by row, left to right.

        Phrase boxes from EasyOCR overlap their neighbours, so no cut exists;
        sorting by top edge alone let a box a few pixels taller jump ahead of
        the phrase to its left ("cùng / người so với").
        """
        rows: list[list[tuple[int, OCRBlock]]] = []
        for item in sorted(blocks, key=lambda it: (it[1].bbox.y1 + it[1].bbox.y2)):
            box = item[1].bbox
            if rows:
                anchor = rows[-1][0][1].bbox
                overlap = min(box.y2, anchor.y2) - max(box.y1, anchor.y1)
                if overlap >= _SAME_ROW_OVERLAP * min(box.height, anchor.height):
                    rows[-1].append(item)
                    continue
            rows.append([item])
        return [
            item
            for row in rows
            for item in sorted(row, key=lambda it: (it[1].bbox.x1, it[0]))
        ]

    def _gutter_width(self, blocks: list[tuple[int, OCRBlock]]) -> float:
        """Smallest whitespace that separates columns rather than words.

        Word-level boxes from engines such as EasyOCR leave word spaces that
        line up across two or three lines; cutting there read a short passage
        column by column. A column gutter is at least about half a line tall.
        """
        heights = sorted(
            line.bbox.height
            for _, block in blocks
            for line in (block.lines or ())
            if line.bbox.height > 0
        )
        if not heights:
            return self._minimum_gap
        return max(self._minimum_gap, 0.5 * heights[len(heights) // 2])

    def _largest_gap(
        self,
        blocks: list[tuple[int, OCRBlock]],
        *,
        horizontal: bool,
        minimum: float | None = None,
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
        best_gap = self._minimum_gap if minimum is None else minimum
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


def projection_by_bboxes(boxes: np.ndarray, axis: int) -> np.ndarray:
    """Compute a 1D per-pixel projection histogram along `axis` (0=x, 1=y)."""
    if axis not in (0, 1):
        raise ValueError("axis phải là 0 (ngang) hoặc 1 (dọc).")
    if boxes.size == 0:
        return np.zeros(0, dtype=int)
    coords = np.asarray(boxes[:, axis::2], dtype=int)
    length = int(np.max(coords))
    if length <= 0:
        return np.zeros(0, dtype=int)
    hist = np.zeros(length, dtype=int)
    for start, end in coords:
        s = max(0, int(start))
        e = max(s, int(end))
        hist[s:e] += 1
    return hist


def split_projection_profile(
    arr_values: np.ndarray, min_value: float = 0.0, min_gap: float = 1.0
) -> tuple[np.ndarray, np.ndarray] | None:
    """Split a 1D projection profile into contiguous non-empty intervals."""
    arr_index = np.where(arr_values > min_value)[0]
    if len(arr_index) == 0:
        return None
    arr_diff = arr_index[1:] - arr_index[:-1]
    arr_diff_index = np.where(arr_diff > min_gap)[0]
    zero_start = arr_index[arr_diff_index]
    zero_end = arr_index[arr_diff_index + 1]
    starts = np.insert(zero_end, 0, arr_index[0])
    ends = np.append(zero_start, arr_index[-1]) + 1
    return starts, ends


def merge_overlapping_boxes(boxes: Sequence[BoundingBox]) -> list[BoundingBox]:
    """Consolidate overlapping bounding boxes into unified region envelopes."""
    remaining = list(boxes)
    merged: list[BoundingBox] = []
    while remaining:
        current = remaining.pop(0)
        overlaps = [
            idx
            for idx, candidate in enumerate(remaining)
            if not (
                current.x2 < candidate.x1
                or current.x1 > candidate.x2
                or current.y2 < candidate.y1
                or current.y1 > candidate.y2
            )
        ]
        if overlaps:
            group = [current]
            for offset, idx in enumerate(overlaps):
                group.append(remaining.pop(idx - offset))
            current = BoundingBox(
                min(b.x1 for b in group),
                min(b.y1 for b in group),
                max(b.x2 for b in group),
                max(b.y2 for b in group),
            )
        merged.append(current)
    return merged

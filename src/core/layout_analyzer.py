"""Geometry-only XY-Cut reading order analysis for OCR blocks."""

from __future__ import annotations

from collections.abc import Sequence

from src.core.models import OCRBlock, OCRPage


class LayoutAnalyzer:
    """Sort page blocks by recursively cutting whitespace between regions."""

    def __init__(self, minimum_gap: float = 1.0) -> None:
        if minimum_gap < 0:
            raise ValueError("Khoảng trắng tối thiểu không được âm.")
        self._minimum_gap = float(minimum_gap)

    def analyze(self, page: OCRPage) -> OCRPage:
        """Return a new page whose blocks carry a contiguous reading order."""
        if not isinstance(page, OCRPage):
            raise TypeError("page phải là đối tượng OCRPage.")
        return page.with_updates(blocks=self.sort_blocks(page.blocks))

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

"""Build immutable table grids from detected cell and OCR word coordinates."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.core.models import BoundingBox, OCRTable, OCRWord, TableCellSpan

_MAX_GRID_CELLS = 10_000


@dataclass(frozen=True)
class DetectedTableCell:
    """Geometry and logical grid coordinates returned by a table detector."""

    row: int
    column: int
    bbox: BoundingBox
    row_span: int = 1
    column_span: int = 1

    def __post_init__(self) -> None:
        for name in ("row", "column"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(f"{name} phải là số nguyên không âm.")
        for name in ("row_span", "column_span"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} phải là số nguyên dương.")
        if not isinstance(self.bbox, BoundingBox):
            raise TypeError("bbox phải là đối tượng BoundingBox.")


class TableExtractor:
    """Assign recognized words to a validated, finite cell layout."""

    def extract(
        self,
        cells: Sequence[DetectedTableCell],
        words: Sequence[OCRWord],
        *,
        table_bbox: BoundingBox | None = None,
    ) -> OCRTable:
        if not cells:
            raise ValueError("Cần ít nhất một ô để dựng bảng.")
        if any(not isinstance(cell, DetectedTableCell) for cell in cells):
            raise TypeError("cells chỉ được chứa DetectedTableCell.")
        if any(not isinstance(word, OCRWord) for word in words):
            raise TypeError("words chỉ được chứa OCRWord.")
        row_count, column_count = self._grid_size(cells)
        self._validate_occupancy(cells, row_count, column_count)
        grid = [["" for _ in range(column_count)] for _ in range(row_count)]
        for cell in cells:
            assigned = [word for word in words if self._contains(cell.bbox, word)]
            grid[cell.row][cell.column] = " ".join(
                word.text for word in sorted(assigned, key=self._word_key)
            )
        spans = tuple(
            TableCellSpan(cell.row, cell.column, cell.row_span, cell.column_span)
            for cell in sorted(cells, key=lambda item: (item.row, item.column))
            if cell.row_span > 1 or cell.column_span > 1
        )
        return OCRTable(
            rows=tuple(tuple(row) for row in grid),
            bbox=table_bbox or self._enclosing_box(cells),
            merged_cells=spans,
        )

    @staticmethod
    def _grid_size(cells: Sequence[DetectedTableCell]) -> tuple[int, int]:
        rows = max(cell.row + cell.row_span for cell in cells)
        columns = max(cell.column + cell.column_span for cell in cells)
        if rows * columns > _MAX_GRID_CELLS:
            raise ValueError("Kích thước lưới bảng vượt quá giới hạn an toàn.")
        return rows, columns

    @staticmethod
    def _validate_occupancy(
        cells: Sequence[DetectedTableCell], rows: int, columns: int
    ) -> None:
        occupied = [[False for _ in range(columns)] for _ in range(rows)]
        for cell in cells:
            for row in range(cell.row, cell.row + cell.row_span):
                for column in range(cell.column, cell.column + cell.column_span):
                    if occupied[row][column]:
                        raise ValueError("Các ô bảng không được chồng lấn.")
                    occupied[row][column] = True

    @staticmethod
    def _contains(box: BoundingBox, word: OCRWord) -> bool:
        center_x = (word.bbox.x1 + word.bbox.x2) / 2
        center_y = (word.bbox.y1 + word.bbox.y2) / 2
        return box.x1 <= center_x < box.x2 and box.y1 <= center_y < box.y2

    @staticmethod
    def _word_key(word: OCRWord) -> tuple[float, float]:
        return word.bbox.y1, word.bbox.x1

    @staticmethod
    def _enclosing_box(cells: Sequence[DetectedTableCell]) -> BoundingBox:
        return BoundingBox(
            min(cell.bbox.x1 for cell in cells),
            min(cell.bbox.y1 for cell in cells),
            max(cell.bbox.x2 for cell in cells),
            max(cell.bbox.y2 for cell in cells),
        )

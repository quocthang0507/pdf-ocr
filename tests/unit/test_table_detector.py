"""Ruled tables are recovered from their lines for text-only engines."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.core.table_detector import detect_ruled_tables
from src.services.pipeline_service import attach_ruled_tables

pytestmark = pytest.mark.unit

XS = (100, 500, 800, 1100)
YS = (100, 180, 260, 340)


def _grid(
    xs: tuple[int, ...] = XS,
    ys: tuple[int, ...] = YS,
    size: tuple[int, int] = (500, 1300),
) -> np.ndarray:
    image = np.full((*size, 3), 255, dtype=np.uint8)
    for y in ys:
        cv2.line(image, (xs[0], y), (xs[-1], y), (0, 0, 0), 3)
    for x in xs:
        cv2.line(image, (x, ys[0]), (x, ys[-1]), (0, 0, 0), 3)
    return image


def _shape(cells: list) -> tuple[int, int]:
    rows = max(cell.row + cell.row_span for cell in cells)
    columns = max(cell.column + cell.column_span for cell in cells)
    return rows, columns


def test_a_ruled_grid_becomes_rows_and_columns() -> None:
    tables = detect_ruled_tables(_grid())

    assert len(tables) == 1
    assert _shape(tables[0]) == (3, 3)
    assert len(tables[0]) == 9


def test_merged_cells_keep_their_spans() -> None:
    image = _grid()
    # Remove the rule between the first two header cells and between rows 1-2
    # of the first column: one column span and one row span.
    cv2.line(image, (XS[1], YS[0] + 4), (XS[1], YS[1] - 4), (255, 255, 255), 7)
    cv2.line(image, (XS[0] + 4, YS[2]), (XS[1] - 4, YS[2]), (255, 255, 255), 7)

    (cells,) = detect_ruled_tables(image)

    spans = {(c.row, c.column, c.row_span, c.column_span) for c in cells}
    assert (0, 0, 1, 2) in spans
    assert (1, 0, 2, 1) in spans
    assert _shape(cells) == (3, 3)


def test_a_table_cut_at_the_page_edge_is_still_closed() -> None:
    """Border removal can crop a table's outer rule off the image."""
    image = _grid()[:, : XS[-1] - 1]

    (cells,) = detect_ruled_tables(image)

    assert _shape(cells) == (3, 3)


@pytest.mark.parametrize("kind", ["text", "underlines", "single box", "open rules"])
def test_pages_without_a_ruled_grid_have_no_table(kind: str) -> None:
    image = np.full((500, 1300, 3), 255, dtype=np.uint8)
    if kind == "text":
        for y in (100, 160, 220):
            cv2.putText(
                image,
                "Van ban thuong khong co bang",
                (80, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.5,
                (0, 0, 0),
                3,
            )
    elif kind == "underlines":
        for y in (150, 250, 350):
            cv2.line(image, (400, y), (1200, y), (0, 0, 0), 3)
    elif kind == "single box":
        cv2.rectangle(image, (100, 100), (1100, 400), (0, 0, 0), 3)
    else:
        for y in YS:
            cv2.line(image, (XS[0], y), (XS[-1], y), (0, 0, 0), 3)

    assert detect_ruled_tables(image) == []


def test_recognised_lines_fill_the_detected_cells() -> None:
    def line(text: str, x: int, y: int) -> OCRBlock:
        box = BoundingBox(x, y, x + 200, y + 40)
        return OCRBlock((OCRLine((OCRWord(text, box),), box),), box)

    page = OCRPage(
        1,
        1300,
        500,
        blocks=(
            line("Mặt hàng", 120, 120),
            line("Số lượng", 520, 120),
            line("Đơn giá", 820, 120),
            line("Sổ tay", 120, 200),
            line("12", 520, 200),
            line("45.000", 820, 200),
        ),
    )

    filled = attach_ruled_tables(page, _grid())

    (table,) = filled.tables
    assert table.rows[0] == ("Mặt hàng", "Số lượng", "Đơn giá")
    assert table.rows[1] == ("Sổ tay", "12", "45.000")
    assert table.rows[2] == ("", "", "")
    assert filled.blocks == page.blocks


def test_a_page_without_tables_is_returned_unchanged() -> None:
    page = OCRPage(1, 1300, 500)

    assert attach_ruled_tables(page, np.full((500, 1300, 3), 255, np.uint8)) is page

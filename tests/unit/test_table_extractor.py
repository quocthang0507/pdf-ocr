"""Behavior tests for coordinate-driven table extraction."""

from __future__ import annotations

import pytest

from src.core.models import BoundingBox, OCRWord, TableCellSpan
from src.core.table_extractor import DetectedTableCell, TableExtractor


def _word(text: str, box: tuple[float, float, float, float]) -> OCRWord:
    return OCRWord(text, BoundingBox(*box), confidence=0.9)


@pytest.mark.unit
def test_maps_words_into_a_rectangular_row_column_grid() -> None:
    cells = (
        DetectedTableCell(1, 1, BoundingBox(100, 50, 200, 100)),
        DetectedTableCell(0, 0, BoundingBox(0, 0, 100, 50)),
        DetectedTableCell(1, 0, BoundingBox(0, 50, 100, 100)),
        DetectedTableCell(0, 1, BoundingBox(100, 0, 200, 50)),
    )
    words = (
        _word("50.000", (120, 65, 180, 85)),
        _word("Tên", (10, 10, 50, 30)),
        _word("Giá", (120, 10, 160, 30)),
        _word("Sách", (10, 65, 60, 85)),
    )

    table = TableExtractor().extract(cells, words)

    assert table.rows == (("Tên", "Giá"), ("Sách", "50.000"))
    assert table.bbox == BoundingBox(0, 0, 200, 100)
    assert table.merged_cells == ()


@pytest.mark.unit
def test_sorts_multiple_words_inside_each_cell() -> None:
    cell = DetectedTableCell(0, 0, BoundingBox(0, 0, 200, 80))
    words = (
        _word("Việt", (70, 10, 110, 30)),
        _word("Nam", (120, 10, 160, 30)),
        _word("Cộng", (10, 10, 60, 30)),
    )

    table = TableExtractor().extract((cell,), words)

    assert table.rows == (("Cộng Việt Nam",),)


@pytest.mark.unit
def test_preserves_merged_cell_span_and_leaves_covered_slot_empty() -> None:
    cells = (
        DetectedTableCell(0, 0, BoundingBox(0, 0, 200, 50), column_span=2),
        DetectedTableCell(1, 0, BoundingBox(0, 50, 100, 100)),
        DetectedTableCell(1, 1, BoundingBox(100, 50, 200, 100)),
    )
    words = (
        _word("Báo cáo", (40, 10, 150, 35)),
        _word("Tên", (10, 65, 50, 85)),
        _word("Giá", (120, 65, 160, 85)),
    )

    table = TableExtractor().extract(cells, words)

    assert table.rows == (("Báo cáo", ""), ("Tên", "Giá"))
    assert table.merged_cells == (TableCellSpan(0, 0, 1, 2),)
    assert type(table).from_json(table.to_json()) == table


@pytest.mark.unit
def test_ignores_words_outside_detected_cells() -> None:
    cell = DetectedTableCell(0, 0, BoundingBox(0, 0, 100, 50))

    table = TableExtractor().extract(
        (cell,),
        (_word("inside", (10, 10, 40, 30)), _word("outside", (150, 10, 190, 30))),
    )

    assert table.rows == (("inside",),)


@pytest.mark.unit
def test_assigns_a_word_on_an_internal_boundary_only_once() -> None:
    cells = (
        DetectedTableCell(0, 0, BoundingBox(0, 0, 100, 50)),
        DetectedTableCell(0, 1, BoundingBox(100, 0, 200, 50)),
    )

    table = TableExtractor().extract(cells, (_word("boundary", (100, 10, 100, 30)),))

    assert table.rows == (("", "boundary"),)


@pytest.mark.unit
def test_rejects_overlapping_or_empty_cell_layouts() -> None:
    extractor = TableExtractor()
    overlapping = (
        DetectedTableCell(0, 0, BoundingBox(0, 0, 200, 50), column_span=2),
        DetectedTableCell(0, 1, BoundingBox(100, 0, 200, 50)),
    )

    with pytest.raises(ValueError, match="chồng lấn"):
        extractor.extract(overlapping, ())
    with pytest.raises(ValueError, match="ít nhất một ô"):
        extractor.extract((), ())


def test_words_in_a_cell_are_read_line_by_line_left_to_right() -> None:
    """EasyOCR word boxes on one line differ by a few pixels in height."""
    cell = DetectedTableCell(0, 0, BoundingBox(0, 0, 400, 120))
    words = (
        OCRWord("hàng", BoundingBox(110, 10, 190, 40)),
        OCRWord("Mặt", BoundingBox(20, 14, 100, 42)),
        OCRWord("cứng", BoundingBox(110, 62, 190, 90)),
        OCRWord("bìa", BoundingBox(20, 60, 100, 88)),
    )

    table = TableExtractor().extract([cell], words)

    assert table.rows == (("Mặt hàng bìa cứng",),)

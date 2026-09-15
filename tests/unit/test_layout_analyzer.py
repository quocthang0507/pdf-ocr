"""Behavior tests for XY-Cut document reading order."""

from __future__ import annotations

import pytest

from src.constants import BlockType, PageType
from src.core.layout_analyzer import LayoutAnalyzer
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord


def _block(text: str, box: tuple[float, float, float, float]) -> OCRBlock:
    bbox = BoundingBox(*box)
    word = OCRWord(text=text, bbox=bbox)
    line = OCRLine(words=(word,), bbox=bbox)
    return OCRBlock(lines=(line,), bbox=bbox)


@pytest.mark.unit
def test_orders_two_columns_top_to_bottom_before_next_column() -> None:
    blocks = (
        _block("right-2", (320, 180, 560, 240)),
        _block("left-1", (40, 80, 280, 140)),
        _block("right-1", (320, 80, 560, 140)),
        _block("left-2", (40, 180, 280, 240)),
    )

    ordered = LayoutAnalyzer().sort_blocks(blocks)

    assert [block.text for block in ordered] == [
        "left-1",
        "left-2",
        "right-1",
        "right-2",
    ]
    assert [block.reading_order for block in ordered] == [0, 1, 2, 3]


@pytest.mark.unit
def test_recursively_orders_three_columns() -> None:
    blocks = (
        _block("middle", (220, 90, 380, 150)),
        _block("right", (420, 70, 580, 130)),
        _block("left", (20, 110, 180, 170)),
    )

    ordered = LayoutAnalyzer().sort_blocks(blocks)

    assert [block.text for block in ordered] == ["left", "middle", "right"]


@pytest.mark.unit
def test_spanning_title_and_footer_wrap_column_flow() -> None:
    title = _block("title", (20, 10, 580, 60))
    footer = _block("footer", (20, 300, 580, 340))
    blocks = (
        _block("right-2", (320, 190, 560, 250)),
        footer,
        _block("left-2", (40, 190, 280, 250)),
        title,
        _block("right-1", (320, 90, 560, 150)),
        _block("left-1", (40, 90, 280, 150)),
    )

    ordered = LayoutAnalyzer().sort_blocks(blocks)

    assert [block.text for block in ordered] == [
        "title",
        "left-1",
        "left-2",
        "right-1",
        "right-2",
        "footer",
    ]


@pytest.mark.unit
def test_overlapping_blocks_use_stable_geometric_fallback() -> None:
    blocks = (
        _block("lower", (30, 55, 260, 130)),
        _block("upper-right", (80, 20, 280, 100)),
        _block("upper-left", (20, 20, 240, 100)),
    )

    ordered = LayoutAnalyzer().sort_blocks(blocks)

    assert [block.text for block in ordered] == [
        "upper-left",
        "upper-right",
        "lower",
    ]


@pytest.mark.unit
def test_analyze_returns_immutable_page_with_sorted_blocks() -> None:
    page = OCRPage(
        page_number=2,
        width=600,
        height=800,
        blocks=(
            _block("right", (320, 80, 560, 140)),
            _block("left", (40, 100, 280, 160)),
        ),
        page_type=PageType.SCANNED,
        dpi=200,
    )

    analyzed = LayoutAnalyzer().analyze(page)

    assert analyzed is not page
    assert [block.text for block in analyzed.blocks] == ["left", "right"]
    assert analyzed.page_number == 2
    assert analyzed.page_type == PageType.SCANNED
    assert analyzed.dpi == 200
    assert all(block.block_type == BlockType.TEXT for block in analyzed.blocks)

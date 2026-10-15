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


@pytest.mark.unit
def test_merge_paragraphs_combines_consecutive_lines_in_same_column() -> None:
    blocks = (
        _block("Thị trường lao động quý III ghi nhận", (50, 60, 400, 80)),
        _block("mức tăng trưởng ổn định ở nhiều ngành nghề.", (50, 85, 400, 105)),
        _block("Số lượng việc làm tăng cao.", (50, 110, 300, 130)),
    )
    analyzer = LayoutAnalyzer()
    merged = analyzer.merge_paragraphs(blocks)

    assert len(merged) == 1
    assert len(merged[0].lines) == 3
    assert merged[0].text == (
        "Thị trường lao động quý III ghi nhận mức tăng trưởng ổn định "
        "ở nhiều ngành nghề. Số lượng việc làm tăng cao."
    )


@pytest.mark.unit
def test_merge_paragraphs_keeps_separate_columns_distinct() -> None:
    blocks = (
        _block("Cột 1 dòng 1", (50, 60, 250, 80)),
        _block("Cột 1 dòng 2", (50, 85, 250, 105)),
        _block("Cột 2 dòng 1", (320, 60, 520, 80)),
        _block("Cột 2 dòng 2", (320, 85, 520, 105)),
    )
    analyzer = LayoutAnalyzer()
    merged = analyzer.merge_paragraphs(blocks)

    assert len(merged) == 2
    assert merged[0].text == "Cột 1 dòng 1 Cột 1 dòng 2"
    assert merged[1].text == "Cột 2 dòng 1 Cột 2 dòng 2"


@pytest.mark.unit
def test_merge_paragraphs_respects_list_items_and_colons() -> None:
    blocks = (
        _block("Hồ sơ yêu cầu gồm:", (50, 60, 300, 80)),
        _block("1. Bản sao công chứng giấy phép kinh doanh", (50, 85, 450, 105)),
        _block("2. Đơn đăng ký theo mẫu quy định", (50, 110, 450, 130)),
    )
    analyzer = LayoutAnalyzer()
    merged = analyzer.merge_paragraphs(blocks)

    assert len(merged) == 3
    assert merged[0].text == "Hồ sơ yêu cầu gồm:"
    assert merged[1].text == "1. Bản sao công chứng giấy phép kinh doanh"
    assert merged[2].text == "2. Đơn đăng ký theo mẫu quy định"


@pytest.mark.unit
def test_merge_paragraphs_handles_hyphenation_at_line_end() -> None:
    blocks = (
        _block("Hệ thống nhận-", (50, 60, 300, 80)),
        _block("diện văn bản tự động.", (50, 85, 300, 105)),
    )
    analyzer = LayoutAnalyzer()
    merged = analyzer.merge_paragraphs(blocks)

    assert len(merged) == 1
    assert merged[0].text == "Hệ thống nhận-diện văn bản tự động."


def test_analyze_groups_lines_inside_a_table_into_one_table_block() -> None:
    from src.core.models import OCRTable

    table = OCRTable(rows=(("a", "b"),), bbox=BoundingBox(0, 100, 200, 140))
    page = OCRPage(
        page_number=1,
        width=300,
        height=300,
        blocks=(
            _block("Tiêu đề", (0, 0, 200, 20)),
            _block("a", (10, 105, 50, 120)),
            _block("b", (110, 105, 150, 120)),
        ),
        tables=(table,),
    )

    result = LayoutAnalyzer().analyze(page)

    kinds = [block.block_type for block in result.blocks]
    assert kinds == [BlockType.TEXT, BlockType.TABLE]
    assert len(result.blocks[1].lines) == 2


def test_analyze_can_keep_engine_order_when_reading_order_is_off() -> None:
    page = OCRPage(
        page_number=1,
        width=300,
        height=300,
        blocks=(_block("dưới", (0, 200, 100, 220)), _block("trên", (0, 0, 100, 20))),
    )

    result = LayoutAnalyzer().analyze(page, False, reading_order=False)

    assert [block.text for block in result.blocks] == ["dưới", "trên"]


def test_analyze_classifies_typographic_headings_and_caption() -> None:
    def sized_block(text: str, top: float, size: float) -> OCRBlock:
        box = BoundingBox(10, top, 190, top + size * 1.4)
        line = OCRLine(
            words=(OCRWord(text, box),),
            bbox=box,
            font_size=size,
        )
        return OCRBlock(lines=(line,), bbox=box)

    page = OCRPage(
        page_number=1,
        width=300,
        height=300,
        blocks=(
            sized_block("Tiêu đề chính", 0, 24),
            sized_block("Mục lớn", 40, 18),
            sized_block("Mục nhỏ", 70, 16),
            sized_block("Đoạn văn bình thường", 100, 12),
            sized_block("Hình 1. Sơ đồ quy trình", 130, 12),
            sized_block("Một đoạn khác", 160, 12),
            sized_block("Đoạn cuối", 190, 12),
        ),
    )

    result = LayoutAnalyzer().analyze(page)
    labels = {block.text: block.block_type for block in result.blocks}

    assert labels["Tiêu đề chính"] is BlockType.HEADING_1
    assert labels["Mục lớn"] is BlockType.HEADING_2
    assert labels["Mục nhỏ"] is BlockType.HEADING_3
    assert labels["Đoạn văn bình thường"] is BlockType.TEXT
    assert labels["Hình 1. Sơ đồ quy trình"] is BlockType.CAPTION

"""Edits made in the transcript flow back into the page model for export."""

from __future__ import annotations

import pytest

from src.constants import BlockType
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRTable, OCRWord
from src.core.transcript import apply_transcript, render_transcript

pytestmark = pytest.mark.unit


def _line(words: list[tuple[str, float]], top: float) -> OCRLine:
    boxes = []
    placed = []
    for index, (text, confidence) in enumerate(words):
        box = BoundingBox(10 + index * 60, top, 60 + index * 60, top + 20)
        boxes.append(box)
        placed.append(OCRWord(text, box, confidence))
    return OCRLine(
        words=tuple(placed),
        bbox=BoundingBox(boxes[0].x1, top, boxes[-1].x2, top + 20),
    )


def _page() -> OCRPage:
    title = _line([("Tiêu", 0.99), ("đề", 0.99)], 10)
    body_one = _line([("Nội", 0.99), ("dung", 0.5)], 50)
    body_two = _line([("dòng", 0.99), ("hai", 0.99)], 80)
    return OCRPage(
        page_number=1,
        width=400,
        height=300,
        blocks=(
            OCRBlock(lines=(title,), bbox=title.bbox, block_type=BlockType.TITLE),
            OCRBlock(
                lines=(body_one, body_two),
                bbox=BoundingBox(10, 50, 110, 100),
                reading_order=1,
            ),
        ),
    )


def test_rendering_matches_the_editor_paragraphs() -> None:
    """Lines of one block read as a paragraph, exactly as the editor shows them."""
    assert render_transcript(_page()) == "Tiêu đề\n\nNội dung dòng hai"


def test_an_unchanged_transcript_leaves_the_page_untouched() -> None:
    page = _page()

    assert apply_transcript(page, render_transcript(page)) == page


def test_a_corrected_word_keeps_its_position_and_becomes_certain() -> None:
    page = _page()

    edited = apply_transcript(page, "Tiêu đề\n\nNội dụng dòng hai")

    word = edited.blocks[1].lines[0].words[1]
    assert word.text == "dụng"
    assert word.bbox == page.blocks[1].lines[0].words[1].bbox
    assert word.confidence == 1.0
    assert edited.blocks[0] == page.blocks[0]
    assert edited.blocks[0].block_type is BlockType.TITLE


def test_a_correction_keeps_the_line_structure_the_editor_hides() -> None:
    page = _page()

    edited = apply_transcript(page, "Tiêu đề\n\nNội dung dòng ba")

    block = edited.blocks[1]
    assert len(block.lines) == 2
    assert block.lines[1].words[1].text == "ba"
    assert block.lines[1].words[1].bbox == page.blocks[1].lines[1].words[1].bbox


def test_a_rewritten_block_stays_inside_its_area() -> None:
    page = _page()

    edited = apply_transcript(page, "Tiêu đề\n\nNội dung đã được sửa lại hoàn toàn")

    block = edited.blocks[1]
    assert block.text == "Nội dung đã được sửa lại hoàn toàn"
    for line in block.lines:
        for word in line.words:
            assert block.bbox.x1 <= word.bbox.x1 <= word.bbox.x2 <= block.bbox.x2


def test_added_lines_stay_inside_their_block() -> None:
    page = _page()

    edited = apply_transcript(page, "Tiêu đề\n\nMột\nHai\nBa")

    block = edited.blocks[1]
    assert [line.words[0].text for line in block.lines] == ["Một", "Hai", "Ba"]
    for line in block.lines:
        assert block.bbox.y1 <= line.bbox.y1 <= line.bbox.y2 <= block.bbox.y2


def test_a_restructured_transcript_is_kept_in_full() -> None:
    page = _page()

    edited = apply_transcript(page, "Một khối duy nhất\nvới hai dòng")

    assert len(edited.blocks) == 1
    assert render_transcript(edited) == "Một khối duy nhất với hai dòng"


def test_blank_lines_and_blocks_are_dropped() -> None:
    page = _page()

    edited = apply_transcript(page, "Tiêu đề\n\n\n\nNội dung\n\ndòng hai\n\n")

    assert "" not in [word.text for word in _words(edited)]
    assert render_transcript(edited).split() == "Tiêu đề Nội dung dòng hai".split()


def test_clearing_the_transcript_empties_the_page() -> None:
    assert apply_transcript(_page(), "   ").blocks == ()


def _words(page: OCRPage) -> list[OCRWord]:
    return [w for b in page.blocks for line in b.lines for w in line.words]


def test_a_word_split_by_a_hyphen_is_edited_as_one_word() -> None:
    first = _line([("chuyển", 0.99), ("đổi-", 0.99)], 10)
    second = _line([("số", 0.99)], 40)
    page = OCRPage(
        page_number=1,
        width=400,
        height=300,
        blocks=(OCRBlock(lines=(first, second), bbox=BoundingBox(10, 10, 130, 60)),),
    )
    assert render_transcript(page) == "chuyển đổi-số"

    edited = apply_transcript(page, "chuyển đổi-số hoá")

    assert edited.blocks[0].text == "chuyển đổi-số hoá"


def test_an_unchanged_hyphenated_block_is_kept() -> None:
    first = _line([("đổi-", 0.99)], 10)
    second = _line([("mới", 0.99)], 40)
    page = OCRPage(
        page_number=1,
        width=400,
        height=300,
        blocks=(OCRBlock(lines=(first, second), bbox=BoundingBox(10, 10, 60, 60)),),
    )

    assert apply_transcript(page, "đổi-mới") is page


def test_a_hyphenated_word_can_be_corrected() -> None:
    first = _line([("đổi-", 0.99)], 10)
    second = _line([("mơí", 0.4)], 40)
    page = OCRPage(
        page_number=1,
        width=400,
        height=300,
        blocks=(OCRBlock(lines=(first, second), bbox=BoundingBox(10, 10, 60, 60)),),
    )

    edited = apply_transcript(page, "đổi-mới")

    assert edited.blocks[0].text == "đổi-mới"
    assert edited.blocks[0].lines[0].words[0].bbox == first.words[0].bbox


def _table_page() -> OCRPage:
    cells = (("Mặt hàng", "Số lượng"), ("Bút", "50"))
    words = tuple(
        OCRWord(
            text,
            BoundingBox(20 + 100 * col, 20 + 40 * row, 90 + 100 * col, 50 + 40 * row),
        )
        for row, line in enumerate(cells)
        for col, text in enumerate(line)
    )
    table_block = OCRBlock(
        lines=(OCRLine(words=words, bbox=BoundingBox(20, 20, 190, 90)),),
        bbox=BoundingBox(20, 20, 190, 90),
        block_type=BlockType.TABLE,
    )
    note = OCRWord("Ghi", BoundingBox(20, 120, 60, 140))
    note_block = OCRBlock(
        lines=(OCRLine(words=(note,), bbox=BoundingBox(20, 120, 60, 140)),),
        bbox=BoundingBox(20, 120, 60, 140),
        reading_order=1,
    )
    return OCRPage(
        page_number=1,
        width=400,
        height=400,
        blocks=(table_block, note_block),
        tables=(OCRTable(rows=cells, bbox=BoundingBox(20, 20, 190, 90)),),
    )


def test_a_table_block_shows_its_rows_and_tab_separated_cells() -> None:
    assert render_transcript(_table_page()) == ("Mặt hàng\tSố lượng\nBút\t50\n\nGhi")


def test_editing_a_table_cell_updates_the_table_and_leaves_the_rest() -> None:
    page = _table_page()

    edited = apply_transcript(page, "Mặt hàng\tSố lượng\nBút\t55\n\nGhi chú")

    assert edited.tables[0].rows == (("Mặt hàng", "Số lượng"), ("Bút", "55"))
    assert edited.blocks[0] == page.blocks[0]
    assert edited.blocks[1].text == "Ghi chú"


def test_an_unchanged_table_survives_an_edit_elsewhere() -> None:
    page = _table_page()

    edited = apply_transcript(page, render_transcript(page) + " thêm")

    assert edited.tables == page.tables

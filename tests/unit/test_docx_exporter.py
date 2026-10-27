"""Word exports preserve headings, paragraphs, page breaks, and tables."""

from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

from src.constants import BlockType
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
    TableCellSpan,
)
from src.exporters.docx_exporter import DOCXExporter

pytestmark = pytest.mark.unit


def _block(
    text: str,
    y: float,
    *,
    block_type: BlockType = BlockType.TEXT,
    font_size: float | None = None,
) -> OCRBlock:
    box = BoundingBox(40, y, 500, y + 40)
    word = OCRWord(text, box)
    line = OCRLine((word,), box, font_size=font_size)
    return OCRBlock((line,), box, block_type=block_type)


def _document() -> OCRDocument:
    table = OCRTable(
        rows=(("Kết quả", ""), ("Tên", "Giá"), ("Sách", "50.000")),
        bbox=BoundingBox(40, 180, 500, 300),
        merged_cells=(TableCellSpan(0, 0, 1, 2),),
    )
    first_page = OCRPage(
        1,
        600,
        800,
        blocks=(
            _block("Báo cáo OCR", 20, block_type=BlockType.TITLE, font_size=22),
            _block("Kết quả nhận diện", 80, block_type=BlockType.TITLE, font_size=17),
            _block("Nội dung tiếng Việt", 130),
        ),
        tables=(table,),
    )
    second_page = OCRPage(2, 600, 800, blocks=(_block("Trang thứ hai", 20),))
    return OCRDocument((first_page, second_page), title="Báo cáo")


def test_exports_headings_paragraphs_and_page_breaks(tmp_path: Path) -> None:
    destination = tmp_path / "result.docx"

    DOCXExporter().export(_document(), destination)

    exported = Document(destination)
    visible = [paragraph for paragraph in exported.paragraphs if paragraph.text]
    assert [paragraph.text for paragraph in visible] == [
        "Báo cáo OCR",
        "Kết quả nhận diện",
        "Nội dung tiếng Việt",
        "Trang thứ hai",
    ]
    assert visible[0].style.name == "Heading 1"
    assert visible[1].style.name == "Heading 2"
    assert visible[2].style.name == "Normal"
    assert 'w:type="page"' in exported.element.xml


def test_exports_heading_levels_and_captions_with_word_semantic_styles(
    tmp_path: Path,
) -> None:
    page = OCRPage(
        1,
        600,
        800,
        blocks=(
            _block("Chương", 20, block_type=BlockType.HEADING_1),
            _block("Mục", 80, block_type=BlockType.HEADING_2),
            _block("Tiểu mục", 140, block_type=BlockType.HEADING_3),
            _block("Hình 1. Sơ đồ", 200, block_type=BlockType.CAPTION),
        ),
    )
    destination = tmp_path / "semantic-layout.docx"

    DOCXExporter().export(OCRDocument((page,)), destination)

    visible = [
        paragraph for paragraph in Document(destination).paragraphs if paragraph.text
    ]
    assert [paragraph.style.name for paragraph in visible] == [
        "Heading 1",
        "Heading 2",
        "Heading 3",
        "Caption",
    ]


def test_exports_styled_tables_and_merged_cells(tmp_path: Path) -> None:
    destination = tmp_path / "tables.docx"

    DOCXExporter().export(_document(), destination)

    exported = Document(destination)
    table = exported.tables[0]
    assert table.style.name == "Table Grid"
    assert table.cell(0, 0).text == "Kết quả"
    assert table.cell(0, 0)._tc is table.cell(0, 1)._tc
    assert [cell.text for cell in table.rows[2].cells] == ["Sách", "50.000"]
    borders = table._tbl.tblPr.find(qn("w:tblBorders"))
    assert borders is not None
    assert {edge.get(qn("w:color")) for edge in borders} == {"D9D9D9"}


def test_sets_letter_page_size_and_document_metadata(tmp_path: Path) -> None:
    destination = tmp_path / "metadata.docx"

    DOCXExporter().export(_document(), destination)

    exported = Document(destination)
    section = exported.sections[0]
    assert section.page_width.inches == pytest.approx(8.5, abs=0.01)
    assert section.page_height.inches == pytest.approx(11, abs=0.01)
    assert exported.core_properties.title == "Báo cáo"


def _analysed_report_page() -> OCRPage:
    """A page whose table the layout analyser folded into a TABLE block."""
    from src.core.layout_analyzer import LayoutAnalyzer

    def box_block(text: str, box: tuple[float, float, float, float]) -> OCRBlock:
        bbox = BoundingBox(*box)
        return OCRBlock((OCRLine((OCRWord(text, bbox),), bbox),), bbox)

    table = OCRTable(
        rows=(("Mặt hàng", "Số lượng"), ("Sổ tay", "12")),
        bbox=BoundingBox(180, 280, 1020, 420),
    )
    blocks = (
        box_block("Báo cáo doanh thu quý III", (200, 100, 1400, 160)),
        box_block("Mặt hàng", (200, 300, 500, 340)),
        box_block("Số lượng", (700, 300, 1000, 340)),
        box_block("Sổ tay", (200, 360, 500, 400)),
        box_block("12", (700, 360, 1000, 400)),
        box_block("Tổng kết: doanh thu tăng.", (200, 600, 1400, 640)),
    )
    page = OCRPage(1, 1600, 2000, blocks=blocks, tables=(table,))
    return LayoutAnalyzer().analyze(page)


def test_a_table_is_written_once_where_it_stands_on_the_page(tmp_path: Path) -> None:
    document = OCRDocument((_analysed_report_page(),), source_path="bao-cao.pdf")
    output = tmp_path / "bao-cao.docx"

    DOCXExporter().export(document, output)

    body = Document(str(output)).element.body
    order = [
        (
            "TABLE"
            if child.tag == qn("w:tbl")
            else "".join(node.text or "" for node in child.iter(qn("w:t")))
        )
        for child in body.iterchildren()
        if child.tag in (qn("w:p"), qn("w:tbl"))
    ]
    assert order == ["Báo cáo doanh thu quý III", "TABLE", "Tổng kết: doanh thu tăng."]


def test_centred_and_right_aligned_lines_keep_their_alignment(tmp_path: Path) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    def at(text: str, x1: float, x2: float, y: float) -> OCRBlock:
        box = BoundingBox(x1, y, x2, y + 60)
        return OCRBlock(
            (OCRLine((OCRWord(text, box),), box),), box, reading_order=int(y)
        )

    page = OCRPage(
        1,
        2480,
        3508,
        blocks=(
            at("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 690, 1790, 200),
            at("Hà Nội, ngày 25 tháng 10 năm 2026", 1300, 2240, 320),
            at(
                "Đoạn văn bản trải hết chiều rộng vùng chữ của trang giấy.",
                240,
                2240,
                440,
            ),
            at("Kính gửi: Phòng Kế toán", 240, 1100, 560),
        ),
    )
    output = tmp_path / "don.docx"

    DOCXExporter().export(OCRDocument((page,), source_path="don.pdf"), output)

    alignments = [p.alignment for p in Document(str(output)).paragraphs if p.text]
    assert alignments == [
        WD_ALIGN_PARAGRAPH.CENTER,
        WD_ALIGN_PARAGRAPH.RIGHT,
        WD_ALIGN_PARAGRAPH.LEFT,
        WD_ALIGN_PARAGRAPH.LEFT,
    ]

"""Microsoft Word exporter for OCR paragraphs, headings, and tables."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.document import Document as DocumentType
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from src.constants import BlockType
from src.core.models import OCRBlock, OCRDocument, OCRPage, OCRTable
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter


@register_exporter("docx", "Microsoft Word", extensions=(".docx",))
class DOCXExporter(BaseExporter):
    """Create a readable Word document from immutable OCR structure."""

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        word_document = Document()
        self._configure_document(word_document, document.title)
        for index, page in enumerate(document.pages):
            if index:
                word_document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            self._add_page(word_document, page)
        word_document.save(str(output_path))

    @staticmethod
    def _configure_document(document: DocumentType, title: str) -> None:
        for section in document.sections:
            section.orientation = WD_ORIENT.PORTRAIT
            section.page_width = Inches(8.5)
            section.page_height = Inches(11)
            section.top_margin = Inches(0.75)
            section.bottom_margin = Inches(0.75)
            section.left_margin = Inches(0.75)
            section.right_margin = Inches(0.75)
        document.core_properties.title = title
        for style_name, size in (
            ("Normal", 11),
            ("Heading 1", 18),
            ("Heading 2", 15),
            ("Heading 3", 13),
        ):
            style = document.styles[style_name]
            style.font.name = "Arial"
            style.font.size = Pt(size)
            style.font.color.rgb = RGBColor(0, 0, 0)

    def _add_page(self, document: DocumentType, page: OCRPage) -> None:
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            self._add_block(document, page, block)
        for table in page.tables:
            self._add_table(document, table)

    def _add_block(
        self, document: DocumentType, page: OCRPage, block: OCRBlock
    ) -> None:
        style = self._heading_style(block)
        paragraph = document.add_paragraph(style=style)
        paragraph.alignment = self._alignment(page, block)
        paragraph.paragraph_format.space_after = Pt(6 if style == "Normal" else 8)
        for index, line in enumerate(block.lines):
            if index:
                paragraph.add_run().add_break()
            paragraph.add_run(line.text)

    @staticmethod
    def _heading_style(block: OCRBlock) -> str:
        if block.block_type != BlockType.TITLE:
            return "Normal"
        sizes = [line.font_size for line in block.lines if line.font_size is not None]
        font_size = max(sizes, default=20)
        if font_size >= 20:
            return "Heading 1"
        if font_size >= 16:
            return "Heading 2"
        return "Heading 3"

    @staticmethod
    def _alignment(page: OCRPage, block: OCRBlock) -> WD_ALIGN_PARAGRAPH:
        center = (block.bbox.x1 + block.bbox.x2) / 2
        if block.bbox.width < page.width * 0.8 and abs(center - page.width / 2) < 20:
            return WD_ALIGN_PARAGRAPH.CENTER
        if block.bbox.x1 > page.width * 0.55:
            return WD_ALIGN_PARAGRAPH.RIGHT
        return WD_ALIGN_PARAGRAPH.LEFT

    def _add_table(self, document: DocumentType, source: OCRTable) -> None:
        if not source.rows or not source.rows[0]:
            return
        table = document.add_table(rows=len(source.rows), cols=len(source.rows[0]))
        table.style = "Table Grid"
        table.autofit = True
        for row_index, row in enumerate(source.rows):
            for column_index, value in enumerate(row):
                cell = table.cell(row_index, column_index)
                cell.text = value
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                self._style_cell(cell, header=row_index == 0)
        for span in source.merged_cells:
            start = table.cell(span.row, span.column)
            end = table.cell(
                span.row + span.row_span - 1,
                span.column + span.column_span - 1,
            )
            merged = start.merge(end)
            merged.text = source.rows[span.row][span.column]
            self._style_cell(merged, header=span.row == 0)
        self._set_table_borders(table._tbl)

    @staticmethod
    def _style_cell(cell: object, *, header: bool) -> None:
        tc = cell._tc  # type: ignore[attr-defined]
        properties = tc.get_or_add_tcPr()
        margins = OxmlElement("w:tcMar")
        for side in ("top", "left", "bottom", "right"):
            node = OxmlElement(f"w:{side}")
            node.set(qn("w:w"), "100")
            node.set(qn("w:type"), "dxa")
            margins.append(node)
        properties.append(margins)
        if header:
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "1F4E78")
            properties.append(shading)
            for run in cell.paragraphs[0].runs:  # type: ignore[attr-defined]
                run.bold = True
                run.font.color.rgb = RGBColor(255, 255, 255)

    @staticmethod
    def _set_table_borders(table: object) -> None:
        properties = table.tblPr  # type: ignore[attr-defined]
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            node = OxmlElement(f"w:{edge}")
            node.set(qn("w:val"), "single")
            node.set(qn("w:sz"), "4")
            node.set(qn("w:color"), "D9D9D9")
            borders.append(node)
        properties.append(borders)

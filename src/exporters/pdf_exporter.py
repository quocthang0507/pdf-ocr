"""Searchable PDF exporter preserving source pages and adding invisible text."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from src.core.exceptions import ExportError
from src.core.models import BoundingBox, OCRDocument, OCRPage, OCRWord
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter

_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)


@register_exporter("pdf", "Searchable PDF", extensions=(".pdf",))
class PDFExporter(BaseExporter):
    """Overlay OCR words invisibly without rasterizing the original pages."""

    def _export(self, document: OCRDocument, output_path: Path) -> None:
        source_path = Path(document.source_path).expanduser()
        if not source_path.is_file():
            raise ExportError("Không tìm thấy tài liệu nguồn để tạo PDF.")
        source = self._open_source(source_path)
        converted: pymupdf.Document | None = None
        output = pymupdf.open()
        try:
            source_pdf = source
            if not source.is_pdf:
                converted = pymupdf.open("pdf", source.convert_to_pdf())
                source_pdf = converted
            self._copy_pages(document, source_pdf, output)
            if document.title:
                output.set_metadata({"title": document.title})
            output_path.write_bytes(output.tobytes(garbage=4, deflate=True))
        finally:
            output.close()
            if converted is not None:
                converted.close()
            source.close()

    @staticmethod
    def _open_source(source_path: Path) -> pymupdf.Document:
        try:
            return pymupdf.open(str(source_path))
        except Exception as error:
            raise ExportError("Không thể mở tài liệu nguồn để tạo PDF.") from error

    def _copy_pages(
        self,
        document: OCRDocument,
        source: pymupdf.Document,
        output: pymupdf.Document,
    ) -> None:
        if not document.pages:
            raise ExportError("Tài liệu xuất phải có ít nhất một trang.")
        for ocr_page in document.pages:
            source_index = ocr_page.page_number - 1
            if source_index >= source.page_count:
                raise ExportError("Số trang OCR không khớp với tài liệu nguồn.")
            source_page = source[source_index]
            target_page = output.new_page(
                width=source_page.rect.width, height=source_page.rect.height
            )
            target_page.show_pdf_page(target_page.rect, source, source_index)
            self._add_text_layer(target_page, ocr_page)

    def _add_text_layer(self, target: pymupdf.Page, ocr_page: OCRPage) -> None:
        font_name = "ocrfont"
        font_path = next((path for path in _FONT_CANDIDATES if path.is_file()), None)
        if font_path is None:
            font_name = "helv"
            font = pymupdf.Font(fontname=font_name)
        else:
            target.insert_font(fontname=font_name, fontfile=str(font_path))
            font = pymupdf.Font(fontfile=str(font_path))
        scale_x = target.rect.width / ocr_page.width
        scale_y = target.rect.height / ocr_page.height
        for block in ocr_page.blocks:
            for line in block.lines:
                for word in line.words:
                    self._insert_word(target, word, scale_x, scale_y, font_name, font)

    @staticmethod
    def _insert_word(
        page: pymupdf.Page,
        word: OCRWord,
        scale_x: float,
        scale_y: float,
        font_name: str,
        font: pymupdf.Font,
    ) -> None:
        rect = PDFExporter._scaled_rect(word.bbox, scale_x, scale_y, page.rect)
        natural_width = max(font.text_length(word.text), 0.01)
        font_size = min(rect.height * 0.8, rect.width * 0.95 / natural_width)
        if font_size <= 0:
            return
        page.insert_textbox(
            rect,
            word.text,
            fontname=font_name,
            fontsize=max(1.0, font_size),
            render_mode=3,
            overlay=True,
        )

    @staticmethod
    def _scaled_rect(
        bbox: BoundingBox,
        scale_x: float,
        scale_y: float,
        page_rect: pymupdf.Rect,
    ) -> pymupdf.Rect:
        return pymupdf.Rect(
            max(page_rect.x0, bbox.x1 * scale_x),
            max(page_rect.y0, bbox.y1 * scale_y),
            min(page_rect.x1, bbox.x2 * scale_x),
            min(page_rect.y1, bbox.y2 * scale_y),
        )

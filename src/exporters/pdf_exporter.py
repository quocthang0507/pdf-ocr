"""Searchable PDF exporter preserving source pages and adding invisible text."""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf

from src.config import PDF_COMPRESSION_LEVELS, ConfigManager
from src.core.exceptions import ExportError
from src.core.models import BoundingBox, OCRDocument, OCRPage, OCRWord
from src.exporters.base_exporter import BaseExporter
from src.exporters.exporter_registry import register_exporter
from src.utils.logger import logger

# Arial covers Vietnamese; Arial Unicode (~22 MB) is only a last resort.
_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
)
_SAVE_LEVEL_ARGS: dict[str, dict[str, object]] = {
    "fast": {"garbage": 1, "deflate": False},
    "balanced": {"garbage": 3, "deflate": True},
    "max": {"garbage": 4, "deflate": True, "clean": True},
}


@register_exporter("pdf", "Searchable PDF", extensions=(".pdf",))
class PDFExporter(BaseExporter):
    """Overlay OCR words invisibly without rasterizing the original pages."""

    def __init__(self, *, compression_level: str | None = None) -> None:
        if (
            compression_level is not None
            and compression_level not in PDF_COMPRESSION_LEVELS
        ):
            raise ValueError("Mức nén PDF không hợp lệ.")
        self._compression_level = compression_level

    def _resolve_save_kwargs(self) -> dict[str, object]:
        level = self._compression_level
        if level is None:
            try:
                level = ConfigManager(use_qsettings=False).load().pdf_compression_level
            except Exception:
                level = "balanced"
        return dict(_SAVE_LEVEL_ARGS.get(level, _SAVE_LEVEL_ARGS["balanced"]))

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
            output_path.write_bytes(output.tobytes(**self._resolve_save_kwargs()))
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
        font = _text_layer_font(document)
        for ocr_page in document.pages:
            source_index = ocr_page.page_number - 1
            if source_index >= source.page_count:
                raise ExportError("Số trang OCR không khớp với tài liệu nguồn.")
            source_page = source[source_index]
            target_page = output.new_page(
                width=source_page.rect.width, height=source_page.rect.height
            )
            target_page.show_pdf_page(target_page.rect, source, source_index)
            self._add_text_layer(
                target_page, ocr_page, _native_text_areas(source_page), font
            )

    def _add_text_layer(
        self,
        target: pymupdf.Page,
        ocr_page: OCRPage,
        native_areas: tuple[pymupdf.Rect, ...] = (),
        font_data: bytes | None = None,
    ) -> None:
        scale_x = target.rect.width / ocr_page.width
        scale_y = target.rect.height / ocr_page.height
        missing = [
            word
            for block in ocr_page.blocks
            for line in block.lines
            for word in line.words
            if not _already_searchable(
                self._scaled_rect(word.bbox, scale_x, scale_y, target.rect),
                native_areas,
            )
        ]
        if not missing:
            # A page that is searchable already needs no font at all; an
            # unused embedded font cannot be subset and cost ~0.5 MB a page.
            return
        if font_data is None:
            font_name = "helv"
            font = pymupdf.Font(fontname=font_name)
        else:
            font_name = "ocrfont"
            target.insert_font(fontname=font_name, fontbuffer=font_data)
            font = pymupdf.Font(fontbuffer=font_data)
        for word in missing:
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


def _text_layer_font(document: OCRDocument) -> bytes | None:
    """The font for the hidden text, cut down to the characters it needs.

    Embedding a whole font made a one-page scan about 15 MB. Keeping only the
    document's own characters also keeps the text correct: Arial draws a
    space and a no-break space, or "-" and a soft hyphen, with one glyph, and
    a PDF reader would then copy and search the wrong character.
    """
    font_path = next((path for path in _FONT_CANDIDATES if path.is_file()), None)
    if font_path is None:
        return None
    characters = {
        character
        for page in document.pages
        for block in page.blocks
        for line in block.lines
        for word in line.words
        for character in word.text
    }
    try:
        return _subset_font(font_path, characters)
    except Exception as error:  # fontTools missing or an unusual font file
        logger.debug("Không rút gọn được phông chữ PDF: {}", error)
        return font_path.read_bytes()


def _subset_font(font_path: Path, characters: set[str]) -> bytes:
    from fontTools import subset
    from fontTools.ttLib import TTFont

    options = subset.Options()
    options.name_IDs = ["*"]
    options.notdef_outline = True
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes={ord(character) for character in characters})
    font = TTFont(str(font_path))
    subsetter.subset(font)
    buffer = io.BytesIO()
    font.save(buffer)
    return buffer.getvalue()


def _native_text_areas(page: pymupdf.Page) -> tuple[pymupdf.Rect, ...]:
    """Where the source page already has real, selectable text."""
    return tuple(pymupdf.Rect(entry[:4]) for entry in page.get_text("words"))


def _already_searchable(
    rect: pymupdf.Rect, native_areas: tuple[pymupdf.Rect, ...]
) -> bool:
    """Skip OCR words the source already carries, so nothing is found twice."""
    centre = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
    return any(area.contains(centre) for area in native_areas)

"""Searchable PDF exports preserve source pixels and add invisible OCR text."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from src.constants import PageType
from src.core.exceptions import ExportError
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRDocument,
    OCRLine,
    OCRPage,
    OCRWord,
)
from src.exporters.pdf_exporter import PDFExporter

pytestmark = pytest.mark.unit


@pytest.fixture
def scanned_source(tmp_path: Path) -> Path:
    source = tmp_path / "source.pdf"
    image = Image.fromarray(np.full((100, 200, 3), (235, 240, 245), dtype=np.uint8))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.insert_image(page.rect, stream=stream.getvalue())
    document.save(source)
    document.close()
    return source


def _ocr_document(source: Path) -> OCRDocument:
    first_box = BoundingBox(10, 10, 70, 30)
    second_box = BoundingBox(80, 10, 145, 30)
    line = OCRLine(
        words=(OCRWord("Hello", first_box), OCRWord("world", second_box)),
        bbox=BoundingBox(10, 10, 145, 30),
    )
    block = OCRBlock(lines=(line,), bbox=line.bbox)
    page = OCRPage(
        page_number=1,
        width=200,
        height=100,
        blocks=(block,),
        page_type=PageType.SCANNED,
        dpi=72,
    )
    return OCRDocument((page,), source_path=str(source), title="Searchable scan")


def test_exports_searchable_invisible_text_over_unchanged_source_pixels(
    scanned_source: Path, tmp_path: Path
) -> None:
    destination = tmp_path / "searchable.pdf"

    PDFExporter().export(_ocr_document(scanned_source), destination)

    source = pymupdf.open(scanned_source)
    exported = pymupdf.open(destination)
    assert exported.page_count == 1
    assert " ".join(exported[0].get_text().split()) == "Hello world"
    assert exported[0].search_for("Hello")
    assert exported[0].get_pixmap().samples == source[0].get_pixmap().samples
    streams = [exported.xref_stream(xref) for xref in exported[0].get_contents()]
    assert any(b"3 Tr" in content for content in streams)
    source.close()
    exported.close()


def test_scales_ocr_coordinates_to_the_source_page(
    scanned_source: Path, tmp_path: Path
) -> None:
    document = _ocr_document(scanned_source)
    scaled_page = document.pages[0].with_updates(width=400, height=200)
    destination = tmp_path / "scaled.pdf"

    PDFExporter().export(document.with_updates(pages=(scaled_page,)), destination)

    exported = pymupdf.open(destination)
    match = exported[0].search_for("Hello")[0]
    exported.close()
    assert match.x0 == pytest.approx(5, abs=2)
    assert match.y0 == pytest.approx(5, abs=3)


def test_rejects_missing_source_or_page_mismatch(tmp_path: Path) -> None:
    missing = _ocr_document(tmp_path / "missing.pdf")
    with pytest.raises(ExportError, match="nguồn"):
        PDFExporter().export(missing, tmp_path / "missing-output.pdf")

    source = tmp_path / "one-page.pdf"
    pdf = pymupdf.open()
    pdf.new_page()
    pdf.save(source)
    pdf.close()
    invalid_page = missing.pages[0].with_updates(page_number=2)
    mismatched = missing.with_updates(pages=(invalid_page,), source_path=str(source))
    with pytest.raises(ExportError, match="trang"):
        PDFExporter().export(mismatched, tmp_path / "mismatch.pdf")


def _source_with_native_text(tmp_path: Path) -> Path:
    """A page whose "Hello" is real text and whose right half is a bare scan."""
    source = tmp_path / "hybrid.pdf"
    document = pymupdf.open()
    page = document.new_page(width=200, height=100)
    page.insert_text((10, 26), "Hello", fontsize=14)
    document.save(source)
    document.close()
    return source


def test_text_the_source_already_carries_is_not_duplicated(tmp_path: Path) -> None:
    """A second, invisible copy would double every search hit and every paste."""
    source = _source_with_native_text(tmp_path)
    destination = tmp_path / "no-duplicates.pdf"

    PDFExporter().export(_ocr_document(source), destination)

    exported = pymupdf.open(destination)
    words = [entry[4] for entry in exported[0].get_text("words")]
    exported.close()
    assert words.count("Hello") == 1
    assert words.count("world") == 1

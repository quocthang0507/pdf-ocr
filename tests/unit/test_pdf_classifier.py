"""Unit tests for PDF page classifier and direct text extraction."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from src.constants import PageType
from src.core.models import OCRPage
from src.core.pdf_classifier import PDFClassifier, classify_page, extract_text_page


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    """PDF containing pure native text."""
    pdf_path = tmp_path / "text_only.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 80), "CONG HOA XA HOI CHU NGHIA VIET NAM", fontsize=14)
    page.insert_text((50, 110), "Doc lap - Tu do - Hanh phuc", fontsize=12)
    page.insert_text(
        (50, 150),
        "Thong bao ve viec trien khai he thong xu ly du lieu va OCR tu dong.",
        fontsize=11,
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    """PDF containing only a scanned raster image without text layer."""
    pdf_path = tmp_path / "scanned_only.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    img_data = np.full((600, 400, 3), 220, dtype=np.uint8)
    pil_img = Image.fromarray(img_data)
    stream = io.BytesIO()
    pil_img.save(stream, format="PNG")

    page.insert_image(pymupdf.Rect(20, 20, 575, 820), stream=stream.getvalue())
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def hybrid_pdf(tmp_path: Path) -> Path:
    """PDF containing both a prominent image and native vector text."""
    pdf_path = tmp_path / "hybrid.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    # Insert an image covering top half
    img_data = np.full((300, 400, 3), 180, dtype=np.uint8)
    pil_img = Image.fromarray(img_data)
    stream = io.BytesIO()
    pil_img.save(stream, format="PNG")
    page.insert_image(pymupdf.Rect(50, 50, 500, 350), stream=stream.getvalue())

    # Insert substantial text in bottom half
    page.insert_text((50, 400), "Hinh 1: So do kien truc he thong", fontsize=12)
    page.insert_text(
        (50, 430), "Cac thanh phan chinh gom Loader, Preprocessor, Engine.", fontsize=11
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.mark.unit
def test_classify_text_based_page(text_pdf: Path) -> None:
    doc = pymupdf.open(str(text_pdf))
    page = doc[0]
    p_type = classify_page(page)
    doc.close()
    assert p_type == PageType.TEXT_BASED


@pytest.mark.unit
def test_classify_scanned_page(scanned_pdf: Path) -> None:
    doc = pymupdf.open(str(scanned_pdf))
    page = doc[0]
    p_type = classify_page(page)
    doc.close()
    assert p_type == PageType.SCANNED


@pytest.mark.unit
def test_classify_hybrid_page(hybrid_pdf: Path) -> None:
    doc = pymupdf.open(str(hybrid_pdf))
    page = doc[0]
    p_type = classify_page(page)
    doc.close()
    assert p_type == PageType.HYBRID


@pytest.mark.unit
def test_extract_text_page_structure(text_pdf: Path) -> None:
    doc = pymupdf.open(str(text_pdf))
    page = doc[0]
    ocr_page = extract_text_page(page, page_number=1, dpi=300)
    doc.close()

    assert isinstance(ocr_page, OCRPage)
    assert ocr_page.page_number == 1
    assert ocr_page.page_type == PageType.TEXT_BASED
    assert ocr_page.dpi == 300
    assert ocr_page.width > 2000
    assert ocr_page.height > 3000
    assert len(ocr_page.blocks) >= 1

    # Check extracted text
    page_text = " ".join(block.text for block in ocr_page.blocks)
    assert "CONG HOA" in page_text
    assert "Doc lap" in page_text

    # Check word bounding boxes and lines
    first_block = ocr_page.blocks[0]
    assert len(first_block.lines) >= 1
    first_line = first_block.lines[0]
    assert first_line.bbox.width > 0
    assert first_line.bbox.height > 0
    assert len(first_line.words) >= 1
    assert first_line.words[0].bbox.width > 0


@pytest.mark.unit
def test_classifier_service_document(text_pdf: Path, scanned_pdf: Path) -> None:
    classifier = PDFClassifier()
    doc1 = pymupdf.open(str(text_pdf))
    types1 = classifier.classify_document(doc1)
    doc1.close()
    assert types1 == [PageType.TEXT_BASED]

    doc2 = pymupdf.open(str(scanned_pdf))
    types2 = classifier.classify_document(doc2)
    doc2.close()
    assert types2 == [PageType.SCANNED]

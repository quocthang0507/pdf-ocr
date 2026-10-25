"""Unit tests for the PDF Editor and viewing color-mode service."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from src.core.pdf_editor import (
    PDFProperties,
    add_highlight_annotation,
    add_stamp_image,
    add_text_note_annotation,
    apply_page_color_mode,
    compress_pdf,
    delete_pages_from_pdf,
    extract_pages_to_pdf,
    inspect_pdf_properties,
    merge_pdfs,
    protect_pdf_with_password,
    redact_region_in_pdf,
    reorder_pages_in_pdf,
    rotate_pages_in_pdf,
    update_pdf_bookmarks,
    update_pdf_metadata,
)


def _create_sample_pdf(path: Path, pages: int = 3, prefix: str = "Page") -> Path:
    doc = pymupdf.open()
    for idx in range(1, pages + 1):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 100), f"{prefix} {idx} secret-token-{idx}", fontsize=14)
    doc.set_metadata({"title": "Sample Title", "author": "Tester"})
    doc.set_toc([[1, "Chapter 1", 1]])
    doc.save(str(path))
    doc.close()
    return path


def test_inspect_pdf_properties_returns_metadata_fonts_and_dimensions(
    tmp_path: Path,
) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "sample.pdf", pages=3)

    props = inspect_pdf_properties(pdf_path)

    assert isinstance(props, PDFProperties)
    assert props.page_count == 3
    assert props.page_width_pt == pytest.approx(400.0)
    assert props.page_height_pt == pytest.approx(600.0)
    assert props.file_size_bytes > 0
    assert props.is_encrypted is False
    assert props.metadata["title"] == "Sample Title"
    assert props.metadata["author"] == "Tester"
    assert len(props.fonts) >= 1
    assert props.bookmarks_count == 1


def test_rotate_pages_in_pdf_persists_rotation_in_place(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "rotate.pdf", pages=2)

    out = rotate_pages_in_pdf(pdf_path, [1], 90)

    assert out == pdf_path.resolve()
    with pymupdf.open(str(pdf_path)) as doc:
        assert doc[0].rotation == 90
        assert doc[1].rotation == 0


def test_delete_pages_from_pdf_removes_selected_pages(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "delete.pdf", pages=3)

    delete_pages_from_pdf(pdf_path, [2])

    with pymupdf.open(str(pdf_path)) as doc:
        assert len(doc) == 2
        assert "Page 1" in doc[0].get_text("text")
        assert "Page 3" in doc[1].get_text("text")


def test_delete_pages_raises_when_deleting_all_pages(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "delete_all.pdf", pages=2)

    with pytest.raises(ValueError, match="không thể xóa toàn bộ"):
        delete_pages_from_pdf(pdf_path, [1, 2])


def test_extract_pages_to_pdf_writes_subset_document(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "source.pdf", pages=4)
    extracted = tmp_path / "extracted.pdf"

    out = extract_pages_to_pdf(pdf_path, [2, 4], extracted)

    assert out == extracted.resolve()
    with pymupdf.open(str(extracted)) as doc:
        assert len(doc) == 2
        assert "Page 2" in doc[0].get_text("text")
        assert "Page 4" in doc[1].get_text("text")


def test_merge_pdfs_combines_multiple_files_in_order(tmp_path: Path) -> None:
    first = _create_sample_pdf(tmp_path / "first.pdf", pages=2, prefix="First")
    second = _create_sample_pdf(tmp_path / "second.pdf", pages=1, prefix="Second")
    merged = tmp_path / "merged.pdf"

    out = merge_pdfs([first, second], merged)

    assert out == merged.resolve()
    with pymupdf.open(str(merged)) as doc:
        assert len(doc) == 3
        assert "First 1" in doc[0].get_text("text")
        assert "Second 1" in doc[2].get_text("text")


def test_reorder_pages_in_pdf_rearranges_page_sequence(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "reorder.pdf", pages=3)

    reorder_pages_in_pdf(pdf_path, [3, 1, 2])

    with pymupdf.open(str(pdf_path)) as doc:
        assert len(doc) == 3
        assert "Page 3" in doc[0].get_text("text")
        assert "Page 1" in doc[1].get_text("text")
        assert "Page 2" in doc[2].get_text("text")


def test_add_highlight_and_text_note_annotations(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "annot.pdf", pages=1)

    add_highlight_annotation(pdf_path, 1, (0.1, 0.1, 0.5, 0.25))
    add_text_note_annotation(pdf_path, 1, (0.2, 0.3), "Ghi chú kiểm tra")

    with pymupdf.open(str(pdf_path)) as doc:
        annots = list(doc[0].annots() or [])
        assert len(annots) == 2
        contents = [a.info.get("content", "") for a in annots]
        assert "Ghi chú kiểm tra" in contents


def test_add_stamp_image_embeds_image_on_page(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "stamp.pdf", pages=1)
    stamp_path = tmp_path / "sig.png"
    Image.new("RGBA", (80, 40), (20, 80, 200, 255)).save(stamp_path)

    add_stamp_image(pdf_path, 1, (0.5, 0.7, 0.8, 0.85), stamp_path)

    with pymupdf.open(str(pdf_path)) as doc:
        images = doc[0].get_images()
        assert len(images) == 1


def test_redact_region_in_pdf_permanently_removes_underlying_text(
    tmp_path: Path,
) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "redact.pdf", pages=1)

    # Text is inserted at (50, 100) on a 400x600 page -> y around 0.12..0.20
    redact_region_in_pdf(pdf_path, 1, (0.05, 0.10, 0.90, 0.22))

    with pymupdf.open(str(pdf_path)) as doc:
        remaining = doc[0].get_text("text")
        assert "secret-token-1" not in remaining


def test_update_pdf_metadata_and_bookmarks(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "meta.pdf", pages=3)

    update_pdf_metadata(
        pdf_path,
        {
            "title": "Tài liệu mới",
            "author": "Nguyễn Văn A",
            "subject": "OCR & PDF",
            "keywords": "pdf, ocr, vietnamese",
        },
    )
    update_pdf_bookmarks(pdf_path, [(1, "Mở đầu", 1), (1, "Kết luận", 3)])

    props = inspect_pdf_properties(pdf_path)
    assert props.metadata["title"] == "Tài liệu mới"
    assert props.metadata["author"] == "Nguyễn Văn A"
    assert props.metadata["subject"] == "OCR & PDF"
    assert props.metadata["keywords"] == "pdf, ocr, vietnamese"
    assert props.bookmarks_count == 2


def test_protect_pdf_with_password_encrypts_file(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "plain.pdf", pages=1)
    encrypted_path = tmp_path / "encrypted.pdf"

    protect_pdf_with_password(pdf_path, "secret123", output_path=encrypted_path)

    with pymupdf.open(str(encrypted_path)) as doc:
        assert doc.is_encrypted is True
        assert doc.authenticate("secret123") > 0


def test_compress_pdf_produces_valid_pdf(tmp_path: Path) -> None:
    pdf_path = _create_sample_pdf(tmp_path / "uncompressed.pdf", pages=2)
    compressed_path = tmp_path / "compressed.pdf"

    out = compress_pdf(pdf_path, level="max", output_path=compressed_path)

    assert out == compressed_path.resolve()
    assert compressed_path.stat().st_size > 0
    with pymupdf.open(str(compressed_path)) as doc:
        assert len(doc) == 2


def test_apply_page_color_mode_transforms_normal_sepia_and_night() -> None:
    white_page = np.full((20, 20, 3), 255, dtype=np.uint8)

    normal = apply_page_color_mode(white_page, "normal")
    sepia = apply_page_color_mode(white_page, "sepia")
    night = apply_page_color_mode(white_page, "night")

    assert np.array_equal(normal, white_page)
    # Night mode inverts white (255) to dark (< 30)
    assert int(night[0, 0, 0]) < 30
    # Sepia mode tints white to warm cream (R > G > B)
    r, g, b = int(sepia[0, 0, 0]), int(sepia[0, 0, 1]), int(sepia[0, 0, 2])
    assert r > g > b

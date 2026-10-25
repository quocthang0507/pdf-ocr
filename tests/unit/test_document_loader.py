"""Tests for DocumentLoader and image utilities."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from src.core.document_loader import DocumentLoader, LoadedPage
from src.core.exceptions import DocumentLoadError
from src.utils.image_utils import (
    ensure_rgb_ndarray,
    ndarray_to_pil,
    pil_to_ndarray,
    validate_image_dimensions,
)


@pytest.fixture
def sample_text_pdf(tmp_path: Path) -> Path:
    """Create a multi-page PDF containing native vector text."""
    pdf_path = tmp_path / "sample_text.pdf"
    doc = pymupdf.open()

    # Page 1: with text
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 72), "Hoa don gia tri gia tang", fontsize=16)
    page1.insert_text((50, 100), "Cong hoa Xa hoi Chu nghia Viet Nam", fontsize=12)

    # Page 2: another page with text
    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((50, 72), "Trang 2: Chi tiet cac mat hang", fontsize=12)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_scanned_pdf(tmp_path: Path) -> Path:
    """Create a PDF containing only a raster image and no text layer."""
    pdf_path = tmp_path / "sample_scanned.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)

    # Create an image and insert into PDF
    img_data = np.full((300, 200, 3), 200, dtype=np.uint8)
    pil_img = Image.fromarray(img_data)
    img_bytes = io.BytesIO()
    pil_img.save(img_bytes, format="PNG")
    page.insert_image(pymupdf.Rect(50, 50, 250, 350), stream=img_bytes.getvalue())

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


@pytest.fixture
def sample_encrypted_pdf(tmp_path: Path) -> Path:
    """Create a password-protected PDF."""
    pdf_path = tmp_path / "sample_encrypted.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 72), "Bảo mật", fontsize=12)

    perm = int(
        pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY
    )
    doc.save(
        str(pdf_path),
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="admin",
        user_pw="secret123",
        permissions=perm,
    )
    doc.close()
    return pdf_path


@pytest.fixture
def sample_png_image(tmp_path: Path) -> Path:
    """Create a standard RGB PNG image."""
    img_path = tmp_path / "test_image.png"
    img = Image.new("RGB", (300, 400), color=(255, 128, 64))
    img.save(img_path)
    return img_path


@pytest.fixture
def sample_multipage_tiff(tmp_path: Path) -> Path:
    """Create a multi-frame TIFF image."""
    tiff_path = tmp_path / "multipage.tiff"
    frame1 = Image.new("RGB", (200, 300), color=(255, 255, 255))
    frame2 = Image.new("RGB", (200, 300), color=(100, 100, 100))
    frame1.save(
        tiff_path,
        save_all=True,
        append_images=[frame2],
        compression="tiff_deflate",
    )
    return tiff_path


# ==============================================================================
# Tests for Image Utils
# ==============================================================================


@pytest.mark.unit
def test_ensure_rgb_ndarray_from_grayscale() -> None:
    gray = np.zeros((100, 100), dtype=np.uint8)
    rgb = ensure_rgb_ndarray(gray)
    assert rgb.shape == (100, 100, 3)
    assert rgb.dtype == np.uint8


@pytest.mark.unit
def test_ensure_rgb_ndarray_from_rgba() -> None:
    rgba = np.zeros((100, 100, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    rgb = ensure_rgb_ndarray(rgba)
    assert rgb.shape == (100, 100, 3)
    assert rgb.dtype == np.uint8


@pytest.mark.unit
def test_ensure_rgb_ndarray_rejects_invalid_type() -> None:
    with pytest.raises(TypeError, match="numpy ndarray"):
        ensure_rgb_ndarray("not an array")  # type: ignore[arg-type]


@pytest.mark.unit
def test_pil_to_ndarray_and_back() -> None:
    pil_img = Image.new("RGB", (50, 60), color=(10, 20, 30))
    arr = pil_to_ndarray(pil_img)
    assert isinstance(arr, np.ndarray)
    assert arr.shape == (60, 50, 3)
    assert arr[0, 0].tolist() == [10, 20, 30]

    restored = ndarray_to_pil(arr)
    assert restored.size == (50, 60)
    assert restored.mode == "RGB"


@pytest.mark.unit
def test_ensure_rgb_ndarray_from_single_channel() -> None:
    single_channel = np.zeros((50, 50, 1), dtype=np.uint8)
    rgb = ensure_rgb_ndarray(single_channel)
    assert rgb.shape == (50, 50, 3)

    invalid_channels = np.zeros((50, 50, 5), dtype=np.uint8)
    with pytest.raises(ValueError, match="kênh màu"):
        ensure_rgb_ndarray(invalid_channels)

    invalid_ndim = np.zeros((10, 10, 10, 10), dtype=np.uint8)
    with pytest.raises(ValueError, match="chiều mảng"):
        ensure_rgb_ndarray(invalid_ndim)


@pytest.mark.unit
def test_qimage_conversion_roundtrip() -> None:
    from src.utils.image_utils import ndarray_to_qimage, qimage_to_ndarray

    arr = np.full((40, 60, 3), 128, dtype=np.uint8)
    arr[0, 0] = [255, 0, 0]
    qimg = ndarray_to_qimage(arr)
    assert qimg.width() == 60
    assert qimg.height() == 40

    restored = qimage_to_ndarray(qimg)
    assert restored.shape == (40, 60, 3)
    assert np.array_equal(restored[0, 0], [255, 0, 0])


@pytest.mark.unit
def test_validate_image_dimensions() -> None:
    validate_image_dimensions(100, 100)
    with pytest.raises(ValueError, match="Kích thước"):
        validate_image_dimensions(0, 100)
    with pytest.raises(ValueError, match="Kích thước"):
        validate_image_dimensions(100, -5)
    with pytest.raises(ValueError, match="vượt quá giới hạn"):
        validate_image_dimensions(20000, 100)


# ==============================================================================
# Tests for Document Loader
# ==============================================================================


@pytest.mark.unit
def test_load_text_based_pdf(sample_text_pdf: Path) -> None:
    loader = DocumentLoader(sample_text_pdf)
    assert loader.page_count == 2

    pages = loader.load_all_pages(dpi=150)
    assert len(pages) == 2

    page1 = pages[0]
    assert isinstance(page1, LoadedPage)
    assert page1.page_number == 1
    assert page1.has_text_layer is True
    assert isinstance(page1.image, np.ndarray)
    assert page1.image.shape[2] == 3  # RGB
    assert page1.dpi == 150
    assert "Hoa don" in page1.extracted_text


@pytest.mark.unit
def test_load_scanned_pdf_detects_no_text(sample_scanned_pdf: Path) -> None:
    loader = DocumentLoader(sample_scanned_pdf)
    assert loader.page_count == 1
    page = loader.load_page(1, dpi=150)
    assert page.page_number == 1
    assert page.has_text_layer is False
    assert page.extracted_text.strip() == ""
    assert isinstance(page.image, np.ndarray)


@pytest.mark.unit
def test_render_dpi_scales_proportionally(sample_text_pdf: Path) -> None:
    loader = DocumentLoader(sample_text_pdf)
    page_150 = loader.load_page(1, dpi=150)
    page_300 = loader.load_page(1, dpi=300)

    h150, w150 = page_150.image.shape[:2]
    h300, w300 = page_300.image.shape[:2]
    assert abs(w300 - 2 * w150) <= 3
    assert abs(h300 - 2 * h150) <= 3


@pytest.mark.unit
def test_load_single_png_image(sample_png_image: Path) -> None:
    loader = DocumentLoader(sample_png_image)
    assert loader.page_count == 1
    page = loader.load_page(1)
    assert page.page_number == 1
    assert page.has_text_layer is False
    assert page.image.shape == (400, 300, 3)


@pytest.mark.unit
def test_load_multipage_tiff(sample_multipage_tiff: Path) -> None:
    loader = DocumentLoader(sample_multipage_tiff)
    assert loader.page_count == 2
    pages = loader.load_all_pages()
    assert len(pages) == 2
    assert pages[0].image.shape == (300, 200, 3)
    assert pages[1].image.shape == (300, 200, 3)


@pytest.mark.unit
def test_encrypted_pdf_raises_document_load_error(sample_encrypted_pdf: Path) -> None:
    with pytest.raises(DocumentLoadError, match="mật khẩu|khóa|giải mã"):
        DocumentLoader(sample_encrypted_pdf)


@pytest.mark.unit
def test_encrypted_pdf_opens_with_valid_password_and_rejects_wrong_password(
    sample_encrypted_pdf: Path,
) -> None:
    from src.core.exceptions import PasswordRequiredError

    with pytest.raises(PasswordRequiredError):
        DocumentLoader(sample_encrypted_pdf, password="wrong-password")

    with DocumentLoader(sample_encrypted_pdf, password="secret123") as loader:
        assert loader.page_count == 1
        page = loader.load_page(1, dpi=150)
        assert page.has_text_layer is True
        assert page.extracted_text.strip() != ""


@pytest.mark.unit
def test_nonexistent_file_raises_document_load_error(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.pdf"
    with pytest.raises(DocumentLoadError, match="không tồn tại"):
        DocumentLoader(missing)


@pytest.mark.unit
def test_directory_path_raises_document_load_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentLoadError, match="phải là tệp tin"):
        DocumentLoader(tmp_path)


@pytest.mark.unit
def test_corrupted_file_raises_document_load_error(tmp_path: Path) -> None:
    corrupt_file = tmp_path / "corrupt.pdf"
    corrupt_file.write_bytes(b"This is not a valid PDF content at all.")
    with pytest.raises(DocumentLoadError, match="hỏng|không thể mở"):
        DocumentLoader(corrupt_file)


@pytest.mark.unit
def test_unsupported_format_raises_document_load_error(tmp_path: Path) -> None:
    unsupported = tmp_path / "data.xyz"
    unsupported.write_bytes(b"binary data")
    with pytest.raises(DocumentLoadError, match="Định dạng.*không được hỗ trợ"):
        DocumentLoader(unsupported)


@pytest.mark.unit
def test_empty_file_raises_document_load_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(DocumentLoadError, match="rỗng|không thể mở"):
        DocumentLoader(empty)


@pytest.mark.unit
def test_context_manager_support(sample_text_pdf: Path) -> None:
    with DocumentLoader(sample_text_pdf) as loader:
        assert loader.page_count == 2
        assert loader.is_pdf is True
        assert loader.file_path == sample_text_pdf.resolve()
        page = loader.load_page(1)
        assert page.page_number == 1

        with pytest.raises(ValueError, match="Số trang"):
            loader.load_page(0)
        with pytest.raises(ValueError, match="Số trang"):
            loader.load_page(99)
        with pytest.raises(ValueError, match="DPI"):
            loader.load_page(1, dpi=-5)


@pytest.mark.unit
def test_loaded_page_validation() -> None:
    valid_img = np.full((10, 10, 3), 255, dtype=np.uint8)
    with pytest.raises(ValueError, match="Số trang"):
        LoadedPage(page_number=0, image=valid_img, has_text_layer=False)

    with pytest.raises(TypeError, match="numpy.ndarray"):
        LoadedPage(page_number=1, image="not_array", has_text_layer=False)  # type: ignore[arg-type]

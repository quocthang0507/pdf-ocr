"""Document loading and ingestion for PDFs and image files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf
from PIL import Image

from src.core.exceptions import DocumentLoadError
from src.utils.image_utils import pil_to_ndarray, validate_image_dimensions
from src.utils.logger import logger

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
}
SUPPORTED_EXTENSIONS = {".pdf"} | SUPPORTED_IMAGE_EXTENSIONS


@dataclass(frozen=True)
class LoadedPage:
    """Represents a single loaded document page with its rendered image and metadata."""

    page_number: int
    image: np.ndarray
    has_text_layer: bool
    extracted_text: str = ""
    dpi: int = 300
    width: int = 0
    height: int = 0

    def __post_init__(self) -> None:
        """Validate and populate dimensions."""
        if self.page_number <= 0:
            raise ValueError(f"Số trang phải lớn hơn 0, nhận được: {self.page_number}")

        if not isinstance(self.image, np.ndarray):
            raise TypeError("Thuộc tính image phải là numpy.ndarray")

        h, w = self.image.shape[:2]
        validate_image_dimensions(w, h)

        if self.width == 0:
            object.__setattr__(self, "width", w)
        if self.height == 0:
            object.__setattr__(self, "height", h)


class DocumentLoader:
    """Loader for PDF and multi-format image documents."""

    def __init__(self, file_path: str | Path) -> None:
        """Initialize DocumentLoader and open the document.

        Args:
            file_path: Path to the target file.

        Raises:
            DocumentLoadError: If file is missing, empty, corrupt, or unsupported.
        """
        self._path = Path(file_path).resolve()
        self._validate_path()

        self._suffix = self._path.suffix.lower()
        if self._suffix not in SUPPORTED_EXTENSIONS:
            raise DocumentLoadError(
                f"Định dạng tệp '{self._suffix}' không được hỗ trợ. "
                f"Chỉ chấp nhận: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        self._doc: pymupdf.Document | None = None
        self._pil_img: Image.Image | None = None
        self._is_pdf = self._suffix == ".pdf"
        self._page_count = 0

        self._open_document()

    def _validate_path(self) -> None:
        """Verify file existence and non-zero size."""
        if not self._path.exists():
            raise DocumentLoadError(f"Tệp tin '{self._path}' không tồn tại.")
        if not self._path.is_file():
            raise DocumentLoadError(f"Đường dẫn '{self._path}' phải là tệp tin.")
        if self._path.stat().st_size == 0:
            raise DocumentLoadError(f"Tệp tin '{self._path}' rỗng hoặc không thể mở.")

    def _open_document(self) -> None:
        """Open PDF or image file securely."""
        if self._is_pdf:
            self._open_pdf()
        else:
            self._open_image()

    def _open_pdf(self) -> None:
        """Open PDF using PyMuPDF."""
        try:
            self._doc = pymupdf.open(str(self._path))
        except Exception as err:
            logger.error(f"Failed to open PDF {self._path}: {err}")
            raise DocumentLoadError(
                f"Tệp PDF '{self._path}' bị hỏng hoặc không thể mở: {err}"
            ) from err

        if self._doc.is_encrypted or self._doc.needs_pass:
            self._doc.close()
            raise DocumentLoadError(
                f"Tệp PDF '{self._path}' đã được khóa bảo vệ bằng mật khẩu."
            )

        self._page_count = len(self._doc)
        if self._page_count == 0:
            self._doc.close()
            raise DocumentLoadError(
                f"Tệp PDF '{self._path}' rỗng hoặc không có trang nào."
            )

    def _open_image(self) -> None:
        """Open image file using PIL."""
        try:
            self._pil_img = Image.open(str(self._path))
            self._page_count = getattr(self._pil_img, "n_frames", 1)
        except Exception as err:
            logger.error(f"Failed to open image {self._path}: {err}")
            raise DocumentLoadError(
                f"Tệp ảnh '{self._path}' bị hỏng hoặc không thể mở: {err}"
            ) from err

    @property
    def file_path(self) -> Path:
        """Return the resolved document file path."""
        return self._path

    @property
    def page_count(self) -> int:
        """Return the total number of pages."""
        return self._page_count

    @property
    def is_pdf(self) -> bool:
        """Return whether the loaded document is a PDF."""
        return self._is_pdf

    def load_page(self, page_number: int, dpi: int = 300) -> LoadedPage:
        """Load and render a single page by 1-based page number.

        Args:
            page_number: 1-indexed page number.
            dpi: Rendering DPI for PDF rasterization.

        Returns:
            LoadedPage: Loaded page object.

        Raises:
            ValueError: If page_number is out of range or dpi <= 0.
            DocumentLoadError: If rendering fails.
        """
        if page_number < 1 or page_number > self._page_count:
            raise ValueError(
                f"Số trang {page_number} không hợp lệ "
                f"(tài liệu có {self._page_count} trang)."
            )
        if dpi <= 0:
            raise ValueError(f"DPI phải lớn hơn 0, nhận được: {dpi}")

        if self._is_pdf and self._doc is not None:
            return self._render_pdf_page(page_number, dpi)
        elif self._pil_img is not None:
            return self._load_image_page(page_number, dpi)
        else:
            raise DocumentLoadError("Tài liệu chưa được khởi tạo hoặc đã bị đóng.")

    def _render_pdf_page(self, page_number: int, dpi: int) -> LoadedPage:
        """Render a PDF page to RGB ndarray and extract text."""
        if self._doc is None:
            raise DocumentLoadError("Tài liệu PDF chưa được nạp hoặc đã bị đóng.")
        try:
            page = self._doc.load_page(page_number - 1)
            zoom = dpi / 72.0
            matrix = pymupdf.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)

            arr = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                (pixmap.height, pixmap.width, 3)
            )
            text = page.get_text()
            has_text = len(text.strip()) > 0

            return LoadedPage(
                page_number=page_number,
                image=arr.copy(),
                has_text_layer=has_text,
                extracted_text=text,
                dpi=dpi,
                width=pixmap.width,
                height=pixmap.height,
            )
        except Exception as err:
            logger.error(f"Error rendering PDF page {page_number}: {err}")
            raise DocumentLoadError(
                f"Không thể kết xuất trang {page_number}: {err}"
            ) from err

    def _load_image_page(self, page_number: int, dpi: int) -> LoadedPage:
        """Extract a single frame from image."""
        if self._pil_img is None:
            raise DocumentLoadError("Tệp ảnh chưa được nạp hoặc đã bị đóng.")
        try:
            self._pil_img.seek(page_number - 1)
            arr = pil_to_ndarray(self._pil_img)
            h, w = arr.shape[:2]
            return LoadedPage(
                page_number=page_number,
                image=arr,
                has_text_layer=False,
                extracted_text="",
                dpi=dpi,
                width=w,
                height=h,
            )
        except Exception as err:
            logger.error(f"Error loading image frame {page_number}: {err}")
            raise DocumentLoadError(
                f"Không thể đọc khung hình {page_number}: {err}"
            ) from err

    def load_all_pages(self, dpi: int = 300) -> list[LoadedPage]:
        """Load and render all pages in the document.

        Args:
            dpi: Rendering DPI.

        Returns:
            list[LoadedPage]: List of all loaded pages.
        """
        return [self.load_page(idx, dpi=dpi) for idx in range(1, self._page_count + 1)]

    def close(self) -> None:
        """Release open file resources."""
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        if self._pil_img is not None:
            self._pil_img.close()
            self._pil_img = None

    def __enter__(self) -> DocumentLoader:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

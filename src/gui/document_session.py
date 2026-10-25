"""State of one open document: rendered pages, recognised results, and edits."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from src.core.document_loader import DocumentLoader, LoadedPage
from src.core.exceptions import DocumentLoadError, PDFOCRError
from src.core.models import OCRDocument, OCRPage
from src.core.pdf_editor import apply_page_color_mode
from src.core.transcript import render_transcript
from src.utils.logger import logger

if TYPE_CHECKING:
    from src.services.settings_store import SettingsStore

IMAGE_CACHE_SIZE = 2

LoaderFactory = Callable[[Path], DocumentLoader]


class DocumentSession:
    """Keep the document open for previews and remember what was recognised.

    Pages are rendered on demand and only the last few are kept, because a
    300 DPI page weighs tens of megabytes. Results survive `close`, so a
    document the user comes back to still shows its recognised text.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        loader_factory: LoaderFactory = DocumentLoader,
        cache_size: int = IMAGE_CACHE_SIZE,
        color_mode: str = "normal",
        password: str | None = None,
        session_store: SettingsStore | None = None,
    ) -> None:
        self.path = Path(path)
        self._loader_factory = loader_factory
        self._loader: DocumentLoader | None = None
        self._password = password
        self._session_store = session_store
        self._pages: OrderedDict[tuple[int, int], LoadedPage] = OrderedDict()
        self._results: dict[int, OCRPage] = (
            session_store.load_ocr_pages(self.path) if session_store is not None else {}
        )
        self._rotations: dict[int, int] = {}
        self._cache_size = max(1, min(32, int(cache_size)))
        self._color_mode = "normal"
        self.set_page_color_mode(color_mode)
        self._current = 1

    # -- document ---------------------------------------------------------

    @property
    def cache_size(self) -> int:
        return self._cache_size

    def set_cache_size(self, max_pages: int) -> None:
        """Update the rendered-page LRU limit and evict older pages if needed."""
        self._cache_size = max(1, min(32, int(max_pages)))
        while len(self._pages) > self._cache_size:
            self._pages.popitem(last=False)

    def _open(self) -> DocumentLoader:
        if self._loader is None:
            try:
                if (
                    self._password is not None
                    and self._loader_factory is DocumentLoader
                ):
                    self._loader = DocumentLoader(self.path, password=self._password)
                else:
                    self._loader = self._loader_factory(self.path)
            except PDFOCRError:
                raise
            except Exception as error:
                raise DocumentLoadError("Không thể mở tài liệu đã chọn.") from error
        return self._loader

    @property
    def is_pdf(self) -> bool:
        return bool(self._open().is_pdf)

    @property
    def page_count(self) -> int:
        return int(self._open().page_count)

    @property
    def current_page(self) -> int:
        return self._current

    @property
    def page_color_mode(self) -> str:
        return self._color_mode

    def set_page_color_mode(self, mode: str) -> None:
        normalized = mode.strip().lower()
        if normalized in ("normal", "sepia", "night"):
            self._color_mode = normalized

    def file_size_bytes(self) -> int:
        try:
            return int(self.path.stat().st_size)
        except OSError:
            return 0

    def go_to(self, page_number: int) -> int:
        """Move to a page, clamped to the document so a bad jump is harmless."""
        self._current = max(1, min(page_number, self.page_count))
        return self._current

    def step(self, delta: int) -> int:
        return self.go_to(self._current + delta)

    def page_rotation(self, page_number: int) -> int:
        return self._rotations.get(page_number, 0)

    def rotate_page(self, page_number: int, delta_degrees: int) -> int:
        """Rotate a page in 90-degree increments and return the new angle."""
        angle = (self._rotations.get(page_number, 0) + delta_degrees) % 360
        if angle == 0:
            self._rotations.pop(page_number, None)
        else:
            self._rotations[page_number] = angle
        return angle

    def reload(self) -> None:
        """Reload document from disk after an in-place PDF edit."""
        self._pages.clear()
        self._rotations.clear()
        if self._loader is not None:
            self._loader.close()
            self._loader = None
        total = self.page_count
        self._results = {
            num: page for num, page in self._results.items() if 1 <= num <= total
        }
        self._current = max(1, min(self._current, total))

    def outline(self) -> tuple[tuple[int, str, int], ...]:
        """Extract PDF bookmarks as (level, title, page_number) tuples."""
        loader = self._open()
        if not loader.is_pdf:
            return ()
        try:
            import pymupdf

            with pymupdf.open(str(self.path)) as pdf:
                toc = pdf.get_toc(simple=True)
            return tuple(
                (int(item[0]), str(item[1]).strip(), max(1, int(item[2])))
                for item in toc
                if len(item) >= 3 and str(item[1]).strip()
            )
        except Exception:
            return ()

    def search_text(self, query: str) -> list[tuple[int, str]]:
        """Search all pages across recognised OCR results and native PDF text."""
        needle = query.strip().lower()
        if not needle:
            return []
        matches: list[tuple[int, str]] = []
        total = self.page_count
        for number in range(1, total + 1):
            result = self._results.get(number)
            text = (
                render_transcript(result)
                if result is not None
                else self._page_raw_text(number)
            )
            lower = text.lower()
            pos = lower.find(needle)
            if pos >= 0:
                start = max(0, pos - 24)
                end = min(len(text), pos + len(needle) + 36)
                snippet = " ".join(text[start:end].split())
                matches.append((number, snippet))
        return matches

    def _page_raw_text(self, page_number: int) -> str:
        try:
            return self.native_text(page_number, dpi=72)
        except Exception:
            return ""

    def close(self) -> None:
        """Release the file and the rendered pages; results are kept."""
        self._pages.clear()
        if self._loader is not None:
            self._loader.close()
            self._loader = None

    # -- rendering --------------------------------------------------------

    def _loaded(self, page_number: int, dpi: int) -> LoadedPage:
        """Render one page, reusing a recent render of the same page."""
        key = (page_number, dpi)
        cached = self._pages.get(key)
        if cached is not None:
            self._pages.move_to_end(key)
            return cached
        try:
            loaded = self._open().load_page(page_number, dpi)
        except PDFOCRError:
            raise
        except Exception as error:
            raise DocumentLoadError("Không thể hiển thị trang tài liệu.") from error
        self._pages[key] = loaded
        while len(self._pages) > self._cache_size:
            self._pages.popitem(last=False)
        return loaded

    def image(self, page_number: int, *, dpi: int) -> np.ndarray:
        raw = self._loaded(page_number, dpi).image
        rotated = _rotate_image(raw, self.page_rotation(page_number))
        return apply_page_color_mode(rotated, self._color_mode)

    def thumbnail(self, page_number: int, max_side: int = 72) -> np.ndarray:
        """Render a small thumbnail image for the navigation page list."""
        raw = self._loaded(page_number, 72).image
        rotated = _rotate_image(raw, self.page_rotation(page_number))
        h, w = rotated.shape[:2]
        scale = min(1.0, float(max_side) / float(max(h, w, 1)))
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        return cv2.resize(rotated, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def native_text(self, page_number: int, *, dpi: int) -> str:
        """The page's own text layer, so a text-based page reads before OCR."""
        loaded = self._loaded(page_number, dpi)
        return loaded.extracted_text if loaded.has_text_layer else ""

    def image_for(self, page: OCRPage) -> np.ndarray:
        """The page image in the same pixel space as the result's boxes."""
        image = self.image(page.page_number, dpi=page.dpi)
        width, height = round(page.width), round(page.height)
        if image.shape[1] == width and image.shape[0] == height:
            return image
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)

    def cached_images(self) -> int:
        return len(self._pages)

    # -- results ----------------------------------------------------------

    def store(self, page: OCRPage) -> None:
        self._results[page.page_number] = page
        if self._session_store is not None:
            try:
                self._session_store.save_ocr_pages(
                    self.path,
                    tuple(self._results[num] for num in self.recognised_pages()),
                )
            except Exception as err:
                logger.debug("Không lưu được kết quả phiên OCR: {}", err)

    def clear_results(self) -> None:
        """Clear in-memory and cached OCR results for this document."""
        self._results.clear()
        if self._session_store is not None:
            try:
                self._session_store.clear_ocr_pages(self.path)
            except Exception as err:
                logger.debug("Không xóa được kết quả phiên OCR: {}", err)

    def result(self, page_number: int) -> OCRPage | None:
        return self._results.get(page_number)

    def recognised_pages(self) -> tuple[int, ...]:
        return tuple(sorted(self._results))

    def has_results(self) -> bool:
        return bool(self._results)

    def document(self) -> OCRDocument:
        """Every recognised page in reading order, ready for an exporter."""
        pages = tuple(self._results[number] for number in self.recognised_pages())
        return OCRDocument(pages, source_path=str(self.path), title=self.path.stem)


def _rotate_image(image: np.ndarray, angle: int) -> np.ndarray:
    if angle == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image

"""State of one open document: rendered pages, recognised results, and edits."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

from src.core.document_loader import DocumentLoader, LoadedPage
from src.core.exceptions import DocumentLoadError, PDFOCRError
from src.core.models import OCRDocument, OCRPage

IMAGE_CACHE_SIZE = 2

LoaderFactory = Callable[[Path], DocumentLoader]


class DocumentSession:
    """Keep the document open for previews and remember what was recognised.

    Pages are rendered on demand and only the last few are kept, because a
    300 DPI page weighs tens of megabytes. Results survive `close`, so a
    document the user comes back to still shows its recognised text.
    """

    def __init__(
        self, path: str | Path, *, loader_factory: LoaderFactory = DocumentLoader
    ) -> None:
        self.path = Path(path)
        self._loader_factory = loader_factory
        self._loader: DocumentLoader | None = None
        self._pages: OrderedDict[tuple[int, int], LoadedPage] = OrderedDict()
        self._results: dict[int, OCRPage] = {}
        self._current = 1

    # -- document ---------------------------------------------------------

    def _open(self) -> DocumentLoader:
        if self._loader is None:
            try:
                self._loader = self._loader_factory(self.path)
            except PDFOCRError:
                raise
            except Exception as error:
                raise DocumentLoadError("Không thể mở tài liệu đã chọn.") from error
        return self._loader

    @property
    def page_count(self) -> int:
        return int(self._open().page_count)

    @property
    def current_page(self) -> int:
        return self._current

    def go_to(self, page_number: int) -> int:
        """Move to a page, clamped to the document so a bad jump is harmless."""
        self._current = max(1, min(page_number, self.page_count))
        return self._current

    def step(self, delta: int) -> int:
        return self.go_to(self._current + delta)

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
        while len(self._pages) > IMAGE_CACHE_SIZE:
            self._pages.popitem(last=False)
        return loaded

    def image(self, page_number: int, *, dpi: int) -> np.ndarray:
        return self._loaded(page_number, dpi).image

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

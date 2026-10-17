"""End-to-end document pipeline with native-text branching and OCR fallback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import numpy as np
import pymupdf

from src.constants import PageType
from src.core.document_loader import DocumentLoader, LoadedPage
from src.core.exceptions import OCREngineError, PDFOCRError
from src.core.layout_analyzer import LayoutAnalyzer
from src.core.models import OCRBlock, OCRDocument, OCRPage
from src.core.pdf_classifier import PDFClassifier
from src.core.postprocessor import Postprocessor
from src.core.preprocessor import (
    deskew_image,
    detect_orientation,
    enhance_document_image,
    remove_borders,
    rotate_orientation,
)
from src.engines.base_engine import BaseOCREngine
from src.engines.engine_registry import engine_session, release_accelerator_memory
from src.services.weights_manager import ModelWeightsManager

LoaderFactory = Callable[[str | Path], DocumentLoader]
ImagePreprocessor = Callable[[np.ndarray], np.ndarray]


def preprocess_for_ocr(
    image: np.ndarray, stages: Mapping[str, bool] | None = None
) -> np.ndarray:
    """Run the Phase 2 image cleanup stages in their safe order.

    `stages` maps orientation/deskew/borders/enhance to on or off; a stage
    that is not mentioned stays on.
    """

    def enabled(name: str) -> bool:
        return True if stages is None else bool(stages.get(name, True))

    if enabled("orientation"):
        image = rotate_orientation(image, detect_orientation(image))
    if enabled("deskew"):
        image, _ = deskew_image(image)
    if enabled("borders"):
        image = remove_borders(image)
    if enabled("enhance"):
        image = enhance_document_image(image)
    return image


@dataclass(frozen=True)
class PageOptions:
    """Per-run choices for cleanup, layout and table recognition."""

    preprocessing: Mapping[str, bool] | None = None
    detect_tables: bool = True
    reading_order: bool = True
    merge_paragraphs: bool = True
    spell_check: bool = True
    force_ocr: bool = False

    @classmethod
    def from_mapping(cls, options: Mapping[str, object]) -> PageOptions:
        """Read the GUI option mapping defensively; bad shapes fall back to defaults."""
        raw = options.get("preprocessing")
        stages = (
            {str(key): bool(value) for key, value in raw.items()}
            if isinstance(raw, Mapping)
            else None
        )

        def flag(key: str, default: bool = True) -> bool:
            value = options.get(key, default)
            return value if isinstance(value, bool) else default

        return cls(
            preprocessing=stages,
            detect_tables=flag("detect_tables"),
            reading_order=flag("reading_order"),
            merge_paragraphs=flag("merge_paragraphs"),
            spell_check=flag("spell_check"),
            force_ocr=flag("force_ocr", False),
        )


@dataclass
class _OpenDocument:
    """One document held open for a whole batch, with its page types cached."""

    loader: DocumentLoader
    pdf: pymupdf.Document | None
    page_types: tuple[PageType, ...]


class PageSession:
    """Recognise pages one at a time while the models stay loaded.

    Reloading a model for every page would dominate the run time, so the
    session keeps engines and documents open and releases only the per-page
    buffers and accelerator cache. Closing it unloads everything, even when
    the caller failed part way through.
    """

    def __init__(
        self,
        service: PipelineService,
        *,
        engine_ids: tuple[str, ...],
        device: str,
        dpi: int,
        engine_config: Mapping[str, object] | None,
        page_options: PageOptions | None = None,
    ) -> None:
        self._service = service
        self._page_options = page_options or PageOptions()
        self._engine_ids = engine_ids
        self._device = device
        self._dpi = dpi
        self._config = engine_config
        self._stack = ExitStack()
        self._engines: dict[str, BaseOCREngine] = {}
        self._documents: dict[str, _OpenDocument] = {}

    def __enter__(self) -> PageSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Unload every engine and document, then hand the memory back."""
        self._documents.clear()
        self._engines.clear()
        self._stack.close()
        release_accelerator_memory(self._device)

    def page_count(self, file_path: str | Path) -> int:
        return int(self._open(file_path).loader.page_count)

    def recognise(self, file_path: str | Path, page_number: int) -> OCRPage:
        """Recognise one page, freeing its working memory before returning."""
        try:
            document = self._open(file_path)
            page = self._service.recognise_page(
                document,
                page_number,
                self._engine_ids,
                self._device,
                self._dpi,
                self._config,
                self._stack,
                self._engines,
                self._page_options,
            )
            return self._service.postprocessor.process_page(
                page, spell_check=self._page_options.spell_check
            )
        except PDFOCRError:
            raise
        except Exception as error:
            raise PDFOCRError("Không thể nhận diện trang tài liệu.") from error
        finally:
            release_accelerator_memory(self._device)

    def _open(self, file_path: str | Path) -> _OpenDocument:
        key = str(file_path)
        document = self._documents.get(key)
        if document is None:
            document = self._service.open_document(file_path, self._stack)
            self._documents[key] = document
        return document


class PipelineService:
    """Coordinate loading, classification, OCR, layout, and post-processing."""

    def __init__(
        self,
        *,
        loader_factory: LoaderFactory = DocumentLoader,
        classifier: PDFClassifier | None = None,
        preprocessor: ImagePreprocessor = preprocess_for_ocr,
        layout_analyzer: LayoutAnalyzer | None = None,
        postprocessor: Postprocessor | None = None,
        weights_manager: ModelWeightsManager | None = None,
    ) -> None:
        self._loader_factory = loader_factory
        self._classifier = classifier or PDFClassifier()
        self._preprocessor = preprocessor
        self._layout_analyzer = layout_analyzer or LayoutAnalyzer()
        self._postprocessor = postprocessor or Postprocessor()
        self._weights_manager = weights_manager

    @property
    def postprocessor(self) -> Postprocessor:
        return self._postprocessor

    @property
    def weights_manager(self) -> ModelWeightsManager | None:
        return self._weights_manager

    def set_weights_manager(self, weights_manager: ModelWeightsManager) -> None:
        self._weights_manager = weights_manager

    def open_page_session(
        self,
        *,
        engine_id: str = "vietocr",
        fallback_engine_ids: Sequence[str] = (),
        device: str = "cpu",
        dpi: int = 300,
        engine_config: Mapping[str, object] | None = None,
        page_options: PageOptions | None = None,
    ) -> PageSession:
        """Open a session that recognises pages individually for batch work."""
        self._validate_options(engine_id, fallback_engine_ids, dpi)
        return PageSession(
            self,
            engine_ids=(engine_id, *fallback_engine_ids),
            device=device,
            dpi=dpi,
            engine_config=engine_config,
            page_options=page_options,
        )

    def open_document(self, file_path: str | Path, stack: ExitStack) -> _OpenDocument:
        """Open a document once per batch and classify its pages up front."""
        loader = stack.enter_context(self._loader_factory(file_path))
        if not loader.is_pdf:
            return _OpenDocument(loader, None, ())
        pdf = stack.enter_context(pymupdf.open(str(loader.file_path)))
        return _OpenDocument(
            loader, pdf, tuple(self._classifier.classify_document(pdf))
        )

    def recognise_page(
        self,
        document: _OpenDocument,
        page_number: int,
        engine_ids: tuple[str, ...],
        device: str,
        dpi: int,
        config: Mapping[str, object] | None,
        stack: ExitStack,
        engines: dict[str, BaseOCREngine],
        options: PageOptions | None = None,
    ) -> OCRPage:
        """Recognise one page, taking the text layer when the page already has one."""
        force_ocr = bool(options and options.force_ocr)
        if document.pdf is None or force_ocr:
            loaded = document.loader.load_page(page_number, dpi)
            recognized = self._ocr_page(
                loaded, engine_ids, device, config, stack, engines, options
            )
            return recognized.with_updates(page_type=PageType.SCANNED)
        page_type = document.page_types[page_number - 1]
        index = page_number - 1
        if page_type == PageType.TEXT_BASED:
            native = self._classifier.extract_page(
                document.pdf[index], page_number, dpi
            )
            return self._analyze_layout(native, options or PageOptions())
        loaded = document.loader.load_page(page_number, dpi)
        recognized = self._ocr_page(
            loaded, engine_ids, device, config, stack, engines, options
        )
        if page_type == PageType.HYBRID:
            direct = self._classifier.extract_page(
                document.pdf[index], page_number, dpi
            )
            return self._merge_hybrid(direct, recognized, options)
        return recognized.with_updates(page_type=PageType.SCANNED)

    def process(
        self,
        file_path: str | Path,
        *,
        engine_id: str = "vietocr",
        fallback_engine_ids: Sequence[str] = (),
        device: str = "cpu",
        dpi: int = 300,
        engine_config: Mapping[str, object] | None = None,
    ) -> OCRDocument:
        """Process one PDF/image and hide unexpected implementation failures."""
        self._validate_options(engine_id, fallback_engine_ids, dpi)
        try:
            document = self._run(
                file_path,
                (engine_id, *fallback_engine_ids),
                device,
                dpi,
                engine_config,
            )
            return self._postprocessor.process_document(document)
        except PDFOCRError:
            raise
        except Exception as error:
            raise PDFOCRError("Không thể xử lý tài liệu đầu vào.") from error

    def _run(
        self,
        file_path: str | Path,
        engine_ids: tuple[str, ...],
        device: str,
        dpi: int,
        engine_config: Mapping[str, object] | None,
    ) -> OCRDocument:
        with self._loader_factory(file_path) as loader, ExitStack() as stack:
            engines: dict[str, BaseOCREngine] = {}
            if loader.is_pdf:
                pages = self._process_pdf(
                    loader, engine_ids, device, dpi, engine_config, stack, engines
                )
            else:
                pages = self._process_images(
                    loader, engine_ids, device, dpi, engine_config, stack, engines
                )
            return OCRDocument(
                pages=tuple(pages),
                source_path=str(loader.file_path),
                title=loader.file_path.stem,
            )

    def _process_pdf(
        self,
        loader: DocumentLoader,
        engine_ids: tuple[str, ...],
        device: str,
        dpi: int,
        config: Mapping[str, object] | None,
        stack: ExitStack,
        engines: dict[str, BaseOCREngine],
    ) -> list[OCRPage]:
        pages: list[OCRPage] = []
        with pymupdf.open(str(loader.file_path)) as pdf:
            page_types = self._classifier.classify_document(pdf)
            for index, page_type in enumerate(page_types):
                page_number = index + 1
                if page_type == PageType.TEXT_BASED:
                    native = self._classifier.extract_page(pdf[index], page_number, dpi)
                    pages.append(self._analyze_layout(native, PageOptions()))
                    continue
                loaded = loader.load_page(page_number, dpi)
                recognized = self._ocr_page(
                    loaded, engine_ids, device, config, stack, engines
                )
                if page_type == PageType.HYBRID:
                    direct = self._classifier.extract_page(pdf[index], page_number, dpi)
                    pages.append(self._merge_hybrid(direct, recognized))
                else:
                    pages.append(recognized.with_updates(page_type=PageType.SCANNED))
        return pages

    def _process_images(
        self,
        loader: DocumentLoader,
        engine_ids: tuple[str, ...],
        device: str,
        dpi: int,
        config: Mapping[str, object] | None,
        stack: ExitStack,
        engines: dict[str, BaseOCREngine],
    ) -> list[OCRPage]:
        return [
            self._ocr_page(
                loader.load_page(number, dpi),
                engine_ids,
                device,
                config,
                stack,
                engines,
            )
            for number in range(1, loader.page_count + 1)
        ]

    def _ocr_page(
        self,
        loaded: LoadedPage,
        engine_ids: tuple[str, ...],
        device: str,
        config: Mapping[str, object] | None,
        stack: ExitStack,
        engines: dict[str, BaseOCREngine],
        options: PageOptions | None = None,
    ) -> OCRPage:
        options = options or PageOptions()
        image = self._preprocess(loaded.image, options.preprocessing)
        last_error: PDFOCRError | None = None
        for engine_id in engine_ids:
            try:
                engine = engines.get(engine_id)
                if engine is None:
                    engine = stack.enter_context(
                        engine_session(
                            engine_id,
                            device=device,
                            weights_manager=self._weights_manager,
                            config=config,
                        )
                    )
                    engines[engine_id] = engine
                page = engine.recognize(image, page_number=loaded.page_number)
                if not options.detect_tables:
                    page = page.with_updates(tables=())
                return self._analyze_layout(page, options)
            except OCREngineError as error:
                last_error = error
        raise OCREngineError(
            "Không OCR engine nào xử lý được trang này."
        ) from last_error

    def _preprocess(
        self, image: np.ndarray, stages: Mapping[str, bool] | None
    ) -> np.ndarray:
        # A custom preprocessor knows nothing about stages; only the built-in does.
        if stages is not None and self._preprocessor is preprocess_for_ocr:
            return preprocess_for_ocr(image, stages)
        return self._preprocessor(image)

    def _analyze_layout(self, page: OCRPage, options: PageOptions) -> OCRPage:
        return self._layout_analyzer.analyze(
            page,
            options.merge_paragraphs,
            reading_order=options.reading_order,
        )

    def _merge_hybrid(
        self,
        direct: OCRPage,
        recognized: OCRPage,
        options: PageOptions | None = None,
    ) -> OCRPage:
        unique_ocr = tuple(
            block
            for block in recognized.blocks
            if not any(self._center_inside(block, native) for native in direct.blocks)
        )
        merged = direct.with_updates(
            blocks=direct.blocks + unique_ocr,
            tables=direct.tables + recognized.tables,
            page_type=PageType.HYBRID,
        )
        return self._analyze_layout(merged, options or PageOptions())

    @staticmethod
    def _center_inside(candidate: OCRBlock, existing: OCRBlock) -> bool:
        center_x = (candidate.bbox.x1 + candidate.bbox.x2) / 2
        center_y = (candidate.bbox.y1 + candidate.bbox.y2) / 2
        return (
            existing.bbox.x1 <= center_x <= existing.bbox.x2
            and existing.bbox.y1 <= center_y <= existing.bbox.y2
        )

    @staticmethod
    def _validate_options(
        engine_id: str, fallback_engine_ids: Sequence[str], dpi: int
    ) -> None:
        all_ids = (engine_id, *fallback_engine_ids)
        if any(not isinstance(value, str) or not value.strip() for value in all_ids):
            raise ValueError("Mã OCR engine không được để trống.")
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("Danh sách OCR engine không được trùng lặp.")
        if type(dpi) is not int or dpi < 1:
            raise ValueError("DPI phải là số nguyên dương.")

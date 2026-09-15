"""End-to-end document pipeline with native-text branching and OCR fallback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path

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
from src.engines.engine_registry import engine_session
from src.services.weights_manager import ModelWeightsManager

LoaderFactory = Callable[[str | Path], DocumentLoader]
ImagePreprocessor = Callable[[np.ndarray], np.ndarray]


def preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
    """Run the Phase 2 image cleanup stages in their safe order."""
    orientation = detect_orientation(image)
    oriented = rotate_orientation(image, orientation)
    deskewed, _ = deskew_image(oriented)
    cropped = remove_borders(deskewed)
    return enhance_document_image(cropped)


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
                    pages.append(
                        self._classifier.extract_page(pdf[index], page_number, dpi)
                    )
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
    ) -> OCRPage:
        image = self._preprocessor(loaded.image)
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
                return self._layout_analyzer.analyze(page)
            except OCREngineError as error:
                last_error = error
        raise OCREngineError(
            "Không OCR engine nào xử lý được trang này."
        ) from last_error

    def _merge_hybrid(self, direct: OCRPage, recognized: OCRPage) -> OCRPage:
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
        return self._layout_analyzer.analyze(merged)

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

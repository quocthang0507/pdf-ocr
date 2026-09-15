"""Integration tests for the end-to-end OCR pipeline orchestration."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from src.constants import PageType
from src.core.document_loader import DocumentLoader
from src.core.exceptions import OCREngineError, PDFOCRError
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import EngineRegistry
from src.services.pipeline_service import PipelineService
from src.services.weights_manager import ModelWeightsManager


class SuccessfulPipelineEngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "device": ConfigField("cpu", lambda value: value in {"cpu", "cuda"})
    }
    recognize_count = 0

    def _load_model(self) -> None:
        return

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        type(self).recognize_count += 1
        height, width = image.shape[:2]  # type: ignore[attr-defined]
        left_box = BoundingBox(10, 30, width / 2 - 10, 60)
        right_box = BoundingBox(width / 2 + 10, 10, width - 10, 40)
        return OCRPage(
            page_number=page_number,
            width=width,
            height=height,
            blocks=(_block("right", right_box), _block("h0c", left_box)),
        )

    def _unload_model(self) -> None:
        return


class FailingPipelineEngine(SuccessfulPipelineEngine):
    def _recognize(self, image: object, page_number: int) -> OCRPage:
        raise OCREngineError("engine unavailable")


def _block(text: str, bbox: BoundingBox) -> OCRBlock:
    word = OCRWord(text, bbox, confidence=0.75)
    return OCRBlock((OCRLine((word,), bbox),), bbox)


@pytest.fixture
def mixed_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "mixed.pdf"
    document = pymupdf.open()
    text_page = document.new_page(width=300, height=400)
    text_page.insert_text(
        (30, 60), "Native vector text is extracted directly.", fontsize=12
    )
    scan_page = document.new_page(width=300, height=400)
    image = Image.fromarray(np.full((200, 150, 3), 225, dtype=np.uint8))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    scan_page.insert_image(pymupdf.Rect(0, 0, 300, 400), stream=stream.getvalue())
    document.save(path)
    document.close()
    return path


@pytest.fixture(autouse=True)
def preserve_engine_registry() -> None:
    snapshot = EngineRegistry.snapshot()
    SuccessfulPipelineEngine.recognize_count = 0
    yield
    EngineRegistry.restore(snapshot)


def _register_engines() -> None:
    EngineRegistry.unregister("pipeline_ok", missing_ok=True)
    EngineRegistry.unregister("pipeline_fail", missing_ok=True)
    EngineRegistry.register("pipeline_ok", "Pipeline OK", "Test engine")(
        SuccessfulPipelineEngine
    )
    EngineRegistry.register("pipeline_fail", "Pipeline fail", "Test engine")(
        FailingPipelineEngine
    )


@pytest.mark.integration
def test_processes_mixed_pdf_and_skips_ocr_for_native_text(
    mixed_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _register_engines()
    loaded_pages: list[int] = []
    preprocessed_pages: list[int] = []
    original_load_page = DocumentLoader.load_page

    def track_load(loader: DocumentLoader, page_number: int, dpi: int = 300):
        loaded_pages.append(page_number)
        return original_load_page(loader, page_number, dpi)

    def preprocess(image: np.ndarray) -> np.ndarray:
        preprocessed_pages.append(1)
        return image

    monkeypatch.setattr(DocumentLoader, "load_page", track_load)
    service = PipelineService(
        weights_manager=ModelWeightsManager(tmp_path / "weights"),
        preprocessor=preprocess,
    )

    document = service.process(mixed_pdf, engine_id="pipeline_ok", dpi=72)

    assert len(document.pages) == 2
    assert document.pages[0].page_type == PageType.TEXT_BASED
    assert "Native vector text" in document.pages[0].blocks[0].text
    assert document.pages[1].page_type == PageType.SCANNED
    assert [block.text for block in document.pages[1].blocks] == ["hoc", "right"]
    assert document.pages[1].blocks[0].lines[0].words[0].is_low_confidence
    assert loaded_pages == [2]
    assert preprocessed_pages == [1]
    assert SuccessfulPipelineEngine.recognize_count == 1


@pytest.mark.integration
def test_falls_back_to_next_engine_when_primary_recognition_fails(
    mixed_pdf: Path, tmp_path: Path
) -> None:
    _register_engines()
    service = PipelineService(
        weights_manager=ModelWeightsManager(tmp_path / "weights"),
        preprocessor=lambda image: image,
    )

    document = service.process(
        mixed_pdf,
        engine_id="pipeline_fail",
        fallback_engine_ids=("pipeline_ok",),
        dpi=72,
    )

    assert document.pages[1].blocks[0].text == "hoc"
    assert SuccessfulPipelineEngine.recognize_count == 1


@pytest.mark.integration
def test_wraps_unexpected_failures_without_leaking_internal_details() -> None:
    def broken_loader(file_path: str | Path) -> DocumentLoader:
        raise RuntimeError("secret filesystem detail")

    service = PipelineService(loader_factory=broken_loader)

    with pytest.raises(PDFOCRError) as caught:
        service.process("input.pdf", engine_id="pipeline_ok")

    assert "secret filesystem detail" not in str(caught.value)
    assert isinstance(caught.value.__cause__, RuntimeError)

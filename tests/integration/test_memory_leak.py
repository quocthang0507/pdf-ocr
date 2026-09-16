"""A long run must not accumulate memory, engines, or accelerator buffers."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest

from src.constants import PageType
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.engines import engine_registry
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import EngineRegistry
from src.services.pipeline_service import PipelineService

pytestmark = pytest.mark.integration

PAGE_COUNT = 100
ENGINE_ID = "memory-probe"


class _Ledger:
    """Counts what a model allocates, so a leak shows up as a non-zero balance."""

    def __init__(self) -> None:
        self.loads = 0
        self.unloads = 0
        self.buffers: list[np.ndarray] = []
        self.released = 0

    @property
    def outstanding_buffers(self) -> int:
        return len(self.buffers)


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> _Ledger:
    book = _Ledger()

    class ProbeEngine(BaseOCREngine):
        """Holds a page-sized buffer while recognising, like a real model would."""

        CONFIG_SCHEMA = {
            "device": ConfigField("cpu", lambda value: isinstance(value, str)),
        }

        def _load_model(self) -> None:
            book.loads += 1

        def _unload_model(self) -> None:
            book.unloads += 1

        def _recognize(self, image: object, page_number: int) -> OCRPage:
            assert isinstance(image, np.ndarray)
            book.buffers.append(np.zeros_like(image))
            box = BoundingBox(0, 0, 80, 30)
            word = OCRWord(f"trang {page_number}", box, 0.98)
            page = OCRPage(
                page_number=page_number,
                width=float(image.shape[1]),
                height=float(image.shape[0]),
                blocks=(OCRBlock(lines=(OCRLine(words=(word,), bbox=box),), bbox=box),),
            )
            book.buffers.pop()
            return page

    snapshot = EngineRegistry.snapshot()
    EngineRegistry.register(ENGINE_ID, "Probe", "Kiểm tra bộ nhớ")(ProbeEngine)

    def counted_release(device: str) -> None:
        book.released += 1
        gc.collect()

    monkeypatch.setattr(engine_registry, "release_accelerator_memory", counted_release)
    monkeypatch.setattr(
        "src.workers.ocr_worker.release_accelerator_memory", counted_release
    )
    monkeypatch.setattr(
        "src.services.pipeline_service.release_accelerator_memory", counted_release
    )
    yield book
    EngineRegistry.restore(snapshot)


@pytest.fixture
def document(tmp_path: Path) -> Path:
    """A scanned-style PDF with many pages, rendered without a text layer."""
    import pymupdf

    path = tmp_path / "nhieu-trang.pdf"
    with pymupdf.open() as pdf:
        for _ in range(PAGE_COUNT):
            pdf.new_page(width=200, height=280)
        pdf.save(path)
    return path


def _session(document: Path, ledger: _Ledger):
    service = PipelineService()
    return service.open_page_session(engine_id=ENGINE_ID, device="cpu", dpi=72)


def test_a_hundred_pages_load_the_model_only_once(
    document: Path, ledger: _Ledger
) -> None:
    with _session(document, ledger) as session:
        for number in range(1, PAGE_COUNT + 1):
            session.recognise(document, number)

    assert ledger.loads == 1


def test_every_page_releases_its_accelerator_memory(
    document: Path, ledger: _Ledger
) -> None:
    with _session(document, ledger) as session:
        for number in range(1, 11):
            session.recognise(document, number)

    assert ledger.released >= 10


def test_the_model_is_unloaded_when_the_session_closes(
    document: Path, ledger: _Ledger
) -> None:
    with _session(document, ledger) as session:
        session.recognise(document, 1)

    assert ledger.unloads == 1
    assert ledger.outstanding_buffers == 0


def test_a_failure_still_closes_the_session(document: Path, ledger: _Ledger) -> None:
    with pytest.raises(RuntimeError):
        with _session(document, ledger) as session:
            session.recognise(document, 1)
            raise RuntimeError("lỗi giữa chừng")

    assert ledger.unloads == 1


def test_a_long_run_does_not_accumulate_python_objects(
    document: Path, ledger: _Ledger
) -> None:
    with _session(document, ledger) as session:
        for number in range(1, 21):
            session.recognise(document, number)
        gc.collect()
        settled = len(gc.get_objects())
        for number in range(21, PAGE_COUNT + 1):
            session.recognise(document, number)
        gc.collect()
        grown = len(gc.get_objects())

    assert grown < settled * 1.15


def test_recognised_pages_are_not_retained_by_the_session(
    document: Path, ledger: _Ledger
) -> None:
    import weakref

    with _session(document, ledger) as session:
        page = session.recognise(document, 1)
        reference = weakref.ref(page)
        del page
        gc.collect()

        assert reference() is None


def test_the_session_reports_how_many_pages_a_document_has(
    document: Path, ledger: _Ledger
) -> None:
    with _session(document, ledger) as session:
        assert session.page_count(document) == PAGE_COUNT


def test_pages_come_back_post_processed_and_classified(
    document: Path, ledger: _Ledger
) -> None:
    with _session(document, ledger) as session:
        page = session.recognise(document, 3)

    assert page.page_number == 3
    assert page.page_type == PageType.SCANNED
    assert page.blocks[0].text == "trang 3"


def test_queued_pages_release_memory_after_every_page(
    qapp, document: Path, ledger: _Ledger
) -> None:
    """The batch path must reclaim memory per page, not only per document."""
    from src.workers.batch_manager import BatchManager

    with _session(document, ledger) as session:
        manager = BatchManager(
            lambda task: session.recognise(task.document_path, task.page_number),
            page_counter=session.page_count,
            max_workers=1,
        )
        before = ledger.released
        manager.start([document])
        assert manager.wait_for_completion(120_000) is True

    assert manager.progress_snapshot().completed == PAGE_COUNT
    assert ledger.released - before >= PAGE_COUNT

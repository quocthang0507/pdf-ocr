"""Queue, pace, and control a batch of pages without ever blocking the GUI."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QObject,
    QThreadPool,
    Signal,
    SignalInstance,
)

from src.core.document_loader import DocumentLoader
from src.core.exceptions import PDFOCRError
from src.core.models import OCRPage
from src.utils.logger import logger
from src.workers.ocr_worker import OCRWorker, PageProcessor
from src.workers.signals import BatchProgress, PageTask, WorkerSignals

PageCounter = Callable[[Path], int]
Clock = Callable[[], float]
DEFAULT_WORKERS = 1
_POLL_SECONDS = 0.05


def count_document_pages(path: Path) -> int:
    """Open a document only long enough to learn how many pages it holds."""
    with DocumentLoader(path) as loader:
        return int(loader.page_count)


class BatchControl:
    """Thread-safe pause and cancel shared by every worker in one batch.

    Pausing clears an event the workers wait on; cancelling sets it again so
    nobody is left blocked, and the cancelled flag turns them away instead.
    """

    def __init__(self) -> None:
        self._running = threading.Event()
        self._running.set()
        self._cancelled = threading.Event()

    @property
    def is_paused(self) -> bool:
        return not self._running.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._running.set()

    def wait_while_paused(self, timeout: float | None = None) -> bool:
        """Block until the batch runs again; False means it was cancelled."""
        if self.is_cancelled:
            return False
        self._running.wait(timeout)
        return not self.is_cancelled


class BatchManager(QObject):
    """Stateful batch queue; every page runs on the pool, never on the caller.

    The manager owns the counters so progress and estimates stay consistent
    even though results arrive from several worker threads.
    """

    progress = Signal(BatchProgress)
    page_ready = Signal(PageTask, OCRPage)
    page_failed = Signal(PageTask, str)
    finished = Signal(BatchProgress)
    cancelled = Signal(BatchProgress)

    def __init__(
        self,
        processor: PageProcessor,
        *,
        page_counter: PageCounter = count_document_pages,
        max_workers: int = DEFAULT_WORKERS,
        device: str = "cpu",
        clock: Clock = time.monotonic,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError("Số luồng xử lý phải là số nguyên dương.")
        self._processor = processor
        self._page_counter = page_counter
        self._device = device
        self._clock = clock
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_workers)
        self._control = BatchControl()
        self._lock = threading.Lock()
        self._signals = WorkerSignals(self)
        self._signals.page_finished.connect(self._on_page_finished)
        self._signals.page_failed.connect(self._on_page_failed)
        self._completed = 0
        self._failed = 0
        self._total = 0
        self._planned: dict[str, int] = {}
        self._started_at = self._clock()
        self._running = False
        self._closed = False

    # -- lifecycle --------------------------------------------------------

    def start(self, paths: Sequence[str | Path]) -> int:
        """Queue every page of every document and return how many were queued."""
        if self._running:
            raise RuntimeError("Một lượt xử lý hàng loạt đang chạy.")
        self._planned = {}
        tasks = self._plan(paths)
        # A new batch never inherits the previous one's pause or cancel.
        self._control = BatchControl()
        with self._lock:
            self._completed = 0
            self._failed = 0
            self._total = len(tasks)
            self._started_at = self._clock()
            self._running = bool(tasks)
            self._closed = False
        if not tasks:
            self.finished.emit(self.progress_snapshot())
            return 0
        for task in tasks:
            self._pool.start(
                OCRWorker(
                    task,
                    self._processor,
                    self._signals,
                    device=self._device,
                    control=self._control,
                )
            )
        logger.info("Đã xếp hàng {} trang để nhận diện.", len(tasks))
        return len(tasks)

    def _plan(self, paths: Sequence[str | Path]) -> list[PageTask]:
        """Expand documents into pages, reporting the ones that cannot be read."""
        tasks: list[PageTask] = []
        for entry in paths:
            path = Path(entry)
            try:
                pages = self._page_counter(path)
            except (PDFOCRError, OSError, ValueError) as error:
                logger.warning("Bỏ qua '{}': {}", path.name, error)
                self.page_failed.emit(PageTask(str(path), 1), str(error))
                continue
            self._planned[str(path)] = pages
            tasks.extend(PageTask(str(path), number) for number in range(1, pages + 1))
        return tasks

    def pages_per_document(self) -> dict[str, int]:
        """How many pages each document contributed to the current batch."""
        return dict(self._planned)

    def wait_for_completion(self, timeout_ms: int = 60_000) -> bool:
        """Wait for the pool to drain and every queued result to be delivered.

        Results reach this object through Qt's event queue, so the queue is
        pumped while waiting; the counters are therefore final on return.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            drained = bool(self._pool.waitForDone(int(_POLL_SECONDS * 1000)))
            self._deliver_pending()
            if drained:
                return True
            if time.monotonic() >= deadline:
                return False

    @staticmethod
    def _deliver_pending() -> None:
        application = QCoreApplication.instance()
        if application is not None:
            application.processEvents()

    # -- control ----------------------------------------------------------

    @property
    def is_paused(self) -> bool:
        return self._control.is_paused

    @property
    def is_cancelled(self) -> bool:
        return self._control.is_cancelled

    @property
    def is_running(self) -> bool:
        return self._running

    def pause(self) -> None:
        """Stop handing out new pages; the page in flight finishes normally."""
        self._control.pause()
        logger.info("Đã tạm dừng xử lý hàng loạt.")

    def resume(self) -> None:
        self._control.resume()
        logger.info("Đã tiếp tục xử lý hàng loạt.")

    def cancel(self) -> None:
        """Drop every page that has not started; nothing is left half written."""
        self._control.cancel()
        logger.info("Đã hủy xử lý hàng loạt.")
        self._close(self.cancelled)

    # -- progress ---------------------------------------------------------

    def progress_snapshot(self) -> BatchProgress:
        with self._lock:
            return BatchProgress(
                self._completed,
                self._failed,
                self._total,
                self._clock() - self._started_at,
            )

    def _on_page_finished(self, task: PageTask, page: OCRPage) -> None:
        with self._lock:
            self._completed += 1
        self.page_ready.emit(task, page)
        self._publish()

    def _on_page_failed(self, task: PageTask, message: str) -> None:
        with self._lock:
            self._failed += 1
        self.page_failed.emit(task, message)
        self._publish()

    def _publish(self) -> None:
        snapshot = self.progress_snapshot()
        self.progress.emit(snapshot)
        if snapshot.is_finished:
            self._close(self.finished)

    def _close(self, outcome: SignalInstance) -> None:
        """Announce the end of a batch exactly once, however it ended."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._running = False
        outcome.emit(self.progress_snapshot())

"""Recognise one page off the GUI thread and hand its memory straight back."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from PySide6.QtCore import QRunnable

from src.core.exceptions import PDFOCRError
from src.core.models import OCRPage
from src.engines.engine_registry import release_accelerator_memory
from src.utils.logger import logger
from src.workers.signals import PageTask, WorkerSignals

PageProcessor = Callable[[PageTask], OCRPage]


class PauseControl(Protocol):
    """The control surface a worker needs: hold while paused, stop when cancelled."""

    def wait_while_paused(self, timeout: float | None = None) -> bool:
        """Return True when the page may run, False once the batch is cancelled."""


class OCRWorker(QRunnable):
    """One queued page. Failures are reported, never raised into the thread pool.

    An exception escaping QRunnable.run terminates the process, so every path
    here ends in a signal. Accelerator memory is released as soon as the page
    is done, which keeps a hundred-page run flat instead of climbing.
    """

    def __init__(
        self,
        task: PageTask,
        processor: PageProcessor,
        signals: WorkerSignals,
        *,
        device: str = "cpu",
        control: PauseControl | None = None,
    ) -> None:
        super().__init__()
        self.task = task
        self._processor = processor
        self._signals = signals
        self._device = device
        self._control = control
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._control is not None and not self._control.wait_while_paused():
            return
        try:
            page = self._processor(self.task)
            self._signals.page_finished.emit(self.task, page)
        except PDFOCRError as error:
            logger.warning("Trang {} thất bại: {}", self.task.page_number, error)
            self._signals.page_failed.emit(self.task, str(error))
        except Exception:
            logger.exception("Trang {} gặp lỗi không mong đợi.", self.task.page_number)
            self._signals.page_failed.emit(self.task, PDFOCRError.default_message)
        finally:
            self.release_memory()

    def release_memory(self) -> None:
        """Free the accelerator cache and collect garbage before the next page."""
        release_accelerator_memory(self._device)

"""Immutable units of background work and the signals that report on them."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from src.core.models import OCRPage


@dataclass(frozen=True)
class PageTask:
    """One page of one document, the smallest unit the queue schedules."""

    document_path: str
    page_number: int

    def __post_init__(self) -> None:
        if not isinstance(self.document_path, str) or not self.document_path.strip():
            raise ValueError("Đường dẫn tài liệu không được để trống.")
        if type(self.page_number) is not int or self.page_number < 1:
            raise ValueError("Số trang phải là số nguyên lớn hơn không.")


@dataclass(frozen=True)
class BatchProgress:
    """A snapshot of one batch, with the numbers the interface needs to show."""

    completed: int
    failed: int
    total: int
    elapsed_seconds: float

    @property
    def finished_pages(self) -> int:
        return self.completed + self.failed

    @property
    def percent(self) -> int:
        """An empty batch counts as done, so the bar never sits at zero."""
        if self.total <= 0:
            return 100
        return min(100, int(self.finished_pages * 100 / self.total))

    @property
    def is_finished(self) -> bool:
        return self.finished_pages >= self.total

    @property
    def seconds_remaining(self) -> float:
        """Estimate from the pace so far; zero while there is nothing to go on."""
        remaining = self.total - self.finished_pages
        if remaining <= 0 or self.finished_pages <= 0 or self.elapsed_seconds <= 0:
            return 0.0
        return self.elapsed_seconds / self.finished_pages * remaining


class WorkerSignals(QObject):
    """Qt cannot emit from a QRunnable, so workers borrow this object's signals."""

    page_finished = Signal(PageTask, OCRPage)
    page_failed = Signal(PageTask, str)

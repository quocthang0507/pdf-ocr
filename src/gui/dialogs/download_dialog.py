"""Progress dialog for fetching model weights, with speed, ETA and safe cancel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.core.exceptions import PDFOCRError, WeightsError
from src.services.weights_manager import (
    DOWNLOAD_BACKOFF_SECONDS,
    DownloadProgress,
    Opener,
    download_weights,
)
from src.utils.logger import logger

_KB = 1024.0
_MB = _KB * 1024.0
_WAIT_MILLISECONDS = 15_000


def format_rate(bytes_per_second: float) -> str:
    """Show the transfer rate the way a download manager would."""
    if bytes_per_second >= _MB:
        return f"{bytes_per_second / _MB:.1f} MB/s"
    if bytes_per_second >= _KB:
        return f"{bytes_per_second / _KB:.1f} KB/s"
    return "0 KB/s"


def format_eta(seconds: float) -> str:
    """Show the remaining time, or a dash while it cannot be estimated."""
    if seconds <= 0:
        return "—"
    whole = int(round(seconds))
    if whole < 60:
        return f"{whole} giây"
    return f"{whole // 60} phút {whole % 60} giây"


class DownloadTask(QThread):
    """Run one weights download off the GUI thread."""

    advanced = Signal(DownloadProgress)
    failed = Signal(str)
    completed = Signal(str)

    def __init__(
        self,
        url: str,
        destination: Path,
        *,
        sha256: str,
        opener: Opener | None,
        backoff: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._destination = destination
        self._sha256 = sha256
        self._opener = opener
        self._backoff = backoff
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            download_weights(
                self._url,
                self._destination,
                sha256=self._sha256,
                opener=self._opener,
                on_progress=self.advanced.emit,
                should_cancel=lambda: self._cancelled,
                backoff=self._backoff,
            )
        except PDFOCRError as error:
            self.failed.emit(str(error))
            return
        except Exception:
            logger.exception("Tải weights gặp lỗi không mong đợi.")
            self.failed.emit(WeightsError.default_message)
            return
        self.completed.emit(str(self._destination))


class DownloadDialog(QDialog):
    """Stateful download view; the transfer itself lives in the weights service."""

    download_finished = Signal(str)
    download_failed = Signal(str)

    def __init__(
        self,
        url: str,
        destination: str | Path,
        *,
        sha256: str,
        model_name: str,
        opener: Opener | None = None,
        backoff: float = DOWNLOAD_BACKOFF_SECONDS,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("download_dialog")
        self.setWindowTitle("Tải mô hình")
        self._task = DownloadTask(
            url,
            Path(destination),
            sha256=sha256,
            opener=opener,
            backoff=backoff,
            parent=self,
        )
        self.title_label = QLabel(f"Đang tải mô hình {model_name}…", self)
        self.title_label.setObjectName("download_title")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("download_progress")
        self.progress_bar.setRange(0, 100)
        self.rate_label = _status_label(self, "download_rate")
        self.eta_label = _status_label(self, "download_eta")
        self._build_layout()
        self._task.advanced.connect(self._show_progress)
        self._task.failed.connect(self._on_failed)
        self._task.completed.connect(self._on_completed)

    def _build_layout(self) -> None:
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=self)
        buttons.rejected.connect(self.cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.rate_label)
        layout.addWidget(self.eta_label)
        layout.addWidget(buttons)

    # -- transfer ---------------------------------------------------------

    def start(self) -> None:
        """Begin the download; calling this twice does not start a second one."""
        if not self._task.isRunning():
            self._task.start()

    def cancel(self) -> None:
        """Ask the transfer to stop; the partial file is discarded for us."""
        self._task.cancel()

    def wait_for_completion(self) -> None:
        """Block until the worker has stopped, used on close and in tests."""
        self._task.wait(_WAIT_MILLISECONDS)

    def _show_progress(self, progress: DownloadProgress) -> None:
        self.progress_bar.setValue(progress.percent)
        self.rate_label.setText(f"Tốc độ: {format_rate(progress.bytes_per_second)}")
        self.eta_label.setText(f"Còn lại: {format_eta(progress.seconds_remaining)}")

    def _on_completed(self, destination: str) -> None:
        self.progress_bar.setValue(100)
        self.download_finished.emit(destination)
        self.accept()

    def _on_failed(self, message: str) -> None:
        self.title_label.setText(message)
        self.download_failed.emit(message)

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        self.cancel()
        self.wait_for_completion()
        super().closeEvent(event)  # type: ignore[arg-type]


def _status_label(parent: QWidget, name: str) -> QLabel:
    label = QLabel("", parent)
    label.setObjectName(name)
    return label

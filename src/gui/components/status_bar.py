"""Status bar showing batch progress, an estimate, and the run controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QWidget,
)

from src.workers.signals import BatchProgress

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
CONTROL_HEIGHT = 24
PAUSE_LABEL = "Tạm dừng"
RESUME_LABEL = "Tiếp tục"


def format_duration(seconds: float) -> str:
    """Read a remaining time the way a person would say it."""
    whole = int(round(seconds))
    if whole <= 0:
        return "—"
    if whole < _SECONDS_PER_MINUTE:
        return f"{whole} giây"
    if whole < _SECONDS_PER_HOUR:
        return f"{whole // 60} phút {whole % 60} giây"
    hours, remainder = divmod(whole, _SECONDS_PER_HOUR)
    return f"{hours} giờ {remainder // 60} phút"


class BatchStatusBar(QStatusBar):
    """Stateful progress strip; it reports intent and never touches the queue."""

    pause_toggled = Signal(bool)
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("batch_status_bar")
        self.setSizeGripEnabled(False)
        self.setContentsMargins(8, 2, 10, 4)
        self.count_label = _label(self, "batch_counts")
        self.eta_label = _label(self, "batch_eta")
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("batch_progress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setMaximumWidth(220)
        self.progress_bar.setFixedHeight(12)
        self.pause_button = _button(self, PAUSE_LABEL, "batch_pause")
        self.cancel_button = _button(self, "Hủy", "batch_cancel")
        self._paused = False
        controls = QWidget(self)
        controls.setObjectName("batch_controls_container")
        row = QHBoxLayout(controls)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(8)
        row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.count_label)
        row.addWidget(self.eta_label)
        row.addWidget(self.progress_bar)
        row.addWidget(self.pause_button)
        row.addWidget(self.cancel_button)
        self.addPermanentWidget(controls)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button.clicked.connect(self._request_cancel)
        self.set_running(False)

    # -- state ------------------------------------------------------------

    def set_running(self, running: bool) -> None:
        """Only show the bar and enable the controls while a batch is live."""
        self.progress_bar.setVisible(running)
        self.pause_button.setEnabled(running)
        self.cancel_button.setEnabled(running)
        if running:
            # A fresh run must not inherit the previous run's figures.
            self.progress_bar.setValue(0)
            self.count_label.setText("")
            self.eta_label.setText("")
        self._paused = False
        self.pause_button.setText(PAUSE_LABEL)

    def clear_summary(self) -> None:
        """Forget the last finished run, e.g. once another document is opened."""
        if self.progress_bar.isHidden():
            self.count_label.setText("")
            self.eta_label.setText("")

    def show_progress(self, progress: BatchProgress) -> None:
        self.progress_bar.setValue(progress.percent)
        self.count_label.setText(
            f"Đã xong {progress.completed}/{progress.total}" f" · Lỗi {progress.failed}"
        )
        self.eta_label.setText(
            f"Còn lại: {format_duration(progress.seconds_remaining)}"
        )

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.setText(RESUME_LABEL if self._paused else PAUSE_LABEL)
        self.pause_toggled.emit(self._paused)

    def _request_cancel(self) -> None:
        """Cancelling is final, so the button stops accepting further clicks."""
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.cancel_requested.emit()


def _label(parent: QWidget, name: str) -> QLabel:
    label = QLabel("", parent)
    label.setObjectName(name)
    return label


def _button(parent: QWidget, text: str, name: str) -> QPushButton:
    """Keep controls compact while allowing HiDPI font metrics to expand cleanly."""
    button = QPushButton(text, parent)
    button.setObjectName(name)
    button.setMinimumHeight(CONTROL_HEIGHT)
    return button

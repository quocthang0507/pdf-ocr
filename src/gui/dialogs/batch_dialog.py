"""Batch window: per-document state, overall progress, and safe controls."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.models import OCRPage
from src.gui.components.status_bar import PAUSE_LABEL, RESUME_LABEL, format_duration
from src.gui.styles.style_manager import (
    status_accent_color,
    status_error_color,
    status_muted_color,
    status_success_color,
)
from src.workers.batch_manager import BatchManager
from src.workers.signals import BatchProgress, PageTask

_CLOSE_TIMEOUT_MS = 10_000


class DocumentState(str, Enum):
    """How far one document has got, shown beside its name."""

    WAITING = "Chờ"
    RUNNING = "Đang chạy"
    DONE = "Xong"
    FAILED = "Lỗi"


class BatchDialog(QDialog):
    """Stateful batch view driven entirely by the manager's signals.

    The dialog never recognises anything itself; it only shows what the queue
    reports and forwards the user's pause, resume and cancel decisions.
    """

    batch_finished = Signal(BatchProgress)
    page_ready = Signal(PageTask, OCRPage)

    def __init__(
        self,
        manager: BatchManager,
        documents: Sequence[str | Path],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("batch_dialog")
        self.setWindowTitle("Quét hàng loạt")
        self.manager = manager
        self._documents = [Path(entry) for entry in documents]
        self._states: dict[str, DocumentState] = {
            str(path): DocumentState.WAITING for path in self._documents
        }
        self._items: dict[str, QListWidgetItem] = {}
        self._expected: dict[str, int] = {}
        self._seen: dict[str, int] = {}
        self.document_list = QListWidget(self)
        self.document_list.setObjectName("batch_documents")
        self.document_list.setAlternatingRowColors(True)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("batch_total_progress")
        self.progress_bar.setRange(0, 100)
        self.summary_label = QLabel("Sẵn sàng.", self)
        self.summary_label.setObjectName("batch_summary")
        self.eta_label = QLabel("", self)
        self.eta_label.setObjectName("batch_dialog_eta")
        self.pause_button = QPushButton(PAUSE_LABEL, self)
        self.pause_button.setObjectName("batch_dialog_pause")
        self.cancel_button = QPushButton("Hủy", self)
        self.cancel_button.setObjectName("batch_dialog_cancel")
        self._paused = False
        self._settled = False
        self._fill_list()
        self._build_layout()
        self._connect()

    # -- layout -----------------------------------------------------------

    def _fill_list(self) -> None:
        for path in self._documents:
            item = QListWidgetItem(f"{path.name} — {DocumentState.WAITING.value}")
            item.setData(0x0100, str(path))
            item.setForeground(status_muted_color())
            self.document_list.addItem(item)
            self._items[str(path)] = item

    def _build_layout(self) -> None:
        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(self.eta_label)
        controls.addStretch(1)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.cancel_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.document_list)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.summary_label)
        layout.addLayout(controls)
        layout.addWidget(buttons)

    def _connect(self) -> None:
        self.manager.progress.connect(self._show_progress)
        self.manager.page_ready.connect(self._on_page_ready)
        self.manager.page_failed.connect(self._on_page_failed)
        self.manager.finished.connect(self._on_finished)
        self.manager.cancelled.connect(self._on_cancelled)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button.clicked.connect(self.cancel)

    # -- running ----------------------------------------------------------

    def start(self) -> int:
        """Queue every document; the pages are recognised in the background."""
        self.summary_label.setText("Đang xử lý…")
        self._settled = False
        self._seen = {}
        queued = self.manager.start(self._documents)
        self._expected = self.manager.pages_per_document()
        self.progress_bar.setValue(0 if queued else 100)
        return queued

    def cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.manager.cancel()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self.pause_button.setText(RESUME_LABEL if self._paused else PAUSE_LABEL)
        if self._paused:
            self.manager.pause()
        else:
            self.manager.resume()

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        """Never leave workers running behind a closed window."""
        if self.manager.is_running:
            self.manager.cancel()
            self.manager.wait_for_completion(_CLOSE_TIMEOUT_MS)
        super().closeEvent(event)  # type: ignore[arg-type]

    # -- reporting --------------------------------------------------------

    def state_of(self, document: str | Path) -> DocumentState:
        return self._states.get(str(document), DocumentState.WAITING)

    def _show_progress(self, progress: BatchProgress) -> None:
        """A page still in flight when the batch ended must not rewrite its verdict."""
        self.progress_bar.setValue(progress.percent)
        if self._settled:
            return
        self.summary_label.setText(
            f"Đã xong {progress.completed}/{progress.total} trang"
            f" · Lỗi {progress.failed}"
        )
        self.eta_label.setText(
            f"Còn lại: {format_duration(progress.seconds_remaining)}"
        )

    def _on_page_ready(self, task: PageTask, page: OCRPage) -> None:
        self._advance(task.document_path)
        self.page_ready.emit(task, page)

    def _on_page_failed(self, task: PageTask, message: str) -> None:
        self._seen[task.document_path] = self._seen.get(task.document_path, 0) + 1
        self._mark(task.document_path, DocumentState.FAILED)
        if not self._settled:
            self.summary_label.setText(message)

    def _advance(self, document: str) -> None:
        """A document reads as running until its last page lands without failing."""
        seen = self._seen.get(document, 0) + 1
        self._seen[document] = seen
        if self._states.get(document) is DocumentState.FAILED:
            return
        expected = self._expected.get(document, seen)
        self._mark(
            document, DocumentState.DONE if seen >= expected else DocumentState.RUNNING
        )

    def _mark(self, document: str, state: DocumentState) -> None:
        self._states[document] = state
        item = self._items.get(document)
        if item is not None:
            item.setText(f"{Path(document).name} — {state.value}")
            if state is DocumentState.DONE:
                item.setForeground(status_success_color())
            elif state is DocumentState.FAILED:
                item.setForeground(status_error_color())
            elif state is DocumentState.RUNNING:
                item.setForeground(status_accent_color())
            else:
                item.setForeground(status_muted_color())

    def _on_finished(self, progress: BatchProgress) -> None:
        self._settle()
        self.summary_label.setText(
            f"Hoàn tất {progress.completed}/{progress.total} trang"
            f" · Lỗi {progress.failed}"
        )
        self.batch_finished.emit(progress)

    def _on_cancelled(self, progress: BatchProgress) -> None:
        self._settle()
        self.summary_label.setText(
            f"Đã hủy sau {progress.completed}/{progress.total} trang."
        )
        self.batch_finished.emit(progress)

    def _settle(self) -> None:
        self._settled = True
        self.eta_label.setText("Còn lại: —")
        self.pause_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        for document, state in self._states.items():
            if state is DocumentState.RUNNING:
                self._mark(document, DocumentState.DONE)

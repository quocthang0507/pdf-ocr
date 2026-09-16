"""Application settings: weights storage, execution device, and folders."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config import ConfigManager, Preferences
from src.core.exceptions import PDFOCRError
from src.gui.components.settings_dock import populate_device_combo
from src.gui.i18n import LANGUAGE_NAMES, TranslationManager
from src.gui.styles.style_manager import THEMES, StyleManager
from src.services.device_service import detect_devices
from src.services.weights_manager import ModelWeightsManager, migrate_weights
from src.utils.file_utils import normalize_directory
from src.utils.logger import logger

_BYTES_PER_GB = 1024**3

THEME_LABELS = {
    "system": "Theo hệ thống",
    "light": "Sáng",
    "dark": "Tối",
}


class WeightsMigrationTask(QThread):
    """Copy weights off the GUI thread so the window keeps responding."""

    progress = Signal(int)
    failed = Signal(str)
    completed = Signal(str)

    def __init__(self, source: Path, destination: Path, parent: QWidget) -> None:
        super().__init__(parent)
        self._source = source
        self._destination = destination
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            migrate_weights(
                self._source,
                self._destination,
                on_progress=self.progress.emit,
                should_cancel=lambda: self._cancelled,
            )
        except PDFOCRError as error:
            self.failed.emit(str(error))
            return
        except Exception:
            logger.exception("Di chuyển weights gặp lỗi không mong đợi.")
            self.failed.emit(PDFOCRError.default_message)
            return
        self.completed.emit(str(self._destination))


class SettingsDialog(QDialog):
    """Stateful settings editor; preferences are only written when accepted."""

    weights_directory_changed = Signal(str)
    theme_changed = Signal(str)
    language_changed = Signal(str)
    migration_finished = Signal(str)
    migration_failed = Signal(str)

    def __init__(
        self, *, config: ConfigManager | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_dialog")
        self.setWindowTitle("Cài đặt")
        self._config = config or ConfigManager()
        self._preferences = self._config.load()
        self._task: WeightsMigrationTask | None = None
        self.weights_edit = _line_edit(self, "weights_edit")
        self.input_edit = _line_edit(self, "input_edit")
        self.output_edit = _line_edit(self, "output_edit")
        self.free_space_label = QLabel(self)
        self.free_space_label.setObjectName("free_space_label")
        self.device_combo = QComboBox(self)
        self.device_combo.setObjectName("device_combo")
        self.theme_combo = QComboBox(self)
        self.theme_combo.setObjectName("theme_combo")
        self.language_combo = QComboBox(self)
        self.language_combo.setObjectName("language_combo")
        self.device_hint = QLabel(self)
        self.device_hint.setObjectName("device_hint")
        self.device_hint.setWordWrap(True)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("migration_progress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        self.migrate_button = QPushButton("Di chuyển weights sang thư mục mới", self)
        self.migrate_button.setObjectName("migrate_button")
        self._build_layout()
        self._load_preferences()
        self.weights_edit.textChanged.connect(self._refresh_free_space)
        self.migrate_button.clicked.connect(self.start_weights_migration)

    # -- layout -----------------------------------------------------------

    def _build_layout(self) -> None:
        storage = QGroupBox("Thư mục mô hình & weights", self)
        storage_layout = QVBoxLayout(storage)
        storage_layout.addLayout(
            _browse_row(self, self.weights_edit, self.browse_weights_dir)
        )
        storage_layout.addWidget(self.free_space_label)
        storage_layout.addWidget(self.migrate_button)
        storage_layout.addWidget(self.progress_bar)

        execution = QGroupBox("Thiết bị thực thi", self)
        execution_layout = QVBoxLayout(execution)
        execution_layout.addWidget(self.device_combo)
        execution_layout.addWidget(self.device_hint)

        appearance = QGroupBox("Giao diện", self)
        appearance_layout = QFormLayout(appearance)
        appearance_layout.addRow("Chủ đề", self.theme_combo)
        appearance_layout.addRow("Ngôn ngữ", self.language_combo)

        folders = QGroupBox("Thư mục mặc định", self)
        folder_form = QFormLayout(folders)
        folder_form.addRow(
            "Đầu vào", _browse_widget(self, self.input_edit, self.browse_input_dir)
        )
        folder_form.addRow(
            "Đầu ra", _browse_widget(self, self.output_edit, self.browse_output_dir)
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(storage)
        layout.addWidget(execution)
        layout.addWidget(appearance)
        layout.addWidget(folders)
        layout.addWidget(buttons)

    def _load_preferences(self) -> None:
        populate_device_combo(self.device_combo)
        index = self.device_combo.findData(self._preferences.device)
        self.device_combo.setCurrentIndex(max(index, 0))
        for theme in THEMES:
            self.theme_combo.addItem(THEME_LABELS[theme], theme)
        self.theme_combo.setCurrentIndex(
            max(self.theme_combo.findData(self._preferences.theme), 0)
        )
        for code, name in LANGUAGE_NAMES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(
            max(self.language_combo.findData(self._preferences.language), 0)
        )
        self.device_hint.setText(_device_hint())
        self.weights_edit.setText(self._preferences.weights_dir or "")
        self.input_edit.setText(self._preferences.input_dir or "")
        self.output_edit.setText(self._preferences.output_dir or "")
        self._refresh_free_space()

    # -- folder pickers ---------------------------------------------------

    def browse_weights_dir(self) -> None:
        self._browse(self.weights_edit, "Chọn thư mục lưu weights")

    def browse_input_dir(self) -> None:
        self._browse(self.input_edit, "Chọn thư mục đầu vào")

    def browse_output_dir(self) -> None:
        self._browse(self.output_edit, "Chọn thư mục đầu ra")

    def _browse(self, target: QLineEdit, title: str) -> None:
        from PySide6.QtWidgets import QFileDialog

        selected = QFileDialog.getExistingDirectory(self, title, target.text())
        if selected:
            target.setText(selected)

    def _refresh_free_space(self) -> None:
        self.free_space_label.setText(_free_space_text(self.weights_edit.text()))

    # -- weights migration ------------------------------------------------

    def start_weights_migration(self) -> None:
        """Move the existing weights into the folder currently in the field."""
        if self._task is not None and self._task.isRunning():
            return
        source = self._preferences.weights_dir or str(ModelWeightsManager().base_path)
        task = WeightsMigrationTask(Path(source), Path(self.weights_edit.text()), self)
        task.progress.connect(self.progress_bar.setValue)
        task.failed.connect(self._on_migration_failed)
        task.completed.connect(self._on_migration_completed)
        self._task = task
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.migrate_button.setEnabled(False)
        task.start()

    def _on_migration_completed(self, destination: str) -> None:
        self.progress_bar.setValue(100)
        self.migrate_button.setEnabled(True)
        self.migration_finished.emit(destination)

    def _on_migration_failed(self, message: str) -> None:
        self.progress_bar.hide()
        self.migrate_button.setEnabled(True)
        QMessageBox.warning(self, "Di chuyển weights", message)
        self.migration_failed.emit(message)

    # -- saving -----------------------------------------------------------

    def accept(self) -> None:
        """Validate every path before anything is written or applied."""
        try:
            preferences = self._collect()
        except (PDFOCRError, ValueError) as error:
            QMessageBox.warning(self, "Cài đặt", _safe_message(error))
            return
        try:
            self._config.save(preferences)
        except PDFOCRError as error:
            QMessageBox.warning(self, "Cài đặt", str(error))
            return
        self._preferences = preferences
        self._apply_theme(preferences.theme)
        self._apply_language(preferences.language)
        if preferences.weights_dir:
            self.weights_directory_changed.emit(preferences.weights_dir)
        super().accept()

    def _apply_theme(self, theme: str) -> None:
        """Repaint immediately so the choice is visible without a restart."""
        try:
            StyleManager().apply(theme)
        except (RuntimeError, ValueError) as error:
            logger.warning("Không đổi được giao diện: {}", error)
            return
        self.theme_changed.emit(theme)

    def _apply_language(self, language: str) -> None:
        """Install the chosen catalogue so the change needs no restart."""
        try:
            TranslationManager().apply(language)
        except (RuntimeError, ValueError) as error:
            logger.warning("Không đổi được ngôn ngữ: {}", error)
            return
        self.language_changed.emit(language)

    def _collect(self) -> Preferences:
        return Preferences(
            weights_dir=_checked_directory(self.weights_edit.text(), create=True),
            input_dir=_checked_directory(self.input_edit.text()),
            output_dir=_checked_directory(self.output_edit.text()),
            device=str(self.device_combo.currentData()),
            theme=str(self.theme_combo.currentData()),
            language=str(self.language_combo.currentData()),
        )

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait()
        super().closeEvent(event)  # type: ignore[arg-type]


def _checked_directory(value: str, *, create: bool = False) -> str | None:
    """Reject traversal before a user supplied folder is stored or applied."""
    if not value.strip():
        return None
    resolved = normalize_directory(value)
    if create:
        ModelWeightsManager(resolved)
    return str(resolved)


def _safe_message(error: Exception) -> str:
    if isinstance(error, PDFOCRError):
        return str(error)
    return "Đường dẫn thư mục không hợp lệ. Vui lòng chọn lại."


def _free_space_text(path: str) -> str:
    probe = Path(path) if path.strip() else Path.home()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        import shutil

        free = shutil.disk_usage(probe).free / _BYTES_PER_GB
    except OSError:
        return "Không đọc được dung lượng ổ đĩa."
    return f"Dung lượng trống: {free:.1f} GB"


def _device_hint() -> str:
    cuda = next(item for item in detect_devices() if item.identifier == "cuda")
    if cuda.available:
        return f"Đã phát hiện {cuda.name} với {cuda.total_memory_gb:.1f} GB VRAM."
    return "Không phát hiện GPU CUDA; ứng dụng sẽ chạy bằng CPU."


def _line_edit(parent: QWidget, name: str) -> QLineEdit:
    edit = QLineEdit(parent)
    edit.setObjectName(name)
    edit.setClearButtonEnabled(True)
    return edit


def _browse_row(parent: QWidget, edit: QLineEdit, handler: object) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(edit)
    button = QPushButton("Duyệt…", parent)
    button.setObjectName(f"{edit.objectName()}_browse")
    button.clicked.connect(handler)
    row.addWidget(button)
    return row


def _browse_widget(parent: QWidget, edit: QLineEdit, handler: object) -> QWidget:
    container = QWidget(parent)
    container.setLayout(_browse_row(parent, edit, handler))
    return container

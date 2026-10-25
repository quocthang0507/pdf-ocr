"""Application settings: 6-category Adobe/ABBYY-style preferences dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.config import ConfigManager, Preferences
from src.core.exceptions import PDFOCRError
from src.gui.components.settings_dock import populate_device_combo
from src.gui.dialogs.settings_tabs import (
    build_dictionary_tab,
    build_export_tab,
    build_general_tab,
    build_ocr_tab,
    build_performance_tab,
    build_viewing_tab,
    init_extended_controls,
)
from src.gui.i18n import LANGUAGE_NAMES, TranslationManager, localise_buttons
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
    """Stateful 6-category settings editor with JSON profile import/export."""

    weights_directory_changed = Signal(str)
    model_imported = Signal(str, str)
    theme_changed = Signal(str)
    language_changed = Signal(str)
    preferences_applied = Signal(object)
    migration_finished = Signal(str)
    migration_failed = Signal(str)

    # Type declarations for extended controls populated by init_extended_controls
    restore_session_check: QCheckBox
    confirm_delete_check: QCheckBox
    zoom_mode_combo: QComboBox
    color_mode_combo: QComboBox
    thumbnails_check: QCheckBox
    cache_pages_spin: QSpinBox
    default_engine_combo: QComboBox
    default_dpi_spin: QSpinBox
    auto_ocr_check: QCheckBox
    deskew_check: QCheckBox
    denoise_check: QCheckBox
    binarize_check: QCheckBox
    spell_correction_check: QCheckBox
    confidence_spin: QDoubleSpinBox
    custom_dict_edit: QPlainTextEdit
    export_format_combo: QComboBox
    compression_combo: QComboBox
    worker_threads_spin: QSpinBox

    def __init__(
        self, *, config: ConfigManager | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_dialog")
        self.setWindowTitle("Cài đặt toàn diện — PDF Reader, OCR & Editor")
        self.setMinimumSize(780, 520)
        self._config = config or ConfigManager()
        self._preferences = self._config.load()
        self._task: WeightsMigrationTask | None = None
        self._init_core_controls()
        init_extended_controls(self)
        self._populate_static_combos()
        self._build_layout()
        self._load_preferences(self._preferences)
        self._connect_signals()

    def _init_core_controls(self) -> None:
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
        self.import_model_button = QPushButton("Nhập model từ tệp…", self)
        self.import_model_button.setObjectName("import_model_button")
        self.open_models_button = QPushButton("Mở thư mục models", self)
        self.open_models_button.setObjectName("open_models_button")
        self.export_profile_button = QPushButton("Xuất cấu hình (.json)…", self)
        self.export_profile_button.setObjectName("export_profile_button")
        self.import_profile_button = QPushButton("Nhập cấu hình (.json)…", self)
        self.import_profile_button.setObjectName("import_profile_button")
        self.category_tabs = QTabWidget(self)
        self.category_tabs.setObjectName("settings_category_tabs")

    def _populate_static_combos(self) -> None:
        populate_device_combo(self.device_combo)
        for theme in THEMES:
            self.theme_combo.addItem(THEME_LABELS[theme], theme)
        for code, name in LANGUAGE_NAMES.items():
            self.language_combo.addItem(name, code)
        self.device_hint.setText(_device_hint())

    def _connect_signals(self) -> None:
        self.weights_edit.textChanged.connect(self._refresh_free_space)
        self.migrate_button.clicked.connect(self.start_weights_migration)
        self.import_model_button.clicked.connect(self.import_custom_model)
        self.open_models_button.clicked.connect(self.open_models_directory)
        self.export_profile_button.clicked.connect(self.export_profile_to_file)
        self.import_profile_button.clicked.connect(self.import_profile_from_file)

    # -- layout -----------------------------------------------------------

    def _build_storage_group(self) -> QGroupBox:
        storage = QGroupBox("Thư mục mô hình và weights", self)
        storage_layout = QVBoxLayout(storage)
        storage_layout.addLayout(
            _browse_row(self, self.weights_edit, self.browse_weights_dir)
        )
        storage_layout.addWidget(self.free_space_label)
        actions_row = QHBoxLayout()
        actions_row.addWidget(self.migrate_button)
        actions_row.addWidget(self.import_model_button)
        actions_row.addWidget(self.open_models_button)
        storage_layout.addLayout(actions_row)
        storage_layout.addWidget(self.progress_bar)
        return storage

    def _build_folders_group(self) -> QGroupBox:
        folders = QGroupBox("Thư mục mặc định", self)
        folder_form = QFormLayout(folders)
        folder_form.addRow(
            "Đầu vào:", _browse_widget(self, self.input_edit, self.browse_input_dir)
        )
        folder_form.addRow(
            "Đầu ra:", _browse_widget(self, self.output_edit, self.browse_output_dir)
        )
        return folders

    def _build_layout(self) -> None:
        storage = self._build_storage_group()
        folders = self._build_folders_group()
        self.category_tabs.addTab(build_general_tab(self), "Chung và Giao diện")
        self.category_tabs.addTab(build_viewing_tab(self), "Xem PDF")
        self.category_tabs.addTab(build_ocr_tab(self), "OCR và Tiền xử lý")
        self.category_tabs.addTab(build_dictionary_tab(self), "Từ điển và Chính tả")
        self.category_tabs.addTab(build_export_tab(self, folders), "Xuất tệp và PDF")
        self.category_tabs.addTab(
            build_performance_tab(self, storage), "Hiệu năng và AI"
        )

        buttons = localise_buttons(
            QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel,
                parent=self,
            )
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        footer = QHBoxLayout()
        footer.addWidget(self.export_profile_button)
        footer.addWidget(self.import_profile_button)
        footer.addStretch(1)
        footer.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.category_tabs, 1)
        layout.addLayout(footer)

    def _load_preferences(self, prefs: Preferences) -> None:
        _select_combo_data(self.device_combo, prefs.device)
        _select_combo_data(self.theme_combo, prefs.theme)
        _select_combo_data(self.language_combo, prefs.language)
        self.weights_edit.setText(prefs.weights_dir or "")
        self.input_edit.setText(prefs.input_dir or "")
        self.output_edit.setText(prefs.output_dir or "")
        self.restore_session_check.setChecked(prefs.restore_session)
        self.confirm_delete_check.setChecked(prefs.confirm_page_delete)
        _select_combo_data(self.zoom_mode_combo, prefs.default_zoom_mode)
        _select_combo_data(self.color_mode_combo, prefs.page_color_mode)
        self.thumbnails_check.setChecked(prefs.show_thumbnails)
        self.cache_pages_spin.setValue(prefs.cache_size_pages)
        _select_combo_data(self.default_engine_combo, prefs.default_engine)
        self.default_dpi_spin.setValue(prefs.default_dpi)
        self.auto_ocr_check.setChecked(prefs.auto_ocr_on_open)
        self.deskew_check.setChecked(prefs.default_deskew)
        self.denoise_check.setChecked(prefs.default_denoise)
        self.binarize_check.setChecked(prefs.default_binarize)
        self.spell_correction_check.setChecked(prefs.auto_spell_correction)
        self.confidence_spin.setValue(prefs.confidence_threshold)
        self.custom_dict_edit.setPlainText(prefs.custom_dictionary)
        _select_combo_data(self.export_format_combo, prefs.default_export_format)
        _select_combo_data(self.compression_combo, prefs.pdf_compression_level)
        self.worker_threads_spin.setValue(prefs.max_worker_threads)
        self._refresh_free_space()

    # -- folder & profile pickers -----------------------------------------

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

    def export_profile_to_file(self) -> Path | None:
        """Save the current dialog settings to an external JSON profile file."""
        from PySide6.QtWidgets import QFileDialog

        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Xuất cấu hình ra tệp JSON",
            str(Path.home() / "pdf_ocr_profile.json"),
            "Hồ sơ cấu hình JSON (*.json)",
        )
        if not selected:
            return None
        try:
            prefs = self._collect()
            return self._config.export_profile(selected, prefs)
        except Exception as error:
            QMessageBox.warning(self, "Xuất cấu hình", _safe_message(error))
            return None

    def import_profile_from_file(self) -> Preferences | None:
        """Load an external JSON profile file into the dialog controls."""
        from PySide6.QtWidgets import QFileDialog

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Nhập cấu hình từ tệp JSON",
            str(Path.home()),
            "Hồ sơ cấu hình JSON (*.json)",
        )
        if not selected:
            return None
        try:
            prefs = self._config.import_profile(selected)
        except Exception as error:
            QMessageBox.warning(self, "Nhập cấu hình", _safe_message(error))
            return None
        self._preferences = prefs
        self._load_preferences(prefs)
        return prefs

    def _refresh_free_space(self) -> None:
        self.free_space_label.setText(_free_space_text(self.weights_edit.text()))

    def _active_weights_manager(self) -> ModelWeightsManager:
        raw = self.weights_edit.text().strip() or self._preferences.weights_dir
        return ModelWeightsManager(raw)

    def open_models_directory(self) -> None:
        """Open the active models directory in the system file explorer."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        try:
            manager = self._active_weights_manager()
        except PDFOCRError as error:
            QMessageBox.warning(self, "Cài đặt", str(error))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(manager.base_path)))

    def import_custom_model(self, engine_id: str = "vietocr") -> Path | None:
        """Copy a user-selected .pth model file into the managed weights folder."""
        from PySide6.QtWidgets import QFileDialog

        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn tệp trọng số mô hình",
            str(Path.home()),
            "Trọng số PyTorch (*.pth *.pt *.bin);;Tất cả tệp (*)",
        )
        if not selected:
            return None
        try:
            manager = self._active_weights_manager()
            target = manager.import_model_file(engine_id, selected)
        except PDFOCRError as error:
            QMessageBox.warning(self, "Nhập model", str(error))
            return None
        self.model_imported.emit(engine_id, str(target))
        return target

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
        self.preferences_applied.emit(preferences)
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
            restore_session=self.restore_session_check.isChecked(),
            confirm_page_delete=self.confirm_delete_check.isChecked(),
            default_zoom_mode=str(self.zoom_mode_combo.currentData()),
            page_color_mode=str(self.color_mode_combo.currentData()),
            show_thumbnails=self.thumbnails_check.isChecked(),
            cache_size_pages=int(self.cache_pages_spin.value()),
            default_engine=str(self.default_engine_combo.currentData()),
            default_dpi=int(self.default_dpi_spin.value()),
            auto_ocr_on_open=self.auto_ocr_check.isChecked(),
            default_deskew=self.deskew_check.isChecked(),
            default_denoise=self.denoise_check.isChecked(),
            default_binarize=self.binarize_check.isChecked(),
            auto_spell_correction=self.spell_correction_check.isChecked(),
            confidence_threshold=float(self.confidence_spin.value()),
            custom_dictionary=self.custom_dict_edit.toPlainText().strip(),
            default_export_format=str(self.export_format_combo.currentData()),
            pdf_compression_level=str(self.compression_combo.currentData()),
            max_worker_threads=int(self.worker_threads_spin.value()),
        )

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt override
        if self._task is not None and self._task.isRunning():
            self._task.cancel()
            self._task.wait()
        super().closeEvent(event)  # type: ignore[arg-type]


def _select_combo_data(combo: QComboBox, value: object) -> None:
    index = combo.findData(value)
    combo.setCurrentIndex(max(index, 0))


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
    return "Đường dẫn thư mục hoặc tệp cấu hình không hợp lệ. Vui lòng chọn lại."


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

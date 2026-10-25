"""Side panel for the per-run OCR options: engine, device, DPI, and filters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.engines.engine_registry import EngineRegistry
from src.gui.components.engine_specs import (
    BROWSE_DIR_SENTINEL,
    BROWSE_FILE_SENTINEL,
    DEFAULT_DPI,
    DEFAULT_ENGINE_ID,
    ENGINE_PARAMETERS,
    MAX_DPI,
    MIN_DPI,
    MODEL_PARAM_KEYS,
    PREPROCESSING_STAGES,
    STRUCTURE_OPTIONS,
    TABLE_UNSUPPORTED_TIP,
    EngineParameter,
)
from src.services.device_service import detect_devices
from src.services.weights_manager import ModelWeightsManager

_BROWSE_DIR_SENTINEL = BROWSE_DIR_SENTINEL
_BROWSE_FILE_SENTINEL = BROWSE_FILE_SENTINEL
_MODEL_PARAM_KEYS = MODEL_PARAM_KEYS


def populate_device_combo(combo: QComboBox) -> None:
    """Offer every execution target, greying out the ones this machine lacks."""
    model = combo.model()
    for device in detect_devices():
        combo.addItem(device.description, device.identifier)
        if isinstance(model, QStandardItemModel) and not device.available:
            model.item(combo.count() - 1).setEnabled(False)


class SettingsDock(QWidget):
    """Stateful options panel; it publishes choices and never runs OCR itself."""

    options_changed = Signal(dict)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        weights_manager: ModelWeightsManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_dock")
        self.setMinimumWidth(335)
        self._weights_manager = weights_manager
        self._last_combo_value: dict[QComboBox, Any] = {}
        self.engine_combo = QComboBox(self)
        self.engine_combo.setObjectName("engine_combo")
        self.device_combo = QComboBox(self)
        self.device_combo.setObjectName("engine_device_combo")
        self.dpi_spin = QSpinBox(self)
        self.dpi_spin.setObjectName("dpi_spin")
        self.dpi_spin.setRange(MIN_DPI, MAX_DPI)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(DEFAULT_DPI)
        self.dpi_spin.setSuffix(" DPI")
        self.force_ocr_box = QCheckBox("Ép buộc OCR (bỏ qua lớp chữ gốc)", self)
        self.force_ocr_box.setObjectName("force_ocr_check")
        self.force_ocr_box.setToolTip(
            "Luôn chạy mô hình OCR trên ảnh trang kể cả khi PDF đã có lớp chữ gốc."
        )
        self.preprocessing_boxes: dict[str, QCheckBox] = {}
        self.structure_boxes: dict[str, QCheckBox] = {}
        self.param_widgets: dict[str, dict[str, QWidget]] = {}
        self.param_group = QGroupBox("Tham số mô hình", self)
        self.param_group.setObjectName("engine_params_group")
        self.param_form = QFormLayout(self.param_group)
        self.param_reset_button = QPushButton("Đặt lại mặc định", self.param_group)
        self.param_reset_button.setObjectName("engine_params_reset")
        self.param_reset_button.setToolTip(
            "Khôi phục tham số của mô hình đang chọn về giá trị mặc định"
        )
        self._table_engines = {
            metadata.engine_id
            for metadata in EngineRegistry.available()
            if metadata.supports_tables
        }
        self._populate()
        self._build_layout()
        self.refresh_engine_parameters(self._weights_manager)
        self._connect_changes()

    def _populate(self) -> None:
        for metadata in EngineRegistry.available():
            self.engine_combo.addItem(metadata.name, metadata.engine_id)
            self.engine_combo.setItemData(
                self.engine_combo.count() - 1,
                metadata.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        preferred = self.engine_combo.findData(DEFAULT_ENGINE_ID)
        self.engine_combo.setCurrentIndex(max(preferred, 0))
        populate_device_combo(self.device_combo)

    def _build_layout(self) -> None:
        container = QWidget(self)
        container.setObjectName("settings_scroll_content")
        engine_group = QGroupBox("Mô hình nhận diện", container)
        engine_form = QFormLayout(engine_group)
        engine_form.addRow("Mô hình OCR", self.engine_combo)
        engine_form.addRow("Thiết bị", self.device_combo)
        engine_form.addRow("Độ phân giải", self.dpi_spin)
        engine_form.addRow(self.force_ocr_box)
        self._build_param_widgets()
        self._sync_params()
        structure_group = self._build_structure_group(container)
        filter_group = self._build_filter_group(container)
        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(6, 4, 14, 8)
        for group in (engine_group, self.param_group, structure_group, filter_group):
            content_layout.addWidget(group)
        content_layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setObjectName("settings_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

    def _build_filter_group(self, parent: QWidget) -> QGroupBox:
        filter_group = QGroupBox("Tiền xử lý ảnh", parent)
        filter_layout = QVBoxLayout(filter_group)
        for key, label in PREPROCESSING_STAGES:
            box = QCheckBox(label, filter_group)
            box.setObjectName(f"preprocess_{key}")
            box.setChecked(True)
            self.preprocessing_boxes[key] = box
            filter_layout.addWidget(box)
        return filter_group

    def _build_structure_group(self, parent: QWidget) -> QGroupBox:
        structure_group = QGroupBox("Bố cục và cấu trúc", parent)
        structure_layout = QVBoxLayout(structure_group)
        for key, label, tip in STRUCTURE_OPTIONS:
            box = QCheckBox(label, structure_group)
            box.setObjectName(f"structure_{key}")
            box.setToolTip(tip)
            box.setChecked(True)
            self.structure_boxes[key] = box
            structure_layout.addWidget(box)
        self._sync_table_support()
        return structure_group

    def _build_param_widgets(self) -> None:
        """Create every engine's controls once so values survive switching models."""
        for engine_id, parameters in ENGINE_PARAMETERS.items():
            widgets: dict[str, QWidget] = {}
            for parameter in parameters:
                widget = self._parameter_widget(engine_id, parameter)
                widget.setToolTip(parameter.tip)
                widget.setObjectName(f"param_{engine_id}_{parameter.key}")
                self.param_form.addRow(parameter.label, widget)
                widgets[parameter.key] = widget
            self.param_widgets[engine_id] = widgets
        self.param_form.addRow(self.param_reset_button)

    def _parameter_widget(self, engine_id: str, parameter: EngineParameter) -> QWidget:
        if parameter.choices:
            combo = QComboBox(self.param_group)
            for label, value in parameter.choices:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(combo.findData(parameter.default), 0))
            self._last_combo_value[combo] = combo.currentData()
            combo.currentIndexChanged.connect(
                lambda _idx, c=combo, e=engine_id: self._on_combo_changed(e, c)
            )
            return combo
        if isinstance(parameter.default, float):
            number = QDoubleSpinBox(self.param_group)
            number.setDecimals(2)
            number.setRange(parameter.minimum, parameter.maximum)
            number.setSingleStep(parameter.step)
            number.setValue(parameter.default)
            number.valueChanged.connect(self._publish)
            return number
        spin = QSpinBox(self.param_group)
        spin.setRange(int(parameter.minimum), int(parameter.maximum))
        spin.setSingleStep(int(parameter.step))
        spin.setValue(int(parameter.default))
        spin.valueChanged.connect(self._publish)
        return spin

    def refresh_engine_parameters(
        self, weights_manager: ModelWeightsManager | None = None
    ) -> None:
        """Populate model drop-downs with weights found on disk plus a browse item."""
        if weights_manager is not None:
            self._weights_manager = weights_manager
        manager = self._weights_manager
        for engine_id, (param_key, sentinel) in _MODEL_PARAM_KEYS.items():
            widget = self.param_widgets.get(engine_id, {}).get(param_key)
            if not isinstance(widget, QComboBox):
                continue
            current = widget.currentData()
            defaults = next(
                p.choices for p in ENGINE_PARAMETERS[engine_id] if p.key == param_key
            )
            discovered = (
                manager.list_available_models(engine_id)
                if manager is not None
                else list(defaults)
            )
            self._rebuild_model_combo(widget, discovered, sentinel, current)

    def _rebuild_model_combo(
        self,
        combo: QComboBox,
        choices: list[tuple[str, str]],
        sentinel: str,
        current: Any,
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        for label, value in choices:
            combo.addItem(label, value)
        if isinstance(current, str) and current and combo.findData(current) < 0:
            if current not in (_BROWSE_FILE_SENTINEL, _BROWSE_DIR_SENTINEL):
                combo.addItem(f"Tùy chỉnh: {Path(current).name}", current)
        browse_label = (
            "+ Chọn tệp .pth tùy chỉnh…"
            if sentinel == _BROWSE_FILE_SENTINEL
            else "+ Chọn thư mục model tùy chỉnh…"
        )
        combo.addItem(browse_label, sentinel)
        target = combo.findData(current)
        combo.setCurrentIndex(target if target >= 0 else 0)
        self._last_combo_value[combo] = combo.currentData()
        combo.blockSignals(False)

    def _on_combo_changed(self, engine_id: str, combo: QComboBox) -> None:
        data = combo.currentData()
        if data in (_BROWSE_FILE_SENTINEL, _BROWSE_DIR_SENTINEL):
            self._browse_custom_model(engine_id, combo, str(data))
            return
        self._last_combo_value[combo] = data
        self._publish()

    def _browse_custom_model(
        self, engine_id: str, combo: QComboBox, sentinel: str
    ) -> None:
        start_dir = (
            str(self._weights_manager.get_engine_weights_dir(engine_id))
            if self._weights_manager is not None
            else str(Path.home())
        )
        if sentinel == _BROWSE_FILE_SENTINEL:
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Chọn tệp trọng số (.pth)",
                start_dir,
                "Trọng số PyTorch (*.pth *.pt);;Tất cả tệp (*)",
            )
        else:
            chosen = QFileDialog.getExistingDirectory(
                self, "Chọn thư mục model", start_dir
            )
        if chosen:
            self.add_custom_model_choice(engine_id, chosen)
            self._publish()
            return
        previous = self._last_combo_value.get(combo)
        combo.blockSignals(True)
        index = combo.findData(previous)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def add_custom_model_choice(
        self, engine_id: str, path: str, label: str = ""
    ) -> None:
        """Insert and select a custom model path in the engine's model drop-down."""
        entry = _MODEL_PARAM_KEYS.get(engine_id)
        if entry is None:
            return
        param_key, sentinel = entry
        widget = self.param_widgets.get(engine_id, {}).get(param_key)
        if not isinstance(widget, QComboBox):
            return
        widget.blockSignals(True)
        existing = widget.findData(path)
        if existing < 0:
            display = label or f"Tùy chỉnh: {Path(path).name}"
            sentinel_idx = widget.findData(sentinel)
            insert_at = sentinel_idx if sentinel_idx >= 0 else widget.count()
            widget.insertItem(insert_at, display, path)
            existing = insert_at
        widget.setCurrentIndex(existing)
        self._last_combo_value[widget] = path
        widget.blockSignals(False)

    def _sync_params(self) -> None:
        """Show only the controls that belong to the chosen model."""
        engine_id = self.engine_combo.currentData()
        for owner, widgets in self.param_widgets.items():
            for widget in widgets.values():
                visible = owner == engine_id
                widget.setVisible(visible)
                label = self.param_form.labelForField(widget)
                if label is not None:
                    label.setVisible(visible)
        has_params = engine_id in self.param_widgets
        self.param_reset_button.setVisible(has_params)
        self.param_group.setVisible(has_params)

    def reset_engine_params(self) -> None:
        """Put the chosen model's parameters back to their defaults."""
        engine_id = self.engine_combo.currentData()
        for parameter in ENGINE_PARAMETERS.get(engine_id, ()):
            widget = self.param_widgets[engine_id][parameter.key]
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(widget.findData(parameter.default), 0))
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                widget.setValue(parameter.default)

    def engine_params(self) -> dict[str, Any]:
        """Values of the chosen model's tunable settings, keyed as its config."""
        engine_id = self.engine_combo.currentData()
        values: dict[str, Any] = {}
        for parameter in ENGINE_PARAMETERS.get(engine_id, ()):
            widget = self.param_widgets[engine_id][parameter.key]
            if isinstance(widget, QComboBox):
                val = widget.currentData()
                if val in (_BROWSE_FILE_SENTINEL, _BROWSE_DIR_SENTINEL):
                    val = parameter.default
                if val == "" and parameter.default == "":
                    continue
                values[parameter.key] = val
            elif isinstance(widget, QDoubleSpinBox):
                values[parameter.key] = float(widget.value())
            elif isinstance(widget, QSpinBox):
                values[parameter.key] = int(widget.value())
        return values

    def _sync_table_support(self) -> None:
        """Grey out table recognition when the chosen model cannot do it."""
        box = self.structure_boxes["detect_tables"]
        supported = self.engine_combo.currentData() in self._table_engines
        box.setEnabled(supported)
        tip = next(tip for key, _l, tip in STRUCTURE_OPTIONS if key == "detect_tables")
        box.setToolTip(tip if supported else TABLE_UNSUPPORTED_TIP)

    def _connect_changes(self) -> None:
        self.engine_combo.currentIndexChanged.connect(self._sync_table_support)
        self.engine_combo.currentIndexChanged.connect(self._sync_params)
        self.param_reset_button.clicked.connect(self.reset_engine_params)
        for box in self.structure_boxes.values():
            box.toggled.connect(self._publish)
        self.engine_combo.currentIndexChanged.connect(self._publish)
        self.device_combo.currentIndexChanged.connect(self._publish)
        self.dpi_spin.valueChanged.connect(self._publish)
        self.force_ocr_box.toggled.connect(self._publish)
        for box in self.preprocessing_boxes.values():
            box.toggled.connect(self._publish)

    def options(self) -> dict[str, Any]:
        """Return the current run options as a plain, serialisable mapping."""
        return {
            "engine_id": self.engine_combo.currentData(),
            "device": self.device_combo.currentData(),
            "dpi": self.dpi_spin.value(),
            "force_ocr": self.force_ocr_box.isChecked(),
            "engine_params": self.engine_params(),
            "preprocessing": {
                key: box.isChecked() for key, box in self.preprocessing_boxes.items()
            },
            "detect_tables": self.structure_boxes["detect_tables"].isEnabled()
            and self.structure_boxes["detect_tables"].isChecked(),
            "reading_order": self.structure_boxes["reading_order"].isChecked(),
            "merge_paragraphs": self.structure_boxes["merge_paragraphs"].isChecked(),
            "spell_check": self.structure_boxes["spell_check"].isChecked(),
        }

    def _publish(self) -> None:
        self.options_changed.emit(self.options())

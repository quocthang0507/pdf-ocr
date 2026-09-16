"""Side panel for the per-run OCR options: engine, device, DPI, and filters."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.engines.engine_registry import EngineRegistry
from src.services.device_service import detect_devices

MIN_DPI = 72
MAX_DPI = 600
DEFAULT_DPI = 300

PREPROCESSING_STAGES: tuple[tuple[str, str], ...] = (
    ("orientation", "Tự xoay đúng hướng"),
    ("deskew", "Làm thẳng ảnh nghiêng"),
    ("borders", "Cắt viền thừa"),
    ("enhance", "Tăng cường chất lượng ảnh"),
)


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_dock")
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
        self.preprocessing_boxes: dict[str, QCheckBox] = {}
        self._populate()
        self._build_layout()
        self._connect_changes()

    def _populate(self) -> None:
        for metadata in EngineRegistry.available():
            self.engine_combo.addItem(metadata.name, metadata.engine_id)
            self.engine_combo.setItemData(
                self.engine_combo.count() - 1,
                metadata.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        populate_device_combo(self.device_combo)

    def _build_layout(self) -> None:
        engine_group = QGroupBox("Mô hình nhận diện", self)
        engine_form = QFormLayout(engine_group)
        engine_form.addRow("Mô hình OCR", self.engine_combo)
        engine_form.addRow("Thiết bị", self.device_combo)
        engine_form.addRow("Độ phân giải", self.dpi_spin)

        filter_group = QGroupBox("Tiền xử lý ảnh", self)
        filter_layout = QVBoxLayout(filter_group)
        for key, label in PREPROCESSING_STAGES:
            box = QCheckBox(label, filter_group)
            box.setObjectName(f"preprocess_{key}")
            box.setChecked(True)
            self.preprocessing_boxes[key] = box
            filter_layout.addWidget(box)

        layout = QVBoxLayout(self)
        layout.addWidget(engine_group)
        layout.addWidget(filter_group)
        layout.addStretch(1)

    def _connect_changes(self) -> None:
        self.engine_combo.currentIndexChanged.connect(self._publish)
        self.device_combo.currentIndexChanged.connect(self._publish)
        self.dpi_spin.valueChanged.connect(self._publish)
        for box in self.preprocessing_boxes.values():
            box.toggled.connect(self._publish)

    def options(self) -> dict[str, Any]:
        """Return the current run options as a plain, serialisable mapping."""
        return {
            "engine_id": self.engine_combo.currentData(),
            "device": self.device_combo.currentData(),
            "dpi": self.dpi_spin.value(),
            "preprocessing": {
                key: box.isChecked() for key, box in self.preprocessing_boxes.items()
            },
        }

    def _publish(self) -> None:
        self.options_changed.emit(self.options())

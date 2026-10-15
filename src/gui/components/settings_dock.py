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

DEFAULT_ENGINE_ID = "vietocr"
MIN_DPI = 72
MAX_DPI = 600
DEFAULT_DPI = 300

PREPROCESSING_STAGES: tuple[tuple[str, str], ...] = (
    ("orientation", "Tự xoay đúng hướng"),
    ("deskew", "Làm thẳng ảnh nghiêng"),
    ("borders", "Cắt viền thừa"),
    ("enhance", "Tăng cường chất lượng ảnh"),
)


#: Layout choices: key, label, tooltip. All are on by default.
STRUCTURE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "detect_tables",
        "Nhận diện bảng biểu",
        "Tách bảng thành lưới hàng/cột để chỉnh sửa và xuất Excel/Word. "
        "Chỉ các mô hình hỗ trợ bảng (như PaddleOCR) mới dùng được.",
    ),
    (
        "reading_order",
        "Sắp xếp thứ tự đọc nhiều cột",
        "Đọc hết cột này rồi mới sang cột khác, không đọc xuyên cột.",
    ),
    (
        "merge_paragraphs",
        "Gộp các dòng thành đoạn văn",
        "Nối các dòng liên tiếp thuộc cùng một đoạn thành một khối.",
    ),
)
TABLE_UNSUPPORTED_TIP = "Mô hình đang chọn không hỗ trợ nhận diện bảng biểu."


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
        self.structure_boxes: dict[str, QCheckBox] = {}
        self._table_engines = {
            metadata.engine_id
            for metadata in EngineRegistry.available()
            if metadata.supports_tables
        }
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
        preferred = self.engine_combo.findData(DEFAULT_ENGINE_ID)
        self.engine_combo.setCurrentIndex(max(preferred, 0))
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

        structure_group = QGroupBox("Bố cục & cấu trúc", self)
        structure_layout = QVBoxLayout(structure_group)
        for key, label, tip in STRUCTURE_OPTIONS:
            box = QCheckBox(label, structure_group)
            box.setObjectName(f"structure_{key}")
            box.setToolTip(tip)
            box.setChecked(True)
            self.structure_boxes[key] = box
            structure_layout.addWidget(box)
        self._sync_table_support()

        layout = QVBoxLayout(self)
        layout.addWidget(engine_group)
        layout.addWidget(structure_group)
        layout.addWidget(filter_group)
        layout.addStretch(1)

    def _sync_table_support(self) -> None:
        """Grey out table recognition when the chosen model cannot do it."""
        box = self.structure_boxes["detect_tables"]
        supported = self.engine_combo.currentData() in self._table_engines
        box.setEnabled(supported)
        tip = next(tip for key, _l, tip in STRUCTURE_OPTIONS if key == "detect_tables")
        box.setToolTip(tip if supported else TABLE_UNSUPPORTED_TIP)

    def _connect_changes(self) -> None:
        self.engine_combo.currentIndexChanged.connect(self._sync_table_support)
        for box in self.structure_boxes.values():
            box.toggled.connect(self._publish)
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
            # Table recognition only counts when the model can actually do it.
            "detect_tables": self.structure_boxes["detect_tables"].isEnabled()
            and self.structure_boxes["detect_tables"].isChecked(),
            "reading_order": self.structure_boxes["reading_order"].isChecked(),
            "merge_paragraphs": self.structure_boxes["merge_paragraphs"].isChecked(),
        }

    def _publish(self) -> None:
        self.options_changed.emit(self.options())

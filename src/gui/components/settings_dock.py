"""Side panel for the per-run OCR options: engine, device, DPI, and filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QPushButton,
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


@dataclass(frozen=True)
class EngineParameter:
    """One tunable engine setting; `choices` makes it a drop-down, else a number."""

    key: str
    label: str
    default: Any
    tip: str
    choices: tuple[tuple[str, Any], ...] = ()
    minimum: float = 0
    maximum: float = 1
    step: float = 1


_LANGUAGE_CHOICES: tuple[tuple[str, Any], ...] = (
    ("Tiếng Việt + Anh", ("vi", "en")),
    ("Chỉ tiếng Việt", ("vi",)),
    ("Chỉ tiếng Anh", ("en",)),
)

#: Settings each engine accepts beyond device; mirrors its CONFIG_SCHEMA.
ENGINE_PARAMETERS: dict[str, tuple[EngineParameter, ...]] = {
    "vietocr": (
        EngineParameter(
            "architecture",
            "Kiến trúc",
            "vgg_transformer",
            "vgg_transformer chính xác hơn; vgg_seq2seq nhanh hơn.",
            choices=(
                ("VGG Transformer (chính xác)", "vgg_transformer"),
                ("VGG Seq2Seq (nhanh)", "vgg_seq2seq"),
            ),
        ),
    ),
    "surya": (
        EngineParameter(
            "langs",
            "Ngôn ngữ",
            ("vi", "en"),
            "Ngôn ngữ có trong tài liệu.",
            choices=_LANGUAGE_CHOICES,
        ),
    ),
    "easyocr": (
        EngineParameter(
            "langs",
            "Ngôn ngữ",
            ("vi", "en"),
            "Ngôn ngữ có trong tài liệu.",
            choices=_LANGUAGE_CHOICES,
        ),
        EngineParameter(
            "beam_width",
            "Beam width",
            5,
            "Càng lớn càng chính xác nhưng chậm hơn.",
            minimum=1,
            maximum=100,
        ),
    ),
    "paddle": (
        EngineParameter(
            "lang",
            "Ngôn ngữ",
            "vi",
            "Ngôn ngữ chính của tài liệu.",
            choices=(("Tiếng Việt", "vi"), ("Tiếng Anh", "en")),
        ),
        EngineParameter(
            "det_db_thresh",
            "Ngưỡng phát hiện chữ",
            0.3,
            "Thấp hơn: bắt được chữ mờ nhưng dễ nhiễu; cao hơn: chặt chẽ hơn.",
            minimum=0.05,
            maximum=0.95,
            step=0.05,
        ),
    ),
    "trocr": (
        EngineParameter(
            "checkpoint",
            "Loại chữ",
            "microsoft/trocr-base-handwritten",
            "Chọn bản huấn luyện cho chữ viết tay hoặc chữ in.",
            choices=(
                ("Chữ viết tay", "microsoft/trocr-base-handwritten"),
                ("Chữ in", "microsoft/trocr-base-printed"),
            ),
        ),
        EngineParameter(
            "max_new_tokens",
            "Số token tối đa",
            128,
            "Giới hạn độ dài mỗi dòng nhận diện.",
            minimum=1,
            maximum=512,
            step=16,
        ),
        EngineParameter(
            "timeout_seconds",
            "Thời gian tối đa (giây)",
            30.0,
            "Dừng nếu một dòng xử lý quá lâu.",
            minimum=1,
            maximum=300,
            step=5,
        ),
    ),
}


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

        self._build_param_widgets()
        self._sync_params()

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
        layout.addWidget(self.param_group)
        layout.addWidget(structure_group)
        layout.addWidget(filter_group)
        layout.addStretch(1)

    def _build_param_widgets(self) -> None:
        """Create every engine's controls once so values survive switching models."""
        for engine_id, parameters in ENGINE_PARAMETERS.items():
            widgets: dict[str, QWidget] = {}
            for parameter in parameters:
                widget = self._parameter_widget(parameter)
                widget.setToolTip(parameter.tip)
                widget.setObjectName(f"param_{engine_id}_{parameter.key}")
                self.param_form.addRow(parameter.label, widget)
                widgets[parameter.key] = widget
            self.param_widgets[engine_id] = widgets
        self.param_form.addRow(self.param_reset_button)

    def _parameter_widget(self, parameter: EngineParameter) -> QWidget:
        if parameter.choices:
            combo = QComboBox(self.param_group)
            for label, value in parameter.choices:
                combo.addItem(label, value)
            combo.setCurrentIndex(max(combo.findData(parameter.default), 0))
            combo.currentIndexChanged.connect(self._publish)
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
                values[parameter.key] = widget.currentData()
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
        for box in self.preprocessing_boxes.values():
            box.toggled.connect(self._publish)

    def options(self) -> dict[str, Any]:
        """Return the current run options as a plain, serialisable mapping."""
        return {
            "engine_id": self.engine_combo.currentData(),
            "device": self.device_combo.currentData(),
            "dpi": self.dpi_spin.value(),
            "engine_params": self.engine_params(),
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

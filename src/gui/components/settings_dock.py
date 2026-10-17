"""Side panel for the per-run OCR options: engine, device, DPI, and filters."""

from __future__ import annotations

from dataclasses import dataclass
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
    QGroupBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.engines.engine_registry import EngineRegistry
from src.services.device_service import detect_devices
from src.services.weights_manager import ModelWeightsManager

DEFAULT_ENGINE_ID = "vietocr"
MIN_DPI = 72
MAX_DPI = 600
DEFAULT_DPI = 300
_BROWSE_FILE_SENTINEL = "__browse_file__"
_BROWSE_DIR_SENTINEL = "__browse_dir__"
_MODEL_PARAM_KEYS: dict[str, tuple[str, str]] = {
    "vietocr": ("architecture", _BROWSE_FILE_SENTINEL),
    "trocr": ("checkpoint", _BROWSE_DIR_SENTINEL),
    "easyocr": ("recog_network", _BROWSE_FILE_SENTINEL),
    "paddle": ("rec_model_dir", _BROWSE_DIR_SENTINEL),
    "chandra": ("checkpoint", _BROWSE_DIR_SENTINEL),
    "dots_ocr": ("checkpoint", _BROWSE_DIR_SENTINEL),
}

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
        "Chỉ các mô hình hỗ trợ bảng (như PaddleOCR, Chandra, dots.ocr) mới dùng được.",
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
    (
        "spell_check",
        "Sửa lỗi chính tả & dấu tiếng Việt (N-gram)",
        "Tự động sửa lỗi dấu thanh, nguyên âm mũ/móc và từ ghép tiếng Việt "
        "theo ngữ cảnh N-gram (1/2/3-gram) sau khi OCR.",
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
    (
        "Đa ngôn ngữ (Việt, Anh, Pháp, Trung, Nhật, Hàn)",
        ("vi", "en", "fr", "zh", "ja", "ko"),
    ),
)

#: Settings each engine accepts beyond device; mirrors its CONFIG_SCHEMA.
ENGINE_PARAMETERS: dict[str, tuple[EngineParameter, ...]] = {
    "vietocr": (
        EngineParameter(
            "architecture",
            "Kiến trúc / Biến thể",
            "vgg_transformer",
            (
                "Chọn biến thể kiến trúc VietOCR theo mục đích (chính xác cao, "
                "tốc độ nhanh, đặc trưng sâu) hoặc tệp .pth tùy chỉnh."
            ),
            choices=(
                ("VGG19-BN + Transformer (Chính xác cao)", "vgg_transformer"),
                ("VGG19-BN + Seq2Seq Attention (Tốc độ nhanh)", "vgg_seq2seq"),
                ("ResNet50 + Transformer (Chữ phức tạp)", "resnet_transformer"),
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
            "recog_network",
            "Mạng nhận diện",
            "",
            (
                "Chọn thế hệ mạng nhận diện chữ (Gen 2 nhanh nhẹ, Gen 1 cổ điển) "
                "hoặc tệp .pth tùy chỉnh."
            ),
            choices=(
                ("Tự động theo ngôn ngữ", ""),
                ("Generation 2 - Latin / Tiếng Việt (latin_g2)", "latin_g2"),
                ("Generation 2 - Tiếng Anh tối ưu (english_g2)", "english_g2"),
                ("Generation 1 - Latin cổ điển (latin_g1)", "latin_g1"),
            ),
        ),
        EngineParameter(
            "detect_network",
            "Mạng phát hiện chữ",
            "",
            "CRAFT chính xác cho chữ nghiêng/cong; DBNet18 nhanh và nhẹ RAM.",
            choices=(
                ("CRAFT (Mặc định - Chính xác cao)", ""),
                ("DBNet18 (Tốc độ cao, nhẹ RAM)", "dbnet18"),
            ),
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
            choices=(
                ("Tiếng Việt", "vi"),
                ("Tiếng Anh", "en"),
                ("Hệ chữ Latin (Đa ngôn ngữ)", "latin"),
                ("Tiếng Trung / Đa ngôn ngữ (ch)", "ch"),
                ("Tiếng Nhật", "japan"),
                ("Tiếng Hàn", "korean"),
                ("Tiếng Pháp", "fr"),
                ("Tiếng Đức", "german"),
            ),
        ),
        EngineParameter(
            "pipeline_mode",
            "Nhánh mô hình (Pipeline)",
            "",
            (
                "Chọn nhánh xử lý: PP-OCR tiêu chuẩn, PP-StructureV3 "
                "(bố cục/bảng/công thức) hoặc PaddleOCR-VL (VLM 0.9B đa tác vụ)."
            ),
            choices=(
                ("Tiêu chuẩn (PP-OCR + PP-Structure)", ""),
                (
                    "PP-StructureV3 (Phân tích bố cục, bảng, công thức)",
                    "pp_structure_v3",
                ),
                (
                    "PaddleOCR-VL 1.6 (VLM 0.9B: Bảng, công thức, chữ cổ, con dấu)",
                    "paddleocr_vl",
                ),
            ),
        ),
        EngineParameter(
            "ocr_version",
            "Phiên bản PP-OCR",
            "",
            (
                "Chọn thế hệ PP-OCR: v6 (50 ngôn ngữ, chính xác cao), "
                "v5 (chữ viết tay/dọc), v4 (ổn định), v3."
            ),
            choices=(
                ("Tự động (Mặc định)", ""),
                ("PP-OCRv6 (Mới nhất - 50 ngôn ngữ, tốc độ cao)", "PP-OCRv6"),
                ("PP-OCRv5 (Đa kịch bản, chữ viết tay, chữ dọc)", "PP-OCRv5"),
                ("PP-OCRv4 (Ổn định, phổ biến)", "PP-OCRv4"),
                ("PP-OCRv3 (Tương thích rộng)", "PP-OCRv3"),
            ),
        ),
        EngineParameter(
            "model_tier",
            "Cấp độ mô hình",
            "",
            (
                "Mobile/Small ưu tiên tốc độ & nhẹ RAM; "
                "Server/Medium ưu tiên độ chính xác tối đa."
            ),
            choices=(
                ("Tự động theo phiên bản", ""),
                ("Mobile / Small (Nhanh, nhẹ RAM/CPU)", "mobile"),
                ("Server / Medium (Độ chính xác tối đa)", "server"),
                ("Tiny (Siêu nhẹ 1.5M cho máy yếu)", "tiny"),
            ),
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
        EngineParameter(
            "rec_model_dir",
            "Model nhận diện tùy chỉnh",
            "",
            "Thư mục model nhận diện PaddleOCR tùy chỉnh (để trống nếu dùng mặc định).",
            choices=(("Mặc định theo phiên bản", ""),),
        ),
    ),
    "trocr": (
        EngineParameter(
            "checkpoint",
            "Biến thể Checkpoint",
            "microsoft/trocr-base-handwritten",
            (
                "Chọn biến thể TrOCR theo kích thước (Small/Base/Large) và loại chữ "
                "(viết tay/chữ in/chữ cảnh) hoặc thư mục cục bộ."
            ),
            choices=(
                (
                    "Base - Chữ viết tay (~334M, Cân bằng)",
                    "microsoft/trocr-base-handwritten",
                ),
                (
                    "Base - Chữ in / Hóa đơn (~334M, Cân bằng)",
                    "microsoft/trocr-base-printed",
                ),
                (
                    "Small - Chữ viết tay (~62M, Nhanh & nhẹ)",
                    "microsoft/trocr-small-handwritten",
                ),
                ("Small - Chữ in (~62M, Nhanh & nhẹ)", "microsoft/trocr-small-printed"),
                (
                    "Large - Chữ viết tay (~558M, Chính xác nhất)",
                    "microsoft/trocr-large-handwritten",
                ),
                (
                    "Large - Chữ in (~558M, Chính xác nhất)",
                    "microsoft/trocr-large-printed",
                ),
                ("Base - Chữ cảnh tự nhiên (Scene Text)", "microsoft/trocr-base-str"),
                ("Large - Chữ cảnh tự nhiên (Scene Text)", "microsoft/trocr-large-str"),
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
    "chandra": (
        EngineParameter(
            "checkpoint",
            "Biến thể Model",
            "datalab-to/chandra",
            (
                "Chọn phiên bản Chandra OCR (v1 hoặc v2 Flagship 5B) "
                "hoặc thư mục model cục bộ."
            ),
            choices=(
                ("Chandra OCR v1 (Bố cục, bảng, viết tay)", "datalab-to/chandra"),
                (
                    "Chandra OCR v2 (Flagship 5B - Chính xác cao nhất)",
                    "datalab-to/chandra-ocr-2",
                ),
            ),
        ),
        EngineParameter(
            "prompt_type",
            "Chế độ trích xuất",
            "ocr_layout",
            (
                "ocr_layout giữ nguyên tọa độ khối, bảng HTML và công thức; "
                "ocr trích xuất nhanh thuần văn bản."
            ),
            choices=(
                ("Bố cục đầy đủ + Bảng + Toán (ocr_layout)", "ocr_layout"),
                ("Thuần văn bản Markdown nhanh (ocr)", "ocr"),
            ),
        ),
        EngineParameter(
            "method",
            "Phương thức chạy",
            "hf",
            "Chạy trực tiếp qua HuggingFace (hf) hoặc máy chủ vLLM cục bộ (vllm).",
            choices=(
                ("HuggingFace (Cục bộ)", "hf"),
                ("vLLM Server (Tốc độ cao)", "vllm"),
            ),
        ),
        EngineParameter(
            "max_new_tokens",
            "Số token tối đa",
            2048,
            "Số lượng token đầu ra tối đa cho mỗi trang.",
            minimum=64,
            maximum=16384,
            step=256,
        ),
    ),
    "dots_ocr": (
        EngineParameter(
            "checkpoint",
            "Biến thể Model",
            "rednote-hilab/dots.ocr",
            (
                "Chọn biến thể dots.ocr (1.7B chuẩn hoặc dots.mocr 1.5 đa tác vụ) "
                "hoặc thư mục cục bộ."
            ),
            choices=(
                ("dots.ocr 1.7B (Bố cục, bảng, công thức)", "rednote-hilab/dots.ocr"),
                ("dots.mocr 1.5 (Đa tác vụ + SVG)", "rednote-hilab/dots.mocr"),
                ("dots-studio/dots.ocr (Chính thức)", "dots-studio/dots.ocr"),
            ),
        ),
        EngineParameter(
            "prompt_mode",
            "Chế độ Prompt",
            "layout_all",
            (
                "layout_all xuất JSON tọa độ + bảng HTML + LaTeX; "
                "ocr xuất văn bản thuần tránh lặp."
            ),
            choices=(
                ("Đầy đủ bố cục + Bảng HTML + LaTeX (layout_all)", "layout_all"),
                ("Thuần văn bản nhanh, chống lặp (ocr)", "ocr"),
            ),
        ),
        EngineParameter(
            "method",
            "Phương thức chạy",
            "hf",
            "Chạy trực tiếp qua HuggingFace (hf) hoặc máy chủ vLLM cục bộ (vllm).",
            choices=(
                ("HuggingFace (Cục bộ)", "hf"),
                ("vLLM Server (Tốc độ cao)", "vllm"),
            ),
        ),
        EngineParameter(
            "max_new_tokens",
            "Số token tối đa",
            4096,
            "Số lượng token đầu ra tối đa cho mỗi trang.",
            minimum=64,
            maximum=24000,
            step=512,
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

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        weights_manager: ModelWeightsManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_dock")
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
        engine_group = QGroupBox("Mô hình nhận diện", self)
        engine_form = QFormLayout(engine_group)
        engine_form.addRow("Mô hình OCR", self.engine_combo)
        engine_form.addRow("Thiết bị", self.device_combo)
        engine_form.addRow("Độ phân giải", self.dpi_spin)
        engine_form.addRow(self.force_ocr_box)

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
            # Table recognition only counts when the model can actually do it.
            "detect_tables": self.structure_boxes["detect_tables"].isEnabled()
            and self.structure_boxes["detect_tables"].isChecked(),
            "reading_order": self.structure_boxes["reading_order"].isChecked(),
            "merge_paragraphs": self.structure_boxes["merge_paragraphs"].isChecked(),
            "spell_check": self.structure_boxes["spell_check"].isChecked(),
        }

    def _publish(self) -> None:
        self.options_changed.emit(self.options())

"""Tab page builders and option catalogs for the 6-category SettingsDialog."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.engines.engine_registry import EngineRegistry

if TYPE_CHECKING:
    from src.gui.dialogs.settings_dialog import SettingsDialog

ZOOM_MODE_LABELS = {
    "fit_page": "Vừa trang (Fit Page)",
    "fit_width": "Vừa chiều ngang (Fit Width)",
    "actual_size": "Kích thước thật (100%)",
}

COLOR_MODE_LABELS = {
    "normal": "Bình thường (Nền trắng)",
    "sepia": "Giấy vàng bảo vệ mắt (Sepia)",
    "night": "Chế độ ban đêm (Đảo màu thông minh)",
}

EXPORT_FORMAT_LABELS = {
    "docx": "Word (.docx)",
    "pdf": "PDF có lớp văn bản (.pdf)",
    "txt": "Văn bản thuần (.txt)",
    "md": "Markdown (.md)",
    "json": "JSON có cấu trúc (.json)",
    "xlsx": "Bảng tính Excel (.xlsx)",
}

COMPRESSION_LABELS = {
    "fast": "Nhanh (Giữ nguyên chất lượng ảnh)",
    "balanced": "Cân bằng (Khuyên dùng)",
    "max": "Tối đa (Thu gọn dung lượng mạnh nhất)",
}


def init_extended_controls(dialog: SettingsDialog) -> None:
    """Create all extended widgets on SettingsDialog across the 6 categories."""
    # 1. General & Appearance
    dialog.restore_session_check = QCheckBox(
        "Khôi phục tài liệu đang mở từ phiên làm việc trước", dialog
    )
    dialog.confirm_delete_check = QCheckBox(
        "Hiển thị hộp thoại xác nhận trước khi xóa trang PDF", dialog
    )
    # 2. PDF Viewing
    dialog.zoom_mode_combo = QComboBox(dialog)
    for key, label in ZOOM_MODE_LABELS.items():
        dialog.zoom_mode_combo.addItem(label, key)
    dialog.color_mode_combo = QComboBox(dialog)
    for key, label in COLOR_MODE_LABELS.items():
        dialog.color_mode_combo.addItem(label, key)
    dialog.thumbnails_check = QCheckBox(
        "Hiển thị ảnh thu nhỏ (Thumbnail) trong danh sách trang", dialog
    )
    dialog.cache_pages_spin = QSpinBox(dialog)
    dialog.cache_pages_spin.setRange(1, 32)
    dialog.cache_pages_spin.setSuffix(" trang")
    # 3. OCR & Preprocessing
    dialog.default_engine_combo = QComboBox(dialog)
    for metadata in EngineRegistry.available():
        dialog.default_engine_combo.addItem(metadata.name, metadata.engine_id)
    dialog.default_dpi_spin = QSpinBox(dialog)
    dialog.default_dpi_spin.setRange(72, 1200)
    dialog.default_dpi_spin.setSingleStep(50)
    dialog.default_dpi_spin.setSuffix(" DPI")
    dialog.auto_ocr_check = QCheckBox(
        "Tự động chạy OCR ngay khi mở tệp PDF dạng ảnh quét (Scan)", dialog
    )
    dialog.deskew_check = QCheckBox("Tự động căn thẳng trang nghiêng (Deskew)", dialog)
    dialog.denoise_check = QCheckBox("Khử nhiễu hạt văn bản quét (Denoise)", dialog)
    dialog.binarize_check = QCheckBox(
        "Tăng tương phản và nhị phân hóa thích ứng (Binarize)", dialog
    )
    _init_spell_export_ai_controls(dialog)


def _init_spell_export_ai_controls(dialog: SettingsDialog) -> None:
    # 4. Dictionary & Spellcheck
    dialog.spell_correction_check = QCheckBox(
        "Tự động gợi ý và sửa lỗi chính tả tiếng Việt hậu xử lý (N-gram)", dialog
    )
    dialog.confidence_spin = QDoubleSpinBox(dialog)
    dialog.confidence_spin.setRange(0.50, 0.99)
    dialog.confidence_spin.setSingleStep(0.05)
    dialog.confidence_spin.setDecimals(2)
    dialog.custom_dict_edit = QPlainTextEdit(dialog)
    dialog.custom_dict_edit.setPlaceholderText(
        "Nhập các từ viết tắt, tên riêng hoặc thuật ngữ chuyên ngành "
        "(phân tách bằng dấu phẩy hoặc xuống dòng, ví dụ: UBND, HĐND, Bộ Tài chính)..."
    )
    dialog.custom_dict_edit.setMaximumHeight(95)
    # 5. Export & PDF
    dialog.export_format_combo = QComboBox(dialog)
    for key, label in EXPORT_FORMAT_LABELS.items():
        dialog.export_format_combo.addItem(label, key)
    dialog.compression_combo = QComboBox(dialog)
    for key, label in COMPRESSION_LABELS.items():
        dialog.compression_combo.addItem(label, key)
    # 6. Performance & AI
    dialog.worker_threads_spin = QSpinBox(dialog)
    dialog.worker_threads_spin.setRange(1, 16)
    dialog.worker_threads_spin.setSuffix(" luồng")


def build_general_tab(dialog: SettingsDialog) -> QWidget:
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    appearance = QGroupBox("Giao diện và Ngôn ngữ", page)
    form = QFormLayout(appearance)
    form.addRow("Chủ đề màu sắc:", dialog.theme_combo)
    form.addRow("Ngôn ngữ hiển thị:", dialog.language_combo)
    behavior = QGroupBox("Hành vi hệ thống", page)
    vbox = QVBoxLayout(behavior)
    vbox.addWidget(dialog.restore_session_check)
    vbox.addWidget(dialog.confirm_delete_check)
    layout.addWidget(appearance)
    layout.addWidget(behavior)
    layout.addStretch(1)
    return page


def build_viewing_tab(dialog: SettingsDialog) -> QWidget:
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    display = QGroupBox("Chế độ xem tài liệu PDF", page)
    form = QFormLayout(display)
    form.addRow("Thu phóng mặc định:", dialog.zoom_mode_combo)
    form.addRow("Chế độ màu trang đọc:", dialog.color_mode_combo)
    form.addRow("Bộ nhớ đệm kết xuất:", dialog.cache_pages_spin)
    nav = QGroupBox("Điều hướng và Hiển thị trang", page)
    vbox = QVBoxLayout(nav)
    vbox.addWidget(dialog.thumbnails_check)
    layout.addWidget(display)
    layout.addWidget(nav)
    layout.addStretch(1)
    return page


def build_ocr_tab(dialog: SettingsDialog) -> QWidget:
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    rec = QGroupBox("Thông số nhận dạng OCR mặc định", page)
    form = QFormLayout(rec)
    form.addRow("Mô hình OCR mặc định:", dialog.default_engine_combo)
    form.addRow("Độ phân giải quét (DPI):", dialog.default_dpi_spin)
    form.addRow("", dialog.auto_ocr_check)
    pre = QGroupBox("Tiền xử lý ảnh tài liệu mặc định", page)
    vbox = QVBoxLayout(pre)
    vbox.addWidget(dialog.deskew_check)
    vbox.addWidget(dialog.denoise_check)
    vbox.addWidget(dialog.binarize_check)
    layout.addWidget(rec)
    layout.addWidget(pre)
    layout.addStretch(1)
    return page


def build_dictionary_tab(dialog: SettingsDialog) -> QWidget:
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    spell = QGroupBox("Kiểm tra chính tả và Độ tin cậy", page)
    form = QFormLayout(spell)
    form.addRow("", dialog.spell_correction_check)
    form.addRow("Ngưỡng cảnh báo từ độ tin cậy thấp:", dialog.confidence_spin)
    user_dict = QGroupBox("Từ điển người dùng (Bỏ qua khi sửa lỗi chính tả)", page)
    vbox = QVBoxLayout(user_dict)
    vbox.addWidget(dialog.custom_dict_edit)
    layout.addWidget(spell)
    layout.addWidget(user_dict)
    layout.addStretch(1)
    return page


def build_export_tab(dialog: SettingsDialog, folders_group: QGroupBox) -> QWidget:
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    out_group = QGroupBox("Định dạng xuất và Tối ưu hóa PDF", page)
    form = QFormLayout(out_group)
    form.addRow("Định dạng xuất mặc định:", dialog.export_format_combo)
    form.addRow("Mức nén tệp PDF:", dialog.compression_combo)
    layout.addWidget(out_group)
    layout.addWidget(folders_group)
    layout.addStretch(1)
    return page


def build_performance_tab(dialog: SettingsDialog, storage_group: QGroupBox) -> QWidget:
    page = QWidget(dialog)
    layout = QVBoxLayout(page)
    execution = QGroupBox("Thiết bị phần cứng và Đa luồng", page)
    form = QFormLayout(execution)
    form.addRow("Thiết bị thực thi AI:", dialog.device_combo)
    form.addRow("Số luồng xử lý song song:", dialog.worker_threads_spin)
    hint_row = QHBoxLayout()
    hint_row.addWidget(dialog.device_hint)
    form.addRow("", hint_row)
    layout.addWidget(execution)
    layout.addWidget(storage_group)
    layout.addStretch(1)
    return page

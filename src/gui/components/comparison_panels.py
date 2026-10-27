"""Layout and panel builders for ComparisonDock to keep view code modular."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.flow_layout import FlowLayout

_REGION_RESULT_MAX_HEIGHT = 140


def group_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("nav_group_label")
    return label


def separator(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("nav_separator")
    line.setFrameShape(QFrame.Shape.VLine)
    return line


def make_btn(text: str, name: str, tip: str, parent: QWidget) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setObjectName(name)
    btn.setToolTip(tip)
    return btn


def build_transcript_bar(parent: QWidget) -> tuple[QFrame, dict[str, Any]]:
    bar = QFrame(parent)
    bar.setObjectName("transcript_bar")
    title = QLabel("Văn bản nhận diện", bar)
    title.setObjectName("transcript_title_label")
    word_count = QLabel("0 từ · 0 ký tự", bar)
    word_count.setObjectName("word_count_label")
    spell_btn = make_btn(
        "Sửa chính tả",
        "spell_fix_button",
        "Sửa lỗi dấu thanh và từ ghép tiếng Việt theo ngữ cảnh (hỗ trợ Ctrl+Z)",
        bar,
    )
    find_btn = make_btn(
        "Tìm && Thay thế",
        "find_replace_button",
        "Mở hộp thoại Tìm và thay thế (Ctrl+H)",
        bar,
    )
    copy_btn = make_btn(
        "Sao chép",
        "copy_transcript_button",
        "Sao chép toàn bộ văn bản trang hiện tại",
        bar,
    )
    # Wraps onto a second row in a narrow pane instead of widening the window.
    layout = FlowLayout(bar, spacing=6)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.addWidget(title)
    layout.addWidget(word_count)
    layout.addWidget(spell_btn)
    layout.addWidget(find_btn)
    layout.addWidget(copy_btn)
    return bar, {
        "title": title,
        "word_count": word_count,
        "spell_btn": spell_btn,
        "find_btn": find_btn,
        "copy_btn": copy_btn,
    }


def build_region_panel(parent: QWidget) -> tuple[QFrame, dict[str, Any]]:
    panel = QFrame(parent)
    panel.setObjectName("region_panel")
    title = QLabel("Kết quả vùng chọn", panel)
    title.setObjectName("region_title")
    copy_btn = make_btn("Sao chép", "region_copy", "", panel)
    insert_btn = make_btn(
        "Chèn vào bản chép",
        "region_insert",
        "Chèn kết quả vùng chọn vào bản chép",
        panel,
    )
    rerun_btn = make_btn(
        "OCR bằng mô hình",
        "region_rerun",
        "Nhận diện lại vùng này bằng mô hình",
        panel,
    )
    source_label = QLabel("", panel)
    source_label.setObjectName("region_source")
    source_label.setWordWrap(True)
    editor = QPlainTextEdit(panel)
    editor.setObjectName("region_result")
    editor.setReadOnly(True)
    editor.setMaximumHeight(_REGION_RESULT_MAX_HEIGHT)
    header = QHBoxLayout()
    header.addWidget(title)
    header.addStretch(1)
    header.addWidget(rerun_btn)
    header.addWidget(insert_btn)
    header.addWidget(copy_btn)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 10, 12, 12)
    layout.addLayout(header)
    layout.addWidget(source_label)
    layout.addWidget(editor)
    panel.hide()
    return panel, {
        "title": title,
        "copy_btn": copy_btn,
        "insert_btn": insert_btn,
        "rerun_btn": rerun_btn,
        "source_label": source_label,
        "editor": editor,
    }


def build_structure_panel(parent: QWidget) -> tuple[QFrame, dict[str, Any]]:
    panel = QFrame(parent)
    panel.setObjectName("structure_panel")
    summary = QLabel(panel)
    summary.setObjectName("structure_summary")
    summary.setWordWrap(True)
    prev_btn = make_btn(
        "◀ Từ nghi ngờ",
        "uncertain_prev_button",
        "Đi tới từ có độ tin cậy thấp phía trước",
        panel,
    )
    next_btn = make_btn(
        "Từ nghi ngờ ▶",
        "uncertain_next_button",
        "Đi tới từ có độ tin cậy thấp tiếp theo",
        panel,
    )
    table_combo = QComboBox(panel)
    table_combo.setObjectName("table_combo")
    table_combo.setToolTip("Chọn bảng biểu để xem trên trang")
    edit_btn = make_btn(
        "Chỉnh sửa bảng…",
        "edit_table_button",
        "Sửa từng ô của bảng trước khi xuất ra Excel/Word",
        panel,
    )
    actions = QHBoxLayout()
    actions.setContentsMargins(0, 0, 0, 0)
    actions.setSpacing(6)
    actions.addWidget(prev_btn)
    actions.addWidget(next_btn)
    actions.addStretch(1)
    actions.addWidget(table_combo)
    actions.addWidget(edit_btn)
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(10, 6, 10, 6)
    layout.setSpacing(4)
    layout.addWidget(summary)
    layout.addLayout(actions)
    panel.hide()
    return panel, {
        "summary": summary,
        "prev_btn": prev_btn,
        "next_btn": next_btn,
        "table_combo": table_combo,
        "edit_btn": edit_btn,
    }


def build_nav_bar(
    parent: QWidget, ctrls: dict[str, Any]
) -> tuple[QFrame, dict[str, Any]]:
    nav_bar = QFrame(parent)
    nav_bar.setObjectName("nav_bar")
    layout = QVBoxLayout(nav_bar)
    layout.setContentsMargins(8, 4, 8, 4)
    layout.setSpacing(4)
    # Wraps instead of forcing the page pane, and the window, wider.
    zoom_row = FlowLayout(spacing=6)
    zoom_row.addWidget(group_label("Thu phóng", nav_bar))
    zoom_row.addWidget(ctrls["zoom_out"])
    zoom_row.addWidget(ctrls["zoom_label"])
    zoom_row.addWidget(ctrls["zoom_in"])
    zoom_row.addWidget(ctrls["zoom_reset"])
    zoom_row.addWidget(ctrls["fit_width"])
    zoom_row.addWidget(separator(nav_bar))
    zoom_row.addWidget(ctrls["rotate_left"])
    zoom_row.addWidget(ctrls["rotate_right"])
    page_row = QHBoxLayout()
    page_row.setContentsMargins(0, 0, 0, 0)
    page_row.setSpacing(6)
    page_row.addWidget(group_label("Trang", nav_bar))
    page_row.addWidget(ctrls["prev_page"])
    page_row.addWidget(ctrls["page_spin"])
    page_row.addWidget(ctrls["next_page"])
    page_row.addWidget(ctrls["page_slider"], 1)
    page_row.addWidget(ctrls["page_label"])
    layout.addLayout(zoom_row)
    layout.addLayout(page_row)
    return nav_bar, ctrls

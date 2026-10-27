"""Adobe Acrobat-style Document Properties dialog for PDF and image documents."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.pdf_editor import PDFProperties, inspect_pdf_properties
from src.gui.components.sizing import fit_to_contents
from src.gui.i18n import localise_buttons
from src.utils.logger import logger


def _format_bytes(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 B"
    kb = size_bytes / 1024.0
    if kb < 1024.0:
        return f"{kb:.1f} KB ({size_bytes:,} byte)"
    return f"{kb / 1024.0:.2f} MB ({size_bytes:,} byte)"


def _format_dimensions(width_pt: float, height_pt: float) -> str:
    if width_pt <= 0 or height_pt <= 0:
        return "Không xác định"
    w_mm = width_pt * 25.4 / 72.0
    h_mm = height_pt * 25.4 / 72.0
    return f"{w_mm:.1f} × {h_mm:.1f} mm ({width_pt:.0f} × {height_pt:.0f} pt)"


class DocumentPropertiesDialog(QDialog):
    """Display comprehensive PDF properties, metadata, security, and embedded fonts."""

    def __init__(self, file_path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("document_properties_dialog")
        self.setWindowTitle("Thuộc tính tài liệu (Document Properties)")
        self.setMinimumSize(560, 440)
        self._path = Path(file_path).resolve()
        self._props = self._inspect_safe(self._path)
        self.tabs = QTabWidget(self)
        self.page_count_value = QLabel(str(self._props.page_count), self)
        self.fonts_list = QListWidget(self)
        self._build_layout()
        fit_to_contents(self)

    @staticmethod
    def _inspect_safe(path: Path) -> PDFProperties:
        if path.suffix.lower() == ".pdf" and path.is_file():
            try:
                return inspect_pdf_properties(path)
            except Exception as err:
                logger.debug("Không đọc được thuộc tính PDF {}: {}", path, err)
        size = int(path.stat().st_size) if path.is_file() else 0
        return PDFProperties(
            path=str(path),
            pdf_version=f"Tệp ảnh ({path.suffix.upper().lstrip('.')})",
            page_count=1,
            page_width_pt=0.0,
            page_height_pt=0.0,
            file_size_bytes=size,
            is_encrypted=False,
            metadata={},
            fonts=(),
            bookmarks_count=0,
        )

    def _build_layout(self) -> None:
        self.tabs.addTab(self._build_summary_tab(), "Tổng quan và Siêu dữ liệu")
        self.tabs.addTab(
            self._build_fonts_tab(), f"Phông chữ ({len(self._props.fonts)})"
        )
        buttons = localise_buttons(
            QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        )
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(buttons)

    def _build_summary_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        general = QGroupBox("Thông tin tệp và Cấu trúc PDF", page)
        g_form = QFormLayout(general)
        path_lbl = QLabel(self._props.path, general)
        path_lbl.setWordWrap(True)
        g_form.addRow("Đường dẫn tệp:", path_lbl)
        g_form.addRow("Phiên bản định dạng:", QLabel(self._props.pdf_version, general))
        g_form.addRow("Tổng số trang:", self.page_count_value)
        g_form.addRow(
            "Kích thước trang:",
            QLabel(
                _format_dimensions(
                    self._props.page_width_pt, self._props.page_height_pt
                ),
                general,
            ),
        )
        g_form.addRow(
            "Dung lượng tệp:",
            QLabel(_format_bytes(self._props.file_size_bytes), general),
        )
        security_text = (
            "Đã mã hóa mật khẩu (AES)"
            if self._props.is_encrypted
            else "Không khóa mật khẩu"
        )
        g_form.addRow("Bảo mật:", QLabel(security_text, general))
        g_form.addRow(
            "Số mục lục (Bookmarks):",
            QLabel(str(self._props.bookmarks_count), general),
        )

        meta_group = QGroupBox("Siêu dữ liệu (Metadata)", page)
        m_form = QFormLayout(meta_group)
        meta = self._props.metadata
        for label, key in (
            ("Tiêu đề (Title):", "title"),
            ("Tác giả (Author):", "author"),
            ("Chủ đề (Subject):", "subject"),
            ("Từ khóa (Keywords):", "keywords"),
            ("Phần mềm tạo:", "creator"),
        ):
            m_form.addRow(label, QLabel(meta.get(key) or "—", meta_group))
        layout.addWidget(general)
        layout.addWidget(meta_group)
        layout.addStretch(1)
        return page

    def _build_fonts_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        group = QGroupBox("Danh sách phông chữ nhúng trong tài liệu", page)
        vbox = QVBoxLayout(group)
        if self._props.fonts:
            for font_name in self._props.fonts:
                self.fonts_list.addItem(font_name)
        else:
            self.fonts_list.addItem("(Không có phông chữ nhúng — tài liệu dạng ảnh)")
        vbox.addWidget(self.fonts_list)
        layout.addWidget(group)
        return page

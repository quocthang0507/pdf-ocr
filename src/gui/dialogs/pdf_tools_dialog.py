"""Unified PDF editing suite dialog: pages, annotations, metadata, and security."""

from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.pdf_editor import (
    add_highlight_annotation,
    add_stamp_image,
    add_text_note_annotation,
    compress_pdf,
    delete_pages_from_pdf,
    extract_pages_to_pdf,
    inspect_pdf_properties,
    merge_pdfs,
    protect_pdf_with_password,
    redact_region_in_pdf,
    reorder_pages_in_pdf,
    rotate_pages_in_pdf,
    update_pdf_bookmarks,
    update_pdf_metadata,
)
from src.gui.components.sizing import fit_to_contents
from src.gui.i18n import localise_buttons


def parse_page_range(spec: str, max_page: int) -> list[int]:
    """Parse '1, 3-5' into sorted unique 1-based page numbers within 1..max_page."""
    result: list[int] = []
    for part in spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            left_s, right_s = token.split("-", 1)
            start = max(1, min(max_page, int(left_s.strip())))
            end = max(1, min(max_page, int(right_s.strip())))
            step = 1 if end >= start else -1
            for num in range(start, end + step, step):
                if num not in result:
                    result.append(num)
        else:
            num = max(1, min(max_page, int(token)))
            if num not in result:
                result.append(num)
    if not result:
        raise ValueError("Vui lòng nhập ít nhất một số trang hợp lệ.")
    return result


def _parse_bookmarks_text(text: str) -> list[tuple[int, str, int]]:
    items: list[tuple[int, str, int]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3:
            items.append((max(1, int(parts[0])), parts[1], max(1, int(parts[2]))))
        elif len(parts) == 2:
            items.append((1, parts[0], max(1, int(parts[1]))))
    return items


class PDFToolsDialog(QDialog):
    """Comprehensive PDF Editing Suite modeled after Acrobat & ABBYY FineReader."""

    pdf_modified = Signal(str)

    def __init__(
        self,
        pdf_path: str | Path,
        *,
        current_page: int = 1,
        selection_norm: tuple[float, float, float, float] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pdf_tools_dialog")
        self.setWindowTitle("Bộ công cụ chỉnh sửa & bảo mật PDF")
        self.setMinimumSize(660, 520)
        self._path = Path(pdf_path).resolve()
        self._current_page = max(1, current_page)
        self._selection = selection_norm or (0.10, 0.10, 0.60, 0.22)
        self.tabs = QTabWidget(self)
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("pdf_tools_status")
        self._init_page_controls()
        self._init_annot_controls()
        self._init_meta_controls()
        self._init_security_controls()
        self._build_layout()
        self._load_document_state()
        self._connect_signals()
        fit_to_contents(self)

    def _init_page_controls(self) -> None:
        self.pages_range_edit = QLineEdit(str(self._current_page), self)
        self.pages_range_edit.setPlaceholderText("Ví dụ: 1, 3-5")
        self.rotate_left_btn = QPushButton("↺ Xoay trái 90° && Lưu", self)
        self.rotate_right_btn = QPushButton("↻ Xoay phải 90° && Lưu", self)
        self.delete_pages_btn = QPushButton("Xóa trang chọn", self)
        self.extract_pages_btn = QPushButton("Trích xuất PDF…", self)
        self.merge_pdfs_btn = QPushButton("Ghép thêm PDF…", self)
        self.reorder_edit = QLineEdit(self)
        self.reorder_edit.setPlaceholderText("Thứ tự trang mới, ví dụ: 2, 1, 3")
        self.reorder_btn = QPushButton("Áp dụng thứ tự trang", self)

    def _init_annot_controls(self) -> None:
        x0, y0, x1, y1 = self._selection
        self.rect_x0_spin = _norm_spin(self, x0)
        self.rect_y0_spin = _norm_spin(self, y0)
        self.rect_x1_spin = _norm_spin(self, x1)
        self.rect_y1_spin = _norm_spin(self, y1)
        self.highlight_btn = QPushButton("🖍 Tô sáng vùng chọn (Highlight)", self)
        self.note_text_edit = QLineEdit(self)
        self.note_text_edit.setPlaceholderText(
            "Nội dung ghi chú đính kèm trên trang..."
        )
        self.add_note_btn = QPushButton("📌 Gắn ghi chú (Sticky Note)", self)
        self.stamp_path_edit = QLineEdit(self)
        self.stamp_path_edit.setPlaceholderText(
            "Đường dẫn ảnh chữ ký / con dấu (.png/.jpg)..."
        )
        self.browse_stamp_btn = QPushButton("Chọn ảnh…", self)
        self.apply_stamp_btn = QPushButton(
            "✒ Chèn chữ ký / con dấu vào vùng chọn", self
        )
        self.redact_btn = QPushButton(
            "⬛ Che mật vĩnh viễn vùng chọn (Redaction)", self
        )

    def _init_meta_controls(self) -> None:
        self.title_edit = QLineEdit(self)
        self.author_edit = QLineEdit(self)
        self.subject_edit = QLineEdit(self)
        self.keywords_edit = QLineEdit(self)
        self.save_metadata_btn = QPushButton("Lưu siêu dữ liệu PDF", self)
        self.bookmarks_edit = QPlainTextEdit(self)
        self.bookmarks_edit.setPlaceholderText(
            "Mỗi dòng một mục lục theo cú pháp: Cấp | Tiêu đề | Trang\n"
            "Ví dụ:\n1 | Chương 1: Mở đầu | 1\n2 | Mục 1.1 | 2"
        )
        self.save_bookmarks_btn = QPushButton("Lưu mục lục (Bookmarks)", self)

    def _init_security_controls(self) -> None:
        self.user_password_edit = QLineEdit(self)
        self.user_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.user_password_edit.setPlaceholderText("Mật khẩu mở tệp (User Password)")
        self.owner_password_edit = QLineEdit(self)
        self.owner_password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.owner_password_edit.setPlaceholderText(
            "Mật khẩu quyền quản trị (Tùy chọn)"
        )
        self.encrypt_btn = QPushButton("🔒 Xuất bản PDF khóa mật khẩu AES-256…", self)
        self.compression_level_combo = QComboBox(self)
        self.compression_level_combo.addItem("Nhanh (Fast)", "fast")
        self.compression_level_combo.addItem("Cân bằng (Balanced)", "balanced")
        self.compression_level_combo.addItem("Tối đa (Max Compression)", "max")
        self.compression_level_combo.setCurrentIndex(1)
        self.compress_btn = QPushButton("🗜 Tối ưu hóa & Nén dung lượng PDF ngay", self)

    def _build_layout(self) -> None:
        self.tabs.addTab(self._build_pages_tab(), "Quản lý trang")
        self.tabs.addTab(self._build_annot_tab(), "Chú thích và Bảo mật vùng")
        self.tabs.addTab(self._build_meta_tab(), "Siêu dữ liệu và Mục lục")
        self.tabs.addTab(self._build_security_tab(), "Mật khẩu và Nén PDF")
        buttons = localise_buttons(
            QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        )
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        footer = QHBoxLayout()
        footer.addWidget(self.status_label, 1)
        footer.addWidget(buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(footer)

    def _build_pages_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        ops = QGroupBox("Xoay, Xóa, Trích xuất và Ghép trang PDF", page)
        form = QFormLayout(ops)
        form.addRow("Trang áp dụng (1, 3-5):", self.pages_range_edit)
        rot_row = QHBoxLayout()
        rot_row.addWidget(self.rotate_left_btn)
        rot_row.addWidget(self.rotate_right_btn)
        form.addRow("Xoay vĩnh viễn:", rot_row)
        act_row = QHBoxLayout()
        act_row.addWidget(self.delete_pages_btn)
        act_row.addWidget(self.extract_pages_btn)
        act_row.addWidget(self.merge_pdfs_btn)
        form.addRow("Thao tác trang:", act_row)
        order_group = QGroupBox("Sắp xếp lại thứ tự toàn bộ trang", page)
        o_form = QFormLayout(order_group)
        o_form.addRow("Chuỗi thứ tự mới:", self.reorder_edit)
        o_form.addRow("", self.reorder_btn)
        layout.addWidget(ops)
        layout.addWidget(order_group)
        layout.addStretch(1)
        return page

    def _build_annot_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        coords = QGroupBox(
            f"Tọa độ vùng chọn trên Trang {self._current_page} (Tỉ lệ 0.00..1.00)", page
        )
        c_row = QHBoxLayout(coords)
        for lbl, spin in (
            ("X0:", self.rect_x0_spin),
            ("Y0:", self.rect_y0_spin),
            ("X1:", self.rect_x1_spin),
            ("Y1:", self.rect_y1_spin),
        ):
            c_row.addWidget(QLabel(lbl, coords))
            c_row.addWidget(spin)
        markup = QGroupBox("Đánh dấu, Ghi chú, Chữ ký và Che mật (Redaction)", page)
        form = QFormLayout(markup)
        form.addRow("Tô sáng văn bản:", self.highlight_btn)
        note_row = QHBoxLayout()
        note_row.addWidget(self.note_text_edit, 1)
        note_row.addWidget(self.add_note_btn)
        form.addRow("Ghi chú đính kèm:", note_row)
        stamp_row = QHBoxLayout()
        stamp_row.addWidget(self.stamp_path_edit, 1)
        stamp_row.addWidget(self.browse_stamp_btn)
        form.addRow("Tệp ảnh chữ ký:", stamp_row)
        form.addRow("", self.apply_stamp_btn)
        form.addRow("Bảo mật thông tin:", self.redact_btn)
        layout.addWidget(coords)
        layout.addWidget(markup)
        layout.addStretch(1)
        return page

    def _build_meta_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        meta = QGroupBox("Siêu dữ liệu chuẩn PDF (Metadata)", page)
        form = QFormLayout(meta)
        form.addRow("Tiêu đề (Title):", self.title_edit)
        form.addRow("Tác giả (Author):", self.author_edit)
        form.addRow("Chủ đề (Subject):", self.subject_edit)
        form.addRow("Từ khóa (Keywords):", self.keywords_edit)
        form.addRow("", self.save_metadata_btn)
        toc = QGroupBox("Mục lục tài liệu (Bookmarks / Outline)", page)
        vbox = QVBoxLayout(toc)
        vbox.addWidget(self.bookmarks_edit, 1)
        vbox.addWidget(self.save_bookmarks_btn)
        layout.addWidget(meta)
        layout.addWidget(toc, 1)
        return page

    def _build_security_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        sec = QGroupBox("Mã hóa và Bảo vệ bằng mật khẩu (AES-256)", page)
        s_form = QFormLayout(sec)
        s_form.addRow("Mật khẩu mở tệp:", self.user_password_edit)
        s_form.addRow("Mật khẩu quản trị:", self.owner_password_edit)
        s_form.addRow("", self.encrypt_btn)
        comp = QGroupBox("Tối ưu hóa và Nén dung lượng PDF", page)
        c_form = QFormLayout(comp)
        c_form.addRow("Mức độ nén:", self.compression_level_combo)
        c_form.addRow("", self.compress_btn)
        layout.addWidget(sec)
        layout.addWidget(comp)
        layout.addStretch(1)
        return page

    def _connect_signals(self) -> None:
        self.rotate_left_btn.clicked.connect(lambda: self._run_rotate(-90))
        self.rotate_right_btn.clicked.connect(lambda: self._run_rotate(90))
        self.delete_pages_btn.clicked.connect(self._run_delete)
        self.extract_pages_btn.clicked.connect(self._run_extract)
        self.merge_pdfs_btn.clicked.connect(self._run_merge)
        self.reorder_btn.clicked.connect(self._run_reorder)
        self.highlight_btn.clicked.connect(self._run_highlight)
        self.add_note_btn.clicked.connect(self._run_add_note)
        self.browse_stamp_btn.clicked.connect(self._browse_stamp)
        self.apply_stamp_btn.clicked.connect(self._run_stamp)
        self.redact_btn.clicked.connect(self._run_redact)
        self.save_metadata_btn.clicked.connect(self._run_save_metadata)
        self.save_bookmarks_btn.clicked.connect(self._run_save_bookmarks)
        self.encrypt_btn.clicked.connect(self._run_encrypt)
        self.compress_btn.clicked.connect(self._run_compress)

    def _load_document_state(self) -> None:
        props = inspect_pdf_properties(self._path)
        self._page_count = max(1, props.page_count)
        self.reorder_edit.setText(
            ", ".join(str(i) for i in range(1, self._page_count + 1))
        )
        self.title_edit.setText(props.metadata.get("title", ""))
        self.author_edit.setText(props.metadata.get("author", ""))
        self.subject_edit.setText(props.metadata.get("subject", ""))
        self.keywords_edit.setText(props.metadata.get("keywords", ""))
        with pymupdf.open(str(self._path)) as doc:
            toc = doc.get_toc(simple=True)
        lines = [f"{item[0]} | {item[1]} | {item[2]}" for item in toc if len(item) >= 3]
        self.bookmarks_edit.setPlainText("\n".join(lines))

    def _selected_pages(self) -> list[int]:
        return parse_page_range(self.pages_range_edit.text(), self._page_count)

    def _current_rect_norm(self) -> tuple[float, float, float, float]:
        return (
            float(self.rect_x0_spin.value()),
            float(self.rect_y0_spin.value()),
            float(self.rect_x1_spin.value()),
            float(self.rect_y1_spin.value()),
        )

    def _notify_modified(self, message: str) -> None:
        self._load_document_state()
        self.status_label.setText(message)
        self.pdf_modified.emit(str(self._path))

    # -- action handlers --------------------------------------------------

    def _run_rotate(self, delta: int) -> None:
        try:
            pages = self._selected_pages()
            rotate_pages_in_pdf(self._path, pages, delta)
            self._notify_modified(f"Đã xoay {len(pages)} trang ({delta:+d}°).")
        except Exception as err:
            QMessageBox.warning(self, "Xoay trang", str(err))

    def _run_delete(self) -> None:
        try:
            pages = self._selected_pages()
            delete_pages_from_pdf(self._path, pages)
            self._notify_modified(f"Đã xóa {len(pages)} trang khỏi tài liệu.")
        except Exception as err:
            QMessageBox.warning(self, "Xóa trang", str(err))

    def _run_extract(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Trích xuất trang ra tệp PDF",
            str(self._path.with_stem(f"{self._path.stem}_extracted")),
            "PDF (*.pdf)",
        )
        if not target:
            return
        try:
            pages = self._selected_pages()
            out = extract_pages_to_pdf(self._path, pages, target)
            self.status_label.setText(f"Đã trích xuất ra {out.name}.")
        except Exception as err:
            QMessageBox.warning(self, "Trích xuất trang", str(err))

    def _run_merge(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Chọn các tệp PDF cần ghép nối vào cuối tài liệu",
            str(self._path.parent),
            "PDF (*.pdf)",
        )
        if not files:
            return
        try:
            merge_pdfs([self._path, *files], self._path)
            self._notify_modified(f"Đã ghép thêm {len(files)} tệp PDF.")
        except Exception as err:
            QMessageBox.warning(self, "Ghép PDF", str(err))

    def _run_reorder(self) -> None:
        try:
            order = [
                int(x.strip()) for x in self.reorder_edit.text().split(",") if x.strip()
            ]
            reorder_pages_in_pdf(self._path, order)
            self._notify_modified("Đã cập nhật thứ tự trang PDF.")
        except Exception as err:
            QMessageBox.warning(self, "Sắp xếp trang", str(err))

    def _run_highlight(self) -> None:
        try:
            add_highlight_annotation(
                self._path, self._current_page, self._current_rect_norm()
            )
            self._notify_modified(
                f"Đã tô sáng vùng chọn trên trang {self._current_page}."
            )
        except Exception as err:
            QMessageBox.warning(self, "Tô sáng", str(err))

    def _run_add_note(self) -> None:
        try:
            rect = self._current_rect_norm()
            text = self.note_text_edit.text().strip() or "Ghi chú"
            add_text_note_annotation(
                self._path, self._current_page, (rect[0], rect[1]), text
            )
            self._notify_modified(f"Đã gắn ghi chú trên trang {self._current_page}.")
        except Exception as err:
            QMessageBox.warning(self, "Gắn ghi chú", str(err))

    def _browse_stamp(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn ảnh chữ ký hoặc con dấu",
            str(Path.home()),
            "Ảnh (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if selected:
            self.stamp_path_edit.setText(selected)

    def _run_stamp(self) -> None:
        try:
            add_stamp_image(
                self._path,
                self._current_page,
                self._current_rect_norm(),
                self.stamp_path_edit.text().strip(),
            )
            self._notify_modified(
                f"Đã chèn chữ ký/con dấu vào trang {self._current_page}."
            )
        except Exception as err:
            QMessageBox.warning(self, "Chèn chữ ký/con dấu", str(err))

    def _run_redact(self) -> None:
        try:
            redact_region_in_pdf(
                self._path, self._current_page, self._current_rect_norm()
            )
            self._notify_modified(
                f"Đã che mật vĩnh viễn vùng chọn trên trang {self._current_page}."
            )
        except Exception as err:
            QMessageBox.warning(self, "Che mật (Redaction)", str(err))

    def _run_save_metadata(self) -> None:
        try:
            update_pdf_metadata(
                self._path,
                {
                    "title": self.title_edit.text(),
                    "author": self.author_edit.text(),
                    "subject": self.subject_edit.text(),
                    "keywords": self.keywords_edit.text(),
                },
            )
            self._notify_modified("Đã lưu siêu dữ liệu PDF.")
        except Exception as err:
            QMessageBox.warning(self, "Siêu dữ liệu", str(err))

    def _run_save_bookmarks(self) -> None:
        try:
            bookmarks = _parse_bookmarks_text(self.bookmarks_edit.toPlainText())
            update_pdf_bookmarks(self._path, bookmarks)
            self._notify_modified(f"Đã cập nhật {len(bookmarks)} mục lục PDF.")
        except Exception as err:
            QMessageBox.warning(self, "Mục lục PDF", str(err))

    def _run_encrypt(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu bản PDF bảo vệ bằng mật khẩu",
            str(self._path.with_stem(f"{self._path.stem}_protected")),
            "PDF (*.pdf)",
        )
        if not target:
            return
        try:
            out = protect_pdf_with_password(
                self._path,
                self.user_password_edit.text(),
                self.owner_password_edit.text() or None,
                output_path=target,
            )
            self.status_label.setText(f"Đã xuất PDF mã hóa: {out.name}")
        except Exception as err:
            QMessageBox.warning(self, "Mã hóa PDF", str(err))

    def _run_compress(self) -> None:
        try:
            before_kb = self._path.stat().st_size / 1024.0
            level = str(self.compression_level_combo.currentData() or "balanced")
            compress_pdf(self._path, level=level)
            after_kb = self._path.stat().st_size / 1024.0
            self._notify_modified(
                f"Đã nén PDF: {before_kb:.1f} KB → {after_kb:.1f} KB."
            )
        except Exception as err:
            QMessageBox.warning(self, "Nén PDF", str(err))


def _norm_spin(parent: QWidget, value: float) -> QDoubleSpinBox:
    spin = QDoubleSpinBox(parent)
    spin.setRange(0.0, 1.0)
    spin.setSingleStep(0.05)
    spin.setDecimals(2)
    spin.setValue(max(0.0, min(1.0, value)))
    return spin

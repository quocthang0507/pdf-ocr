"""Left workspace navigation dock: File Info Card, Thumbnails, Outline, and Search."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.document_session import DocumentSession
from src.utils.logger import logger

_MAX_EAGER_THUMBNAILS = 40


def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 KB"
    kb = size_bytes / 1024.0
    if kb < 1024.0:
        return f"{kb:.1f} KB"
    return f"{kb / 1024.0:.2f} MB"


def _ndarray_to_icon(image: np.ndarray) -> QIcon:
    rgb = np.ascontiguousarray(image, dtype=np.uint8)
    h, w = rgb.shape[:2]
    channels = rgb.shape[2] if rgb.ndim == 3 else 1
    fmt = (
        QImage.Format.Format_RGB888
        if channels == 3
        else QImage.Format.Format_Grayscale8
    )
    raw_bytes = rgb.tobytes()
    qimg = QImage(raw_bytes, w, h, w * channels, fmt).copy()
    return QIcon(QPixmap.fromImage(qimg))


class NavigationDock(QWidget):
    """Left workspace sidebar for file info, thumbnails, PDF outline, and search."""

    page_selected = Signal(int)
    ocr_page_requested = Signal(int)
    page_context_action = Signal(str, int)
    pdf_tools_requested = Signal()
    document_properties_requested = Signal()
    reading_mode_changed = Signal(str)
    search_result_selected = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigation_dock")
        self.setMinimumWidth(235)
        self._session: DocumentSession | None = None
        self._show_thumbnails = True
        self._thumbnail_cache: dict[tuple[int, int, str], QIcon] = {}
        self._init_file_card()

        self._init_tabs()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self.file_card)
        layout.addWidget(self.tabs, 1)

    def _init_file_card(self) -> None:
        self.file_card = QFrame(self)
        self.file_card.setObjectName("file_info_card")
        self.file_name_label = QLabel("Chưa mở tài liệu", self.file_card)
        self.file_name_label.setObjectName("file_name_label")
        self.file_name_label.setWordWrap(True)
        self.file_meta_label = QLabel("0 trang · 0 KB", self.file_card)
        self.file_meta_label.setObjectName("file_meta_label")
        self.ocr_progress_label = QLabel("Đã OCR: 0 / 0 trang", self.file_card)
        self.ocr_progress_label.setObjectName("ocr_progress_label")
        self.ocr_progress_bar = QProgressBar(self.file_card)
        self.ocr_progress_bar.setObjectName("ocr_progress_bar")
        self.ocr_progress_bar.setRange(0, 1)
        self.ocr_progress_bar.setValue(0)
        self.ocr_progress_bar.setTextVisible(False)
        self.ocr_current_page_btn = QPushButton("OCR trang hiện tại", self.file_card)
        self.ocr_current_page_btn.setObjectName("ocr_current_page_button")
        self.ocr_current_page_btn.setToolTip(
            "Nhận diện ngay trang đang xem bằng mô hình đã chọn"
        )
        self.ocr_current_page_btn.setEnabled(False)
        self.ocr_current_page_btn.clicked.connect(self._request_current_page_ocr)
        self._init_pdf_quick_controls()
        self._assemble_file_card_layout()

    def _init_pdf_quick_controls(self) -> None:
        self.pdf_tools_btn = QPushButton("Sửa PDF…", self.file_card)
        self.pdf_tools_btn.setObjectName("pdf_tools_quick_button")
        self.pdf_tools_btn.setToolTip(
            "Mở bộ công cụ chỉnh sửa trang, chú thích, đóng dấu và nén PDF (Ctrl+E)"
        )
        self.pdf_tools_btn.setEnabled(False)
        self.pdf_tools_btn.clicked.connect(self.pdf_tools_requested.emit)
        self.doc_props_btn = QPushButton("Thuộc tính…", self.file_card)
        self.doc_props_btn.setObjectName("doc_props_quick_button")
        self.doc_props_btn.setToolTip(
            "Xem thuộc tính tài liệu, siêu dữ liệu và phông chữ (Ctrl+D)"
        )
        self.doc_props_btn.setEnabled(False)
        self.doc_props_btn.clicked.connect(self.document_properties_requested.emit)
        self.reading_mode_combo = QComboBox(self.file_card)
        self.reading_mode_combo.setObjectName("reading_mode_combo")
        self.reading_mode_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.reading_mode_combo.addItem("Màu đọc: Bình thường", "normal")
        self.reading_mode_combo.addItem("Màu đọc: Giấy vàng (Sepia)", "sepia")
        self.reading_mode_combo.addItem("Màu đọc: Ban đêm", "night")
        self.reading_mode_combo.currentIndexChanged.connect(
            self._on_reading_mode_changed
        )

    def _assemble_file_card_layout(self) -> None:
        tools_row = QHBoxLayout()
        tools_row.setContentsMargins(0, 0, 0, 0)
        tools_row.setSpacing(4)
        tools_row.addWidget(self.pdf_tools_btn, 1)
        tools_row.addWidget(self.doc_props_btn, 1)
        card_layout = QVBoxLayout(self.file_card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(6)
        card_layout.addWidget(self.file_name_label)
        card_layout.addWidget(self.file_meta_label)
        card_layout.addWidget(self.ocr_progress_label)
        card_layout.addWidget(self.ocr_progress_bar)
        card_layout.addWidget(self.ocr_current_page_btn)
        card_layout.addLayout(tools_row)
        card_layout.addWidget(self.reading_mode_combo)

    def _init_tabs(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("navigation_tabs")
        self.page_list = QListWidget(self.tabs)
        self.page_list.setObjectName("page_status_list")
        self.page_list.setIconSize(QSize(34, 46))
        self.page_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.page_list.customContextMenuRequested.connect(self._show_page_context_menu)
        self.page_list.currentRowChanged.connect(self._on_page_row_changed)
        self.page_list.verticalScrollBar().valueChanged.connect(
            self._load_visible_thumbnails
        )
        self.outline_tree = QTreeWidget(self.tabs)

        self.outline_tree.setObjectName("outline_tree")
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.itemClicked.connect(self._on_outline_clicked)
        search_tab = self._build_search_tab()
        self.tabs.addTab(self.page_list, "Trang")
        self.tabs.addTab(self.outline_tree, "Mục lục")
        self.tabs.addTab(search_tab, "Tìm kiếm")

    def _build_search_tab(self) -> QWidget:
        pane = QWidget(self)
        self.search_input = QLineEdit(pane)
        self.search_input.setObjectName("doc_search_input")
        self.search_input.setPlaceholderText("Tìm trong toàn bộ tài liệu…")
        self.search_input.setClearButtonEnabled(True)
        self.search_btn = QPushButton("Tìm", pane)
        self.search_btn.setObjectName("doc_search_button")
        self.search_summary_label = QLabel("", pane)
        self.search_summary_label.setObjectName("doc_search_summary")
        self.search_results = QListWidget(pane)
        self.search_results.setObjectName("doc_search_results")
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.addWidget(self.search_input, 1)
        bar.addWidget(self.search_btn)
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(bar)
        layout.addWidget(self.search_summary_label)
        layout.addWidget(self.search_results, 1)
        self.search_input.textChanged.connect(self.run_search)
        self.search_input.returnPressed.connect(self.run_search)
        self.search_btn.clicked.connect(self.run_search)
        self.search_results.itemClicked.connect(self._on_search_item_clicked)
        return pane

    def set_thumbnails_enabled(self, enabled: bool) -> None:
        self._show_thumbnails = enabled
        if not enabled:
            self._thumbnail_cache.clear()
        self.page_list.blockSignals(True)
        self.page_list.clear()
        self.page_list.blockSignals(False)
        self.refresh_status()

    def set_session(self, session: DocumentSession | None) -> None:
        """Bind to an open document session and populate pages and outline."""
        self._session = session
        self._thumbnail_cache.clear()
        self.search_results.clear()

        self.search_summary_label.setText("")
        self.page_list.blockSignals(True)
        self.page_list.clear()
        self.page_list.blockSignals(False)
        if session is None:
            self.file_name_label.setText("Chưa mở tài liệu")
            self.file_meta_label.setText("0 trang · 0 KB")
            self.ocr_progress_label.setText("Đã OCR: 0 / 0 trang")
            self.ocr_progress_bar.setRange(0, 1)
            self.ocr_progress_bar.setValue(0)
            self.ocr_current_page_btn.setEnabled(False)
            self.pdf_tools_btn.setEnabled(False)
            self.doc_props_btn.setEnabled(False)
            self.outline_tree.clear()
            return
        self.ocr_current_page_btn.setEnabled(True)
        self.pdf_tools_btn.setEnabled(session.is_pdf)
        self.doc_props_btn.setEnabled(True)
        self._populate_outline(session)
        self.refresh_status()

    def refresh_status(self) -> None:
        """Update file metadata, OCR completion counter, and page badges."""
        session = self._session
        if session is None:
            return
        total = session.page_count
        recognised = len(session.recognised_pages())
        size_str = _format_size(session.file_size_bytes())
        self.file_name_label.setText(Path(session.path).name)
        self.file_meta_label.setText(f"{total} trang · {size_str}")
        self.ocr_progress_label.setText(f"Đã OCR: {recognised} / {total} trang")
        self.ocr_progress_bar.setRange(0, max(1, total))
        self.ocr_progress_bar.setValue(recognised)
        self._sync_page_list(session, total)

    def _sync_page_list(self, session: DocumentSession, total: int) -> None:
        self.page_list.blockSignals(True)
        while self.page_list.count() > total:
            self.page_list.takeItem(self.page_list.count() - 1)
        while self.page_list.count() < total:
            self.page_list.addItem(QListWidgetItem())
        for idx in range(total):
            number = idx + 1
            item = self.page_list.item(idx)
            if item is not None:
                item.setText(self._page_badge_text(session, number))
                item.setData(Qt.ItemDataRole.UserRole, number)
                if self._show_thumbnails and number <= _MAX_EAGER_THUMBNAILS:
                    self._attach_thumbnail(session, item, number)
        if 1 <= session.current_page <= total:
            self.page_list.setCurrentRow(session.current_page - 1)
        self.page_list.blockSignals(False)

    def _attach_thumbnail(
        self, session: DocumentSession, item: QListWidgetItem, page_number: int
    ) -> None:
        key = (
            page_number,
            session.page_rotation(page_number),
            session.page_color_mode,
        )

        cached = self._thumbnail_cache.get(key)
        if cached is not None:
            if item.icon().cacheKey() != cached.cacheKey():
                item.setIcon(cached)
            return
        try:
            thumb = session.thumbnail(page_number, max_side=56)
            icon = _ndarray_to_icon(thumb)
            self._thumbnail_cache[key] = icon
            item.setIcon(icon)
        except Exception as err:
            logger.debug("Không tạo được ảnh thu nhỏ trang {}: {}", page_number, err)

    def _load_visible_thumbnails(self, _value: int = 0) -> None:
        """Lazily render thumbnails for visible items beyond _MAX_EAGER_THUMBNAILS."""
        session = self._session
        if session is None or not self._show_thumbnails:
            return
        viewport = self.page_list.viewport().rect()
        top_item = self.page_list.itemAt(viewport.topLeft())
        bottom_item = self.page_list.itemAt(viewport.bottomLeft())
        start = self.page_list.row(top_item) if top_item is not None else 0
        end = (
            self.page_list.row(bottom_item)
            if bottom_item is not None
            else min(self.page_list.count() - 1, start + 25)
        )
        for row in range(max(0, start), min(self.page_list.count(), end + 1)):
            item = self.page_list.item(row)
            if item is not None and item.icon().isNull():
                self._attach_thumbnail(session, item, row + 1)

    @staticmethod
    def _page_badge_text(session: DocumentSession, page_number: int) -> str:
        result = session.result(page_number)
        if result is None:
            return f"○ Trang {page_number} — Chờ xử lý"
        low_conf = any(
            w.is_low_confidence
            for block in result.blocks
            for line in block.lines
            for w in line.words
        )
        if low_conf:
            return f"⚠ Trang {page_number} — Cần kiểm tra"
        return f"✓ Trang {page_number} — Đã OCR"

    def trigger_page_action(self, action_id: str, page_number: int) -> None:
        """Emit a page context action for page_number (used by menu and tests)."""
        if action_id == "ocr_page":
            self.ocr_page_requested.emit(page_number)
        self.page_context_action.emit(action_id, page_number)

    def _show_page_context_menu(self, pos: QPoint) -> None:
        item = self.page_list.itemAt(pos)
        if item is None or self._session is None:
            return
        page_num = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(page_num, int):
            return
        menu = QMenu(self)
        actions = [
            ("ocr_page", f"Nhận dạng OCR Trang {page_num}"),
            ("rotate_left", f"Xoay trái 90° Trang {page_num} (Lưu vào PDF)"),
            ("rotate_right", f"Xoay phải 90° Trang {page_num} (Lưu vào PDF)"),
            ("extract_page", f"Trích xuất Trang {page_num} ra PDF…"),
            ("delete_page", f"Xóa Trang {page_num} khỏi PDF"),
        ]
        for act_id, label in actions:
            act = menu.addAction(label)
            if act_id != "ocr_page" and not self._session.is_pdf:
                act.setEnabled(False)
            act.triggered.connect(
                lambda _checked=False, a=act_id, p=page_num: self.trigger_page_action(
                    a, p
                )
            )
        menu.exec(self.page_list.mapToGlobal(pos))

    def _populate_outline(self, session: DocumentSession) -> None:
        self.outline_tree.clear()
        toc = session.outline()
        if not toc:
            placeholder = QTreeWidgetItem(["(Tài liệu không có mục lục)"])
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.outline_tree.addTopLevelItem(placeholder)
            return
        stack: list[tuple[int, QTreeWidgetItem]] = []
        for level, title, page_num in toc:
            node = QTreeWidgetItem([f"{title} (tr. {page_num})"])
            node.setData(0, Qt.ItemDataRole.UserRole, page_num)
            while stack and stack[-1][0] >= level:
                stack.pop()
            if stack:
                stack[-1][1].addChild(node)
            else:
                self.outline_tree.addTopLevelItem(node)
            stack.append((level, node))
        self.outline_tree.expandAll()

    def run_search(self) -> None:
        """Search all pages in the active session and display matching snippets."""
        self.search_results.clear()
        session = self._session
        query = self.search_input.text().strip()
        if session is None or not query:
            self.search_summary_label.setText("")
            return
        matches = session.search_text(query)
        self.search_summary_label.setText(f"Tìm thấy trên {len(matches)} trang")
        for page_num, snippet in matches:
            item = QListWidgetItem(f"Trang {page_num}: {snippet}")
            item.setData(Qt.ItemDataRole.UserRole, page_num)
            self.search_results.addItem(item)

    def _on_reading_mode_changed(self, _index: int) -> None:
        mode = str(self.reading_mode_combo.currentData() or "normal")
        self.reading_mode_changed.emit(mode)

    def _on_page_row_changed(self, row: int) -> None:
        if row >= 0:
            self.page_selected.emit(row + 1)

    def _on_outline_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        page_num = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(page_num, int) and page_num >= 1:
            self.page_selected.emit(page_num)

    def _on_search_item_clicked(self, item: QListWidgetItem) -> None:
        page_num = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page_num, int) and page_num >= 1:
            self.page_selected.emit(page_num)
            self.search_result_selected.emit(page_num, self.search_input.text().strip())

    def _request_current_page_ocr(self) -> None:
        if self._session is not None:
            self.ocr_page_requested.emit(self._session.current_page)

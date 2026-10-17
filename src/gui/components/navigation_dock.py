"""Left workspace navigation dock: File Info Card, Pages, Outline, and Search."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.gui.document_session import DocumentSession


def _format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "0 KB"
    kb = size_bytes / 1024.0
    if kb < 1024.0:
        return f"{kb:.1f} KB"
    return f"{kb / 1024.0:.2f} MB"


class NavigationDock(QWidget):
    """Left workspace sidebar for file info, page badges, PDF outline, and search."""

    page_selected = Signal(int)
    ocr_page_requested = Signal(int)
    search_result_selected = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navigation_dock")
        self._session: DocumentSession | None = None
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
        self.ocr_current_page_btn = QPushButton("OCR trang hiện tại", self.file_card)
        self.ocr_current_page_btn.setObjectName("ocr_current_page_button")
        self.ocr_current_page_btn.setToolTip(
            "Nhận diện ngay trang đang xem bằng mô hình đã chọn"
        )
        self.ocr_current_page_btn.setEnabled(False)
        self.ocr_current_page_btn.clicked.connect(self._request_current_page_ocr)
        card_layout = QVBoxLayout(self.file_card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(4)
        card_layout.addWidget(self.file_name_label)
        card_layout.addWidget(self.file_meta_label)
        card_layout.addWidget(self.ocr_progress_label)
        card_layout.addWidget(self.ocr_current_page_btn)

    def _init_tabs(self) -> None:
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("navigation_tabs")
        self.page_list = QListWidget(self.tabs)
        self.page_list.setObjectName("page_status_list")
        self.page_list.currentRowChanged.connect(self._on_page_row_changed)
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
        self.search_input.returnPressed.connect(self.run_search)
        self.search_btn.clicked.connect(self.run_search)
        self.search_results.itemClicked.connect(self._on_search_item_clicked)
        return pane

    def set_session(self, session: DocumentSession | None) -> None:
        """Bind to an open document session and populate pages and outline."""
        self._session = session
        self.search_results.clear()
        self.search_summary_label.setText("")
        if session is None:
            self.file_name_label.setText("Chưa mở tài liệu")
            self.file_meta_label.setText("0 trang · 0 KB")
            self.ocr_progress_label.setText("Đã OCR: 0 / 0 trang")
            self.ocr_current_page_btn.setEnabled(False)
            self.page_list.clear()
            self.outline_tree.clear()
            return
        self.ocr_current_page_btn.setEnabled(True)
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
        self._sync_page_list(session, total)

    def _sync_page_list(self, session: DocumentSession, total: int) -> None:
        self.page_list.blockSignals(True)
        if self.page_list.count() != total:
            self.page_list.clear()
            for number in range(1, total + 1):
                item = QListWidgetItem(self._page_badge_text(session, number))
                item.setData(Qt.ItemDataRole.UserRole, number)
                self.page_list.addItem(item)
        else:
            for idx in range(total):
                number = idx + 1
                item = self.page_list.item(idx)
                if item is not None:
                    item.setText(self._page_badge_text(session, number))
        if 1 <= session.current_page <= total:
            self.page_list.setCurrentRow(session.current_page - 1)
        self.page_list.blockSignals(False)

    @staticmethod
    def _page_badge_text(session: DocumentSession, page_number: int) -> str:
        result = session.result(page_number)
        if result is None:
            return f"Trang {page_number} — Chờ xử lý"
        low_conf = any(
            w.is_low_confidence
            for block in result.blocks
            for line in block.lines
            for w in line.words
        )
        if low_conf:
            return f"Trang {page_number} — Cần kiểm tra"
        return f"Trang {page_number} — Đã OCR"

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

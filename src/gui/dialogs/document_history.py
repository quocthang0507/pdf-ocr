"""Hộp thoại quản lý lịch sử mở tài liệu."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import os
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def _format_size(num_bytes: int) -> str:
    """Format file size in human-readable units."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


class DocumentHistoryDialog(QDialog):
    """Interactive document history dialog allowing search, opening, and management."""

    file_selected = Signal(str)
    item_removed = Signal(str)
    history_cleared = Signal()

    def __init__(
        self,
        recent_entries: Sequence[str | dict[str, object]] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("document_history_dialog")
        self.setWindowTitle("Lịch sử mở tài liệu")
        self.resize(720, 440)
        self.setMinimumSize(560, 360)

        self._raw_entries: list[dict[str, object]] = []
        self._build_ui()
        self.set_entries(recent_entries)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header with search
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        search_label = QLabel("Tìm kiếm:", self)
        self.search_input = QLineEdit(self)
        self.search_input.setObjectName("history_search_input")
        self.search_input.setPlaceholderText("Tìm theo tên tệp hoặc đường dẫn...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)

        header_layout.addWidget(search_label)
        header_layout.addWidget(self.search_input, 1)
        layout.addLayout(header_layout)

        # Table widget
        self.table = QTableWidget(self)
        self.table.setObjectName("history_table")
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Tên tệp", "Đường dẫn", "Thời gian mở", "Kích thước", "Trạng thái"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.table.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        layout.addWidget(self.table, 1)

        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        self.btn_clear = QPushButton("Xóa tất cả", self)
        self.btn_clear.setObjectName("btn_clear_history")
        self.btn_clear.clicked.connect(self._on_clear_all)

        self.btn_remove = QPushButton("Xóa mục", self)
        self.btn_remove.setObjectName("btn_remove_history_item")
        self.btn_remove.clicked.connect(self._on_remove_selected)

        self.btn_reveal = QPushButton("Mở thư mục", self)
        self.btn_reveal.setObjectName("btn_reveal_folder")
        self.btn_reveal.clicked.connect(self._on_reveal_folder)

        button_layout.addWidget(self.btn_clear)
        button_layout.addWidget(self.btn_remove)
        button_layout.addWidget(self.btn_reveal)
        button_layout.addStretch(1)

        self.btn_open = QPushButton("Mở tài liệu", self)
        self.btn_open.setObjectName("btn_open_document")
        self.btn_open.setDefault(True)
        self.btn_open.clicked.connect(self._on_open_selected)

        self.btn_close = QPushButton("Đóng", self)
        self.btn_close.setObjectName("btn_close_history")
        self.btn_close.clicked.connect(self.reject)

        button_layout.addWidget(self.btn_open)
        button_layout.addWidget(self.btn_close)
        layout.addLayout(button_layout)

        self._update_button_states()

    def set_entries(self, entries: Sequence[str | dict[str, object]]) -> None:
        """Populate the history table with entries."""
        self._raw_entries = []
        for item in entries:
            if isinstance(item, str):
                path = item
                timestamp = ""
            elif isinstance(item, dict):
                path = str(item.get("path", ""))
                timestamp = str(item.get("timestamp", ""))
            else:
                continue
            if path:
                self._raw_entries.append({"path": path, "timestamp": timestamp})

        self._populate_table(self._raw_entries)

    def _populate_table(self, entries: list[dict[str, object]]) -> None:
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            path_str = str(entry.get("path", ""))
            timestamp = str(entry.get("timestamp", ""))
            path_obj = Path(path_str)

            name_item = QTableWidgetItem(path_obj.name)
            name_item.setData(Qt.ItemDataRole.UserRole, path_str)
            self.table.setItem(row, 0, name_item)

            path_item = QTableWidgetItem(path_str)
            path_item.setToolTip(path_str)
            self.table.setItem(row, 1, path_item)

            time_str = timestamp
            if not time_str and path_obj.exists():
                try:
                    mtime = os.path.getmtime(path_obj)
                    time_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
                except OSError:
                    time_str = "—"
            time_item = QTableWidgetItem(time_str or "—")
            self.table.setItem(row, 2, time_item)

            exists = path_obj.is_file()
            if exists:
                try:
                    size_str = _format_size(os.path.getsize(path_obj))
                except OSError:
                    size_str = "—"
                status_str = "Tồn tại"
            else:
                size_str = "—"
                status_str = "Không tìm thấy"

            size_item = QTableWidgetItem(size_str)
            self.table.setItem(row, 3, size_item)

            status_item = QTableWidgetItem(status_str)
            if exists:
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            else:
                status_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 4, status_item)

        self._update_button_states()

    def _apply_filter(self, query: str) -> None:
        query = query.strip().lower()
        if not query:
            filtered = self._raw_entries
        else:
            filtered = [
                entry
                for entry in self._raw_entries
                if query in str(entry.get("path", "")).lower()
            ]
        self._populate_table(filtered)

    def _selected_path(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _update_button_states(self) -> None:
        has_selection = self.table.currentRow() >= 0
        has_items = self.table.rowCount() > 0
        self.btn_open.setEnabled(has_selection)
        self.btn_remove.setEnabled(has_selection)
        self.btn_reveal.setEnabled(has_selection)
        self.btn_clear.setEnabled(has_items)

    def _on_item_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        path_item = self.table.item(row, 0)
        if path_item:
            path = str(path_item.data(Qt.ItemDataRole.UserRole))
            self.file_selected.emit(path)
            self.accept()

    def _on_open_selected(self) -> None:
        path = self._selected_path()
        if path:
            self.file_selected.emit(path)
            self.accept()

    def _on_reveal_folder(self) -> None:
        path = self._selected_path()
        if path:
            folder = Path(path).parent
            if folder.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_remove_selected(self) -> None:
        path = self._selected_path()
        if not path:
            return
        self._raw_entries = [e for e in self._raw_entries if e.get("path") != path]
        self.item_removed.emit(path)
        self._apply_filter(self.search_input.text())

    def _on_clear_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Xác nhận xóa",
            "Bạn có chắc chắn muốn xóa toàn bộ lịch sử mở tài liệu?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._raw_entries.clear()
            self.history_cleared.emit()
            self.table.setRowCount(0)
            self._update_button_states()

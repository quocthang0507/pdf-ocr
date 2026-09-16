"""Find and replace for the transcript, for repeated OCR mistakes."""

from __future__ import annotations

from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QWidget,
)


class FindReplaceDialog(QDialog):
    """Non-modal search panel driving one transcript editor.

    Replace All runs inside a single edit block, so one Ctrl+Z undoes the whole
    correction rather than every occurrence one at a time.
    """

    def __init__(self, editor: QTextEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent or editor.window())
        self.setObjectName("find_replace_dialog")
        self.setWindowTitle("Tìm và thay thế")
        self._editor = editor
        self.find_edit = _line_edit(self, "find_edit", "Tìm gì…")
        self.replace_edit = _line_edit(self, "replace_edit", "Thay bằng…")
        self.case_sensitive_box = QCheckBox("Phân biệt hoa thường", self)
        self.case_sensitive_box.setObjectName("case_sensitive_box")
        self.whole_words_box = QCheckBox("Đúng toàn bộ từ", self)
        self.whole_words_box.setObjectName("whole_words_box")
        self.status_label = QLabel("", self)
        self.status_label.setObjectName("find_status")
        self._build_layout()

    def _build_layout(self) -> None:
        layout = QGridLayout(self)
        layout.addWidget(QLabel("Tìm", self), 0, 0)
        layout.addWidget(self.find_edit, 0, 1)
        layout.addWidget(_button(self, "Tìm tiếp", self.find_next), 0, 2)
        layout.addWidget(QLabel("Thay bằng", self), 1, 0)
        layout.addWidget(self.replace_edit, 1, 1)
        layout.addWidget(_button(self, "Thay thế", self.replace_current), 1, 2)
        layout.addWidget(self.case_sensitive_box, 2, 0, 1, 2)
        layout.addWidget(_button(self, "Thay tất cả", self.replace_all), 2, 2)
        layout.addWidget(self.whole_words_box, 3, 0, 1, 2)
        layout.addWidget(self.status_label, 4, 0, 1, 3)

    # -- searching --------------------------------------------------------

    def _flags(self) -> QTextDocument.FindFlag:
        flags = QTextDocument.FindFlag(0)
        if self.case_sensitive_box.isChecked():
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        if self.whole_words_box.isChecked():
            flags |= QTextDocument.FindFlag.FindWholeWords
        return flags

    def find_next(self) -> bool:
        """Search forward, wrapping to the start once the end is reached."""
        needle = self.find_edit.text()
        if not needle:
            return False
        if self._editor.find(needle, self._flags()):
            self.status_label.clear()
            return True
        if self._find_from_start(needle):
            self.status_label.setText("Đã quay lại từ đầu văn bản.")
            return True
        self.status_label.setText("Không tìm thấy nội dung cần tìm.")
        return False

    def _find_from_start(self, needle: str) -> bool:
        cursor = self._editor.textCursor()
        restart = QTextCursor(self._editor.document())
        restart.movePosition(QTextCursor.MoveOperation.Start)
        self._editor.setTextCursor(restart)
        if self._editor.find(needle, self._flags()):
            return True
        self._editor.setTextCursor(cursor)
        return False

    # -- replacing --------------------------------------------------------

    def replace_current(self) -> bool:
        """Replace the highlighted match, or find one first when none is."""
        cursor = self._editor.textCursor()
        if not cursor.hasSelection() or not self._selection_matches(cursor):
            return self.find_next()
        cursor.insertText(self.replace_edit.text())
        return True

    def _selection_matches(self, cursor: QTextCursor) -> bool:
        selected = cursor.selectedText()
        needle = self.find_edit.text()
        if self.case_sensitive_box.isChecked():
            return selected == needle
        return selected.casefold() == needle.casefold()

    def replace_all(self) -> int:
        """Replace every occurrence as one undoable edit, and report the count."""
        needle = self.find_edit.text()
        if not needle:
            return 0
        replacement = self.replace_edit.text()
        cursor = QTextCursor(self._editor.document())
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.beginEditBlock()
        replaced = self._replace_from(cursor, needle, replacement)
        cursor.endEditBlock()
        self.status_label.setText(f"Đã thay thế {replaced} vị trí.")
        return replaced

    def _replace_from(self, cursor: QTextCursor, needle: str, replacement: str) -> int:
        """Continue past each replacement so a self-containing text terminates."""
        document = self._editor.document()
        replaced = 0
        found = document.find(needle, cursor, self._flags())
        while not found.isNull():
            found.insertText(replacement)
            replaced += 1
            found = document.find(needle, found, self._flags())
        return replaced

    def show_for(self, selection: str = "") -> None:
        """Bring the panel up, seeded with whatever the user had selected."""
        if selection:
            self.find_edit.setText(selection)
        self.status_label.clear()
        self.show()
        self.raise_()
        self.find_edit.setFocus()
        self.find_edit.selectAll()


def _line_edit(parent: QWidget, name: str, placeholder: str) -> QLineEdit:
    edit = QLineEdit(parent)
    edit.setObjectName(name)
    edit.setPlaceholderText(placeholder)
    edit.setClearButtonEnabled(True)
    return edit


def _button(parent: QWidget, text: str, handler: object) -> QPushButton:
    button = QPushButton(text, parent)
    button.setObjectName(f"button_{text.replace(' ', '_').lower()}")
    button.clicked.connect(handler)
    return button

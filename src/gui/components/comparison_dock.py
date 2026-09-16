"""Side-by-side verification editor: original page against recognised text."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial

import re

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.constants import LOW_CONFIDENCE_COLOR, BlockType
from src.core.models import BoundingBox, OCRBlock, OCRPage, OCRTable
from src.gui.components.document_canvas import DocumentCanvas
from src.gui.dialogs.find_replace import FindReplaceDialog
from src.gui.dialogs.table_editor import TableEditorDialog

BLOCK_SEPARATOR = "\n\n"
_MIN_PAGE_PANE_WIDTH = 240
_EVEN_SPLIT = 600
_ZOOM_ACTIONS = {1: "zoom_in", -1: "zoom_out", 0: "reset_zoom"}


@dataclass(frozen=True)
class TextSpan:
    """Half-open character range of one recognised element in the transcript."""

    start: int
    end: int

    def contains(self, position: int) -> bool:
        return self.start <= position <= self.end


def _render(page: OCRPage) -> tuple[str, tuple[TextSpan, ...], tuple[TextSpan, ...]]:
    """Lay out the transcript once, recording where each block and word landed."""
    parts: list[str] = []
    blocks: list[TextSpan] = []
    uncertain: list[TextSpan] = []
    cursor = 0
    for index, block in enumerate(page.blocks):
        if index:
            parts.append(BLOCK_SEPARATOR)
            cursor += len(BLOCK_SEPARATOR)
        start = cursor
        cursor = _render_block_lines(block, parts, cursor, uncertain)
        blocks.append(TextSpan(start, cursor))
    return "".join(parts), tuple(blocks), tuple(uncertain)


_LIST_MARKER_REGEX = re.compile(r"^([•\-\*\+–—]|\d+[\.\)]|[a-zA-Z][\.\)])\s+")


def _should_break_line(prev_text: str, curr_text: str) -> bool:
    if prev_text.endswith(":"):
        return True
    if bool(_LIST_MARKER_REGEX.match(curr_text)):
        return True
    return False


def _render_block_lines(
    block: OCRBlock, parts: list[str], cursor: int, uncertain: list[TextSpan]
) -> int:
    for line_index, line in enumerate(block.lines):
        if line_index:
            prev_line = block.lines[line_index - 1]
            prev_text = prev_line.text.rstrip()
            curr_text = line.text.lstrip()
            if _should_break_line(prev_text, curr_text):
                parts.append("\n")
                cursor += 1
            elif prev_text.endswith("-") and not prev_text.endswith(" -"):
                # Nối từ bị ngắt bởi dấu gạch ngang cuối dòng (de-hyphenation)
                pass
            else:
                parts.append(" ")
                cursor += 1
        for word_index, word in enumerate(line.words):
            if word_index:
                parts.append(" ")
                cursor += 1
            parts.append(word.text)
            if word.is_low_confidence:
                uncertain.append(TextSpan(cursor, cursor + len(word.text)))
            cursor += len(word.text)
    return cursor


class ComparisonDock(QWidget):
    """Stateful two-pane editor; the page model itself is never mutated here.

    Both panes drive each other, so every programmatic update is wrapped in a
    re-entrance guard to keep a click from bouncing back and forth.
    """

    page_change_requested = Signal(int)
    transcript_edited = Signal(str)
    table_edited = Signal(int, OCRTable)
    region_ocr_requested = Signal(BoundingBox)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("comparison_dock")
        self.canvas = DocumentCanvas(self)
        self.canvas.setMinimumWidth(_MIN_PAGE_PANE_WIDTH)
        self.editor = QTextEdit(self)
        self.editor.setObjectName("transcript_editor")
        self.editor.setAcceptRichText(False)
        self.editor.setUndoRedoEnabled(True)
        self.editor.setPlaceholderText("Kết quả nhận diện sẽ hiển thị tại đây.")
        self.region_label = QLabel(self)
        self.region_label.setObjectName("region_result")
        self.region_label.setWordWrap(True)
        self.region_label.hide()
        self._block_spans: tuple[TextSpan, ...] = ()
        self._page: OCRPage | None = None
        self._current_page = 0
        self._total_pages = 0
        self.prev_page_btn = QPushButton(self)
        self.prev_page_btn.setObjectName("prev_page_button")
        self.prev_page_btn.setToolTip("Trang trước")
        icon_left = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowLeft)
        if not icon_left.isNull():
            self.prev_page_btn.setIcon(icon_left)
        else:
            self.prev_page_btn.setText("◀")
        self.prev_page_btn.setEnabled(False)
        self.page_label = QLabel("Trang 0 / 0", self)
        self.page_label.setObjectName("page_indicator")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_page_btn = QPushButton(self)
        self.next_page_btn.setObjectName("next_page_button")
        self.next_page_btn.setToolTip("Trang sau")
        icon_right = self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        if not icon_right.isNull():
            self.next_page_btn.setIcon(icon_right)
        else:
            self.next_page_btn.setText("▶")
        self.next_page_btn.setEnabled(False)
        self.table_editor: TableEditorDialog | None = None
        self.find_replace_dialog: FindReplaceDialog | None = None
        self._syncing = False
        self._shortcuts = self._create_shortcuts()
        self._build_layout()
        self.canvas.block_selected.connect(self._focus_text_block)
        self.canvas.block_activated.connect(self.edit_block_table)
        self.canvas.region_selected.connect(self.region_ocr_requested)
        self.editor.cursorPositionChanged.connect(self._focus_canvas_block)
        self.editor.textChanged.connect(self._publish_transcript)
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.next_page_btn.clicked.connect(self._next_page)

    def _build_layout(self) -> None:
        canvas_pane = QWidget(self)
        canvas_layout = QVBoxLayout(canvas_pane)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(4)
        canvas_layout.addWidget(self.canvas, 1)

        nav_bar = QWidget(canvas_pane)
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(4, 2, 4, 4)
        nav_layout.setSpacing(8)
        nav_layout.addStretch(1)
        nav_layout.addWidget(self.prev_page_btn)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.next_page_btn)
        nav_layout.addStretch(1)
        canvas_layout.addWidget(nav_bar)

        text_pane = QWidget(self)
        text_layout = QVBoxLayout(text_pane)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.editor)
        text_layout.addWidget(self.region_label)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("comparison_splitter")
        splitter.addWidget(canvas_pane)
        splitter.addWidget(text_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        # The editor's size hint would otherwise squeeze the page out of view.
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([_EVEN_SPLIT, _EVEN_SPLIT])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _create_shortcuts(self) -> tuple[QShortcut, ...]:
        """Qt only binds Ctrl+Shift+Z for redo on some platforms."""
        redo = QShortcut(QKeySequence("Ctrl+Y"), self.editor)
        redo.setContext(Qt.ShortcutContext.WidgetShortcut)
        redo.activated.connect(self.editor.redo)
        find = QShortcut(QKeySequence("Ctrl+H"), self.editor)
        find.setContext(Qt.ShortcutContext.WidgetShortcut)
        find.activated.connect(self.open_find_replace)
        return (redo, find)

    def open_find_replace(self) -> None:
        """Show the search panel, reusing the one already built for this editor."""
        if self.find_replace_dialog is None:
            self.find_replace_dialog = FindReplaceDialog(self.editor, self)
        self.find_replace_dialog.show_for(self.editor.textCursor().selectedText())

    def editor_shortcuts(self) -> tuple[QShortcut, ...]:
        return self._shortcuts

    # -- page navigation --------------------------------------------------

    def _prev_page(self) -> None:
        if self._current_page > 1:
            self.page_change_requested.emit(self._current_page - 1)

    def _next_page(self) -> None:
        if self._current_page < self._total_pages:
            self.page_change_requested.emit(self._current_page + 1)

    def set_page_info(self, current: int, total: int) -> None:
        """Update current page number, total pages and button availability."""
        self._current_page = max(0, current)
        self._total_pages = max(0, total)
        if self._total_pages > 0:
            self.page_label.setText(f"Trang {self._current_page} / {self._total_pages}")
        else:
            self.page_label.setText("Trang 0 / 0")
        self.prev_page_btn.setEnabled(self._current_page > 1)
        self.next_page_btn.setEnabled(self._current_page < self._total_pages)

    def current_page(self) -> int:
        return self._current_page

    def total_pages(self) -> int:
        return self._total_pages

    # -- content ----------------------------------------------------------

    def set_image(self, image: np.ndarray, text: str = "") -> None:
        """Display an unrecognised page image, optionally with extracted native text."""
        if not isinstance(image, np.ndarray):
            raise TypeError("Dữ liệu hình ảnh phải là đối tượng numpy.ndarray.")
        self._block_spans = ()
        self._page = None
        self.canvas.set_image(image)
        with self._suspend_sync():
            self.editor.setPlainText(text)
            self.editor.setExtraSelections([])
        self.region_label.hide()

    def set_page(self, page: OCRPage, image: np.ndarray) -> None:
        """Show one recognised page beside the image it was recognised from."""
        if not isinstance(page, OCRPage):
            raise ValueError("Dữ liệu trang phải là đối tượng OCRPage.")
        transcript, blocks, uncertain = _render(page)
        self._block_spans = blocks
        self._page = page
        self.canvas.set_image(image)
        self.canvas.set_blocks(page.blocks)
        with self._suspend_sync():
            self.editor.setPlainText(transcript)
            self._highlight(uncertain)
        self.region_label.hide()

    def clear(self) -> None:
        """Drop both panes so the next document starts from an empty state."""
        self._block_spans = ()
        self._page = None
        self.table_editor = None
        self.set_page_info(0, 0)
        self.canvas.clear_page()
        with self._suspend_sync():
            self.editor.clear()
            self.editor.setExtraSelections([])
        self.region_label.clear()
        self.region_label.hide()

    def transcript(self) -> str:
        return self.editor.toPlainText()

    def apply_zoom(self, step: int) -> None:
        """Route a zoom command from the window to the page view."""
        getattr(self.canvas, _ZOOM_ACTIONS[step])()

    # -- table editing ----------------------------------------------------

    def edit_block_table(self, index: int) -> None:
        """Open the grid editor for the table drawn under this layout block."""
        table_index = self._table_for_block(index)
        if table_index is None or self._page is None:
            return
        editor = TableEditorDialog(self._page.tables[table_index], self)
        editor.table_committed.connect(partial(self._publish_table_edit, table_index))
        self.table_editor = editor
        editor.open()

    def _table_for_block(self, index: int) -> int | None:
        """Match a table block to the extracted table drawn inside it."""
        if self._page is None or not 0 <= index < len(self._page.blocks):
            return None
        block = self._page.blocks[index]
        if block.block_type is not BlockType.TABLE:
            return None
        for position, table in enumerate(self._page.tables):
            centre_x = (table.bbox.x1 + table.bbox.x2) / 2
            centre_y = (table.bbox.y1 + table.bbox.y2) / 2
            inside_x = block.bbox.x1 <= centre_x <= block.bbox.x2
            inside_y = block.bbox.y1 <= centre_y <= block.bbox.y2
            if inside_x and inside_y:
                return position
        return None

    def _publish_table_edit(self, index: int, table: OCRTable) -> None:
        self.table_edited.emit(index, table)

    # -- region results ---------------------------------------------------

    def set_region_mode(self, enabled: bool) -> None:
        """Let the user draw a rectangle to recognise instead of the whole page."""
        self.canvas.set_region_mode(enabled)
        if not enabled:
            self.show_region_result("")

    def region_mode(self) -> bool:
        return self.canvas.region_mode()

    def show_region_result(self, text: str) -> None:
        """Display text recognised from a selected region beside the transcript."""
        self.region_label.setText(text)
        self.region_label.setVisible(bool(text))

    def region_result(self) -> str:
        return self.region_label.text()

    # -- two-way synchronisation ------------------------------------------

    def _highlight(self, spans: tuple[TextSpan, ...]) -> None:
        warning = QTextCharFormat()
        warning.setBackground(QColor(LOW_CONFIDENCE_COLOR))
        selections: list[QTextEdit.ExtraSelection] = []
        for span in spans:
            selection = QTextEdit.ExtraSelection()
            selection.format = warning
            cursor = QTextCursor(self.editor.document())
            cursor.setPosition(span.start)
            cursor.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        self.editor.setExtraSelections(selections)

    def _focus_canvas_block(self) -> None:
        if self._syncing:
            return
        index = self._block_at(self.editor.textCursor().position())
        if index is None:
            return
        with self._suspend_sync():
            self.canvas.focus_on_block(index)

    def _focus_text_block(self, index: int) -> None:
        if self._syncing or not 0 <= index < len(self._block_spans):
            return
        with self._suspend_sync():
            cursor = self.editor.textCursor()
            cursor.setPosition(self._block_spans[index].start)
            self.editor.setTextCursor(cursor)
            self.editor.ensureCursorVisible()

    def _publish_transcript(self) -> None:
        if not self._syncing:
            self.transcript_edited.emit(self.transcript())

    def _block_at(self, position: int) -> int | None:
        for index, span in enumerate(self._block_spans):
            if span.contains(position):
                return index
        return None

    @contextmanager
    def _suspend_sync(self) -> Iterator[None]:
        """Silence the partner pane's echo while this pane is updated."""
        previous = self._syncing
        self._syncing = True
        try:
            yield
        finally:
            self._syncing = previous

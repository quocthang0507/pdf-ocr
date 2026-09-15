"""Side-by-side verification editor: original page against recognised text."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QLabel,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.constants import LOW_CONFIDENCE_COLOR
from src.core.models import OCRBlock, OCRPage
from src.gui.components.document_canvas import DocumentCanvas

BLOCK_SEPARATOR = "\n\n"
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


def _render_block_lines(
    block: OCRBlock, parts: list[str], cursor: int, uncertain: list[TextSpan]
) -> int:
    for line_index, line in enumerate(block.lines):
        if line_index:
            parts.append("\n")
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

    transcript_edited = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("comparison_dock")
        self.canvas = DocumentCanvas(self)
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
        self._syncing = False
        self._shortcuts = self._create_shortcuts()
        self._build_layout()
        self.canvas.block_selected.connect(self._focus_text_block)
        self.editor.cursorPositionChanged.connect(self._focus_canvas_block)
        self.editor.textChanged.connect(self._publish_transcript)

    def _build_layout(self) -> None:
        text_pane = QWidget(self)
        text_layout = QVBoxLayout(text_pane)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.editor)
        text_layout.addWidget(self.region_label)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("comparison_splitter")
        splitter.addWidget(self.canvas)
        splitter.addWidget(text_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _create_shortcuts(self) -> tuple[QShortcut, ...]:
        """Qt only binds Ctrl+Shift+Z for redo on some platforms."""
        redo = QShortcut(QKeySequence("Ctrl+Y"), self.editor)
        redo.setContext(Qt.ShortcutContext.WidgetShortcut)
        redo.activated.connect(self.editor.redo)
        return (redo,)

    def editor_shortcuts(self) -> tuple[QShortcut, ...]:
        return self._shortcuts

    # -- content ----------------------------------------------------------

    def set_page(self, page: OCRPage, image: np.ndarray) -> None:
        """Show one recognised page beside the image it was recognised from."""
        if not isinstance(page, OCRPage):
            raise ValueError("Dữ liệu trang phải là đối tượng OCRPage.")
        transcript, blocks, uncertain = _render(page)
        self._block_spans = blocks
        self.canvas.set_image(image)
        self.canvas.set_blocks(page.blocks)
        with self._suspend_sync():
            self.editor.setPlainText(transcript)
            self._highlight(uncertain)
        self.region_label.hide()

    def clear(self) -> None:
        """Drop both panes so the next document starts from an empty state."""
        self._block_spans = ()
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

    # -- region results ---------------------------------------------------

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

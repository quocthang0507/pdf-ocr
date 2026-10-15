"""Side-by-side verification editor: original page against recognised text."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollBar,
    QSpinBox,
    QSplitter,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.constants import LOW_CONFIDENCE_COLOR, BlockType
from src.core.models import BoundingBox, OCRBlock, OCRPage, OCRTable
from src.core.transcript import BLOCK_SEPARATOR
from src.gui.components.document_canvas import DocumentCanvas
from src.gui.dialogs.find_replace import FindReplaceDialog
from src.gui.dialogs.table_editor import TableEditorDialog

_MIN_PAGE_PANE_WIDTH = 240
_EVEN_SPLIT = 600
_REGION_RESULT_MAX_HEIGHT = 140
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


def _column_count(blocks: tuple[OCRBlock, ...]) -> int:
    """Estimate text columns as the widest set of side-by-side narrow blocks."""
    narrow = [
        block
        for block in blocks
        if block.block_type
        in (
            BlockType.TEXT,
            BlockType.TITLE,
            BlockType.HEADING_1,
            BlockType.HEADING_2,
            BlockType.HEADING_3,
        )
    ]
    if not narrow:
        return 0
    page_left = min(block.bbox.x1 for block in narrow)
    page_right = max(block.bbox.x2 for block in narrow)
    span = page_right - page_left
    columns: list[tuple[float, float]] = []
    for block in sorted(narrow, key=lambda item: item.bbox.x1):
        if span > 0 and block.bbox.width >= span * 0.8:
            continue
        for index, (left, right) in enumerate(columns):
            overlap = min(right, block.bbox.x2) - max(left, block.bbox.x1)
            if overlap > 0.5 * min(right - left, block.bbox.width):
                columns[index] = (min(left, block.bbox.x1), max(right, block.bbox.x2))
                break
        else:
            columns.append((block.bbox.x1, block.bbox.x2))
    return max(1, len(columns))


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


def _group_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("nav_group_label")
    return label


def _separator(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setObjectName("nav_separator")
    line.setFrameShape(QFrame.Shape.VLine)
    return line


class ComparisonDock(QWidget):
    """Stateful two-pane editor; the page model itself is never mutated here.

    Both panes drive each other, so every programmatic update is wrapped in a
    re-entrance guard to keep a click from bouncing back and forth.
    """

    page_change_requested = Signal(int)
    transcript_edited = Signal(str)
    table_edited = Signal(int, OCRTable)
    region_ocr_requested = Signal(BoundingBox)
    region_mode_cancelled = Signal()
    region_rerun_requested = Signal()

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
        self.region_panel = QFrame(self)
        self.region_panel.setObjectName("region_panel")
        self.region_title = QLabel("Kết quả vùng chọn", self.region_panel)
        self.region_title.setObjectName("region_title")
        self.region_copy_button = QPushButton("Sao chép", self.region_panel)
        self.region_copy_button.setObjectName("region_copy")
        self.region_insert_button = QPushButton("Chèn vào bản chép", self.region_panel)
        self.region_insert_button.setObjectName("region_insert")
        self.region_insert_button.setToolTip(
            "Chèn kết quả vùng chọn vào vị trí con trỏ trong bản chép"
        )
        self.region_rerun_button = QPushButton("OCR bằng mô hình", self.region_panel)
        self.region_rerun_button.setObjectName("region_rerun")
        self.region_rerun_button.setToolTip(
            "Nhận diện lại vùng này bằng mô hình đang chọn ở bảng tùy chọn"
        )
        self.region_source_label = QLabel("", self.region_panel)
        self.region_source_label.setObjectName("region_source")
        self.region_source_label.setWordWrap(True)
        self.region_label = QPlainTextEdit(self.region_panel)
        self.region_label.setObjectName("region_result")
        self.region_label.setReadOnly(True)
        # A long selection scrolls inside the panel instead of hiding the editor.
        self.region_label.setMaximumHeight(_REGION_RESULT_MAX_HEIGHT)
        self.region_panel.hide()
        self.structure_panel = QFrame(self)
        self.structure_panel.setObjectName("structure_panel")
        self.structure_label = QLabel(self.structure_panel)
        self.structure_label.setObjectName("structure_summary")
        self.structure_label.setWordWrap(True)
        self.table_combo = QComboBox(self.structure_panel)
        self.table_combo.setObjectName("table_combo")
        self.table_combo.setToolTip("Chọn bảng biểu để xem trên trang")
        self.edit_table_button = QPushButton("Chỉnh sửa bảng…", self.structure_panel)
        self.edit_table_button.setObjectName("edit_table_button")
        self.edit_table_button.setToolTip(
            "Sửa từng ô của bảng trước khi xuất ra Excel/Word "
            "(hoặc nhấp đúp vào khung bảng trên trang)"
        )
        self.structure_panel.hide()
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
        self.page_spin = QSpinBox(self)
        self.page_spin.setObjectName("page_spin")
        self.page_spin.setToolTip("Đi tới trang")
        self.page_spin.setRange(0, 0)
        self.page_spin.setEnabled(False)
        self.page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setFixedWidth(64)
        self.page_slider = QScrollBar(Qt.Orientation.Horizontal, self)
        self.page_slider.setObjectName("page_slider")
        self.page_slider.setToolTip("Cuộn để chuyển trang")
        self.page_slider.setRange(0, 0)
        self.page_slider.setEnabled(False)
        self.page_label = QLabel("/ 0", self)
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
        self.zoom_out_btn = QPushButton("−", self)
        self.zoom_out_btn.setObjectName("zoom_out_button")
        self.zoom_out_btn.setToolTip("Thu nhỏ")
        self.zoom_label = QLabel("100%", self)
        self.zoom_label.setObjectName("zoom_indicator")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(48)
        self.zoom_in_btn = QPushButton("+", self)
        self.zoom_in_btn.setObjectName("zoom_in_button")
        self.zoom_in_btn.setToolTip("Phóng to")
        for button in (self.zoom_out_btn, self.zoom_in_btn):
            button.setFixedSize(30, 30)
        self.zoom_reset_btn = QPushButton("Vừa khung", self)
        self.zoom_reset_btn.setObjectName("zoom_reset_button")
        self.zoom_reset_btn.setToolTip("Vừa khung cửa sổ")
        self.table_editor: TableEditorDialog | None = None
        self.find_replace_dialog: FindReplaceDialog | None = None
        self._syncing = False
        self._shortcuts = self._create_shortcuts()
        self._build_layout()
        self.canvas.block_selected.connect(self._focus_text_block)
        self.canvas.block_activated.connect(self.edit_block_table)
        self.canvas.region_selected.connect(self.region_ocr_requested)
        self.canvas.page_step_requested.connect(self._on_page_step_requested)
        self.canvas.region_mode_cancelled.connect(self.region_mode_cancelled)
        self.canvas.zoom_changed.connect(self._show_zoom)
        self.editor.cursorPositionChanged.connect(self._focus_canvas_block)
        self.editor.textChanged.connect(self._publish_transcript)
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.next_page_btn.clicked.connect(self._next_page)
        self.page_spin.editingFinished.connect(self._jump_to_spin_page)
        self.page_slider.valueChanged.connect(self._jump_to_slider_page)
        self.zoom_in_btn.clicked.connect(self.canvas.zoom_in)
        self.zoom_out_btn.clicked.connect(self.canvas.zoom_out)
        self.zoom_reset_btn.clicked.connect(self.canvas.reset_zoom)
        self._show_zoom(self.canvas.zoom_factor())

    def _build_layout(self) -> None:
        canvas_pane = QWidget(self)
        canvas_layout = QVBoxLayout(canvas_pane)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(4)
        canvas_layout.addWidget(self.canvas, 1)

        nav_bar = QFrame(canvas_pane)
        nav_bar.setObjectName("nav_bar")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(8, 6, 8, 6)
        nav_layout.setSpacing(6)
        nav_layout.addWidget(_group_label("Thu phóng", nav_bar))
        nav_layout.addWidget(self.zoom_out_btn)
        nav_layout.addWidget(self.zoom_label)
        nav_layout.addWidget(self.zoom_in_btn)
        nav_layout.addWidget(self.zoom_reset_btn)
        nav_layout.addSpacing(12)
        nav_layout.addWidget(_separator(nav_bar))
        nav_layout.addSpacing(12)
        nav_layout.addWidget(_group_label("Trang", nav_bar))
        nav_layout.addWidget(self.prev_page_btn)
        nav_layout.addWidget(self.page_spin)
        nav_layout.addWidget(self.next_page_btn)
        nav_layout.addWidget(self.page_slider, 1)
        nav_layout.addWidget(self.page_label)
        canvas_layout.addWidget(nav_bar)

        text_pane = QWidget(self)
        text_layout = QVBoxLayout(text_pane)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.editor, 1)
        text_layout.addWidget(self.structure_panel)
        text_layout.addWidget(self.region_panel)
        structure_layout = QHBoxLayout(self.structure_panel)
        structure_layout.setContentsMargins(8, 4, 8, 4)
        structure_layout.addWidget(self.structure_label, 1)
        structure_layout.addWidget(self.table_combo)
        structure_layout.addWidget(self.edit_table_button)
        self.table_combo.currentIndexChanged.connect(self._show_table_on_canvas)
        self.edit_table_button.clicked.connect(self.edit_selected_table)
        header = QHBoxLayout()
        header.addWidget(self.region_title)
        header.addStretch(1)
        header.addWidget(self.region_rerun_button)
        header.addWidget(self.region_insert_button)
        header.addWidget(self.region_copy_button)
        panel_layout = QVBoxLayout(self.region_panel)
        panel_layout.setContentsMargins(12, 10, 12, 12)
        panel_layout.addLayout(header)
        panel_layout.addWidget(self.region_source_label)
        panel_layout.addWidget(self.region_label)
        self.region_copy_button.clicked.connect(self.copy_region_result)
        self.region_insert_button.clicked.connect(self.insert_region_result)
        self.region_rerun_button.clicked.connect(self.region_rerun_requested)
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

    def _on_page_step_requested(self, step: int) -> None:
        if step > 0:
            self._next_page()
        elif step < 0:
            self._prev_page()

    def _prev_page(self) -> None:
        if self._current_page > 1:
            self.page_change_requested.emit(self._current_page - 1)

    def _next_page(self) -> None:
        if self._current_page < self._total_pages:
            self.page_change_requested.emit(self._current_page + 1)

    def _jump_to_spin_page(self) -> None:
        page = self.page_spin.value()
        if page != self._current_page and self._total_pages > 0:
            self.page_change_requested.emit(page)

    def _jump_to_slider_page(self, page: int) -> None:
        if page != self._current_page and self._total_pages > 0:
            self.page_change_requested.emit(page)

    def set_page_info(self, current: int, total: int) -> None:
        """Update current page number, total pages and button availability."""
        self._current_page = max(0, current)
        self._total_pages = max(0, total)
        if self._total_pages > 0:
            self.page_label.setText(f"Trang {self._current_page} / {self._total_pages}")
        else:
            self.page_label.setText("Trang 0 / 0")
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, max(1, self._total_pages))
        self.page_spin.setValue(max(1, self._current_page))
        self.page_spin.setEnabled(self._total_pages > 0)
        self.page_spin.blockSignals(False)
        self.page_slider.blockSignals(True)
        self.page_slider.setRange(1, max(1, self._total_pages))
        self.page_slider.setValue(max(1, self._current_page))
        self.page_slider.setEnabled(self._total_pages > 1)
        self.page_slider.blockSignals(False)
        self.prev_page_btn.setEnabled(self._current_page > 1)
        self.next_page_btn.setEnabled(self._current_page < self._total_pages)

    def current_page(self) -> int:
        return self._current_page

    def total_pages(self) -> int:
        return self._total_pages

    def _show_zoom(self, factor: float) -> None:
        self.zoom_label.setText(f"{round(factor * 100)}%")

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
        self.region_panel.hide()
        self._refresh_structure()

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
        self.region_panel.hide()
        self._refresh_structure()

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
        self.region_panel.hide()
        self._refresh_structure()

    def transcript(self) -> str:
        return self.editor.toPlainText()

    def apply_zoom(self, step: int) -> None:
        """Route a zoom command from the window to the page view."""
        getattr(self.canvas, _ZOOM_ACTIONS[step])()

    # -- table editing ----------------------------------------------------

    def edit_block_table(self, index: int) -> None:
        """Open the grid editor for the table drawn under this layout block."""
        table_index = self._table_for_block(index)
        if table_index is not None:
            self.edit_table(table_index)

    def edit_selected_table(self) -> None:
        """Edit the table picked in the list, or the only one on the page."""
        position = self.table_combo.currentIndex()
        if position >= 0:
            self.edit_table(position)

    def edit_table(self, table_index: int) -> None:
        """Open the grid editor for one table of the current page."""
        if self._page is None or not 0 <= table_index < len(self._page.tables):
            return
        editor = TableEditorDialog(self._page.tables[table_index], self)
        editor.table_committed.connect(partial(self._publish_table_edit, table_index))
        self.table_editor = editor
        editor.open()

    def table_count(self) -> int:
        return len(self._page.tables) if self._page is not None else 0

    def set_layout_visible(self, visible: bool) -> None:
        """Show or hide the coloured layout frames drawn over the page."""
        self.canvas.set_blocks_visible(visible)

    def _refresh_structure(self) -> None:
        """Summarise what was recognised on the page and list its tables."""
        page = self._page
        self.table_combo.blockSignals(True)
        self.table_combo.clear()
        if page is None:
            self.table_combo.blockSignals(False)
            self.structure_panel.hide()
            return
        counts = {kind: 0 for kind in BlockType}
        for block in page.blocks:
            counts[block.block_type] += 1
        for position, table in enumerate(page.tables, start=1):
            columns = len(table.rows[0]) if table.rows else 0
            self.table_combo.addItem(f"Bảng {position} ({len(table.rows)}×{columns})")
        self.table_combo.blockSignals(False)
        has_tables = bool(page.tables)
        self.table_combo.setVisible(has_tables)
        self.edit_table_button.setVisible(has_tables)
        heading_count = sum(
            counts[kind]
            for kind in (
                BlockType.TITLE,
                BlockType.HEADING_1,
                BlockType.HEADING_2,
                BlockType.HEADING_3,
            )
        )
        self.structure_label.setText(
            f"Bố cục: {_column_count(page.blocks)} cột · "
            f"{counts[BlockType.TEXT]} đoạn · "
            f"{heading_count} tiêu đề · "
            f"{counts[BlockType.CAPTION]} chú thích · "
            f"{len(page.tables)} bảng · {counts[BlockType.IMAGE]} hình"
        )
        self.structure_panel.show()

    def _show_table_on_canvas(self, position: int) -> None:
        """Highlight the table picked in the list on the page image."""
        block_index = self._block_for_table(position)
        if block_index is not None:
            self.canvas.focus_on_block(block_index)

    def _block_for_table(self, position: int) -> int | None:
        if self._page is None or not 0 <= position < len(self._page.tables):
            return None
        for index in range(len(self._page.blocks)):
            if self._table_for_block(index) == position:
                return index
        return None

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
        if self._page is not None and 0 <= index < len(self._page.tables):
            tables = list(self._page.tables)
            tables[index] = table
            self._page = self._page.with_updates(tables=tuple(tables))
            self._refresh_structure()
            self.table_combo.setCurrentIndex(index)
        self.table_edited.emit(index, table)

    # -- region results ---------------------------------------------------

    def set_region_mode(self, enabled: bool) -> None:
        """Let the user draw a rectangle to recognise instead of the whole page."""
        self.canvas.set_region_mode(enabled)
        if not enabled:
            self.show_region_result("")

    def region_mode(self) -> bool:
        return self.canvas.region_mode()

    def show_region_result(self, text: str, source: str = "") -> None:
        """Display text recognised from a selected region beside the transcript.

        `source` tells the user where the text came from, so a changed model
        is never silently ignored when the PDF already carried a text layer.
        """
        self.region_label.setPlainText(text)
        self.set_region_source(source)
        self.region_panel.setVisible(bool(text))

    def set_region_source(self, source: str) -> None:
        self.region_source_label.setText(source)
        self.region_source_label.setVisible(bool(source))

    def region_result(self) -> str:
        return self.region_label.toPlainText()

    def insert_region_result(self) -> None:
        """Put the region text into the transcript at the cursor."""
        text = self.region_result().strip()
        if text:
            self.editor.textCursor().insertText(text)
            self.editor.setFocus()

    def copy_region_result(self) -> None:
        QApplication.clipboard().setText(self.region_result())

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

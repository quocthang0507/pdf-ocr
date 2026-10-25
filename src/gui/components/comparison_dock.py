"""Side-by-side verification editor: original page against recognised text."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.constants import LOW_CONFIDENCE_COLOR, LOW_CONFIDENCE_THRESHOLD
from src.core.models import BoundingBox, OCRPage, OCRTable
from src.core.postprocessor import Postprocessor
from src.core.spell_corrector import VietnameseSpellCorrector
from src.gui.components.document_canvas import DocumentCanvas
from src.gui.components.transcript_renderer import (
    TextSpan,
    find_search_spans,
    match_block_for_table,
    match_table_for_block,
    render_page_transcript,
    summarize_page_structure,
)
from src.gui.dialogs.find_replace import FindReplaceDialog
from src.gui.dialogs.table_editor import TableEditorDialog

_MIN_PAGE_PANE_WIDTH = 240
_EVEN_SPLIT = 600
_REGION_RESULT_MAX_HEIGHT = 140
_SEARCH_HIGHLIGHT_COLOR = "#93c5fd"
_ZOOM_ACTIONS = {1: "zoom_in", -1: "zoom_out", 0: "reset_zoom"}


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
    page_rotate_requested = Signal(int)
    transcript_edited = Signal(str)
    transcript_copied = Signal()
    spell_correction_applied = Signal(bool)
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
        self._init_transcript_bar()
        self._init_region_panel()
        self._init_structure_panel()
        self._block_spans: tuple[TextSpan, ...] = ()
        self._uncertain_spans: tuple[TextSpan, ...] = ()
        self._search_spans: tuple[TextSpan, ...] = ()
        self._uncertain_index = -1
        self._page: OCRPage | None = None
        self._current_page = 0
        self._total_pages = 0
        self._confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD
        self._custom_dictionary: str = ""
        self._tone_style: str = "modern"
        self._init_nav_controls()

        self.table_editor: TableEditorDialog | None = None
        self.find_replace_dialog: FindReplaceDialog | None = None
        self._syncing = False
        self._shortcuts = self._create_shortcuts()
        self._build_layout()
        self._connect_signals()
        self._show_zoom(self.canvas.zoom_factor())
        self._update_word_count()

    def _init_transcript_bar(self) -> None:
        self.transcript_bar = QFrame(self)
        self.transcript_bar.setObjectName("transcript_bar")
        self.transcript_title_label = QLabel("Văn bản nhận diện", self.transcript_bar)
        self.transcript_title_label.setObjectName("transcript_title_label")
        self.word_count_label = QLabel("0 từ · 0 ký tự", self.transcript_bar)
        self.word_count_label.setObjectName("word_count_label")
        self.spell_fix_btn = QPushButton("Sửa chính tả", self.transcript_bar)
        self.spell_fix_btn.setObjectName("spell_fix_button")
        self.spell_fix_btn.setToolTip(
            "Sửa lỗi dấu thanh và từ ghép tiếng Việt theo ngữ cảnh (hỗ trợ Ctrl+Z)"
        )
        self.find_replace_btn = QPushButton("Tìm && Thay thế", self.transcript_bar)
        self.find_replace_btn.setObjectName("find_replace_button")
        self.find_replace_btn.setToolTip("Mở hộp thoại Tìm và thay thế (Ctrl+H)")
        self.copy_transcript_btn = QPushButton("Sao chép", self.transcript_bar)
        self.copy_transcript_btn.setObjectName("copy_transcript_button")
        self.copy_transcript_btn.setToolTip("Sao chép toàn bộ văn bản trang hiện tại")

    def _init_region_panel(self) -> None:
        self.region_panel = QFrame(self)
        self.region_panel.setObjectName("region_panel")
        self.region_title = QLabel("Kết quả vùng chọn", self.region_panel)
        self.region_title.setObjectName("region_title")
        self.region_copy_button = QPushButton("Sao chép", self.region_panel)
        self.region_copy_button.setObjectName("region_copy")
        self.region_insert_button = QPushButton("Chèn vào bản chép", self.region_panel)
        self.region_insert_button.setObjectName("region_insert")
        self.region_insert_button.setToolTip("Chèn kết quả vùng chọn vào bản chép")
        self.region_rerun_button = QPushButton("OCR bằng mô hình", self.region_panel)
        self.region_rerun_button.setObjectName("region_rerun")
        self.region_rerun_button.setToolTip("Nhận diện lại vùng này bằng mô hình")
        self.region_source_label = QLabel("", self.region_panel)
        self.region_source_label.setObjectName("region_source")
        self.region_source_label.setWordWrap(True)
        self.region_label = QPlainTextEdit(self.region_panel)
        self.region_label.setObjectName("region_result")
        self.region_label.setReadOnly(True)
        self.region_label.setMaximumHeight(_REGION_RESULT_MAX_HEIGHT)
        self.region_panel.hide()

    def _init_structure_panel(self) -> None:
        self.structure_panel = QFrame(self)
        self.structure_panel.setObjectName("structure_panel")
        self.structure_label = QLabel(self.structure_panel)
        self.structure_label.setObjectName("structure_summary")
        self.structure_label.setWordWrap(True)
        self.uncertain_prev_btn = QPushButton("◀ Từ nghi ngờ", self.structure_panel)
        self.uncertain_prev_btn.setObjectName("uncertain_prev_button")
        self.uncertain_prev_btn.setToolTip("Đi tới từ có độ tin cậy thấp phía trước")
        self.uncertain_next_btn = QPushButton("Từ nghi ngờ ▶", self.structure_panel)
        self.uncertain_next_btn.setObjectName("uncertain_next_button")
        self.uncertain_next_btn.setToolTip("Đi tới từ có độ tin cậy thấp tiếp theo")
        self.table_combo = QComboBox(self.structure_panel)
        self.table_combo.setObjectName("table_combo")
        self.table_combo.setToolTip("Chọn bảng biểu để xem trên trang")
        self.edit_table_button = QPushButton("Chỉnh sửa bảng…", self.structure_panel)
        self.edit_table_button.setObjectName("edit_table_button")
        self.edit_table_button.setToolTip(
            "Sửa từng ô của bảng trước khi xuất ra Excel/Word"
        )
        self.structure_panel.hide()

    def _init_nav_controls(self) -> None:
        self.prev_page_btn = QPushButton("◀", self)
        self.prev_page_btn.setObjectName("prev_page_button")
        self.prev_page_btn.setToolTip("Trang trước")
        self.prev_page_btn.setEnabled(False)
        self.page_spin = QSpinBox(self)
        self.page_spin.setObjectName("page_spin")
        self.page_spin.setToolTip("Đi tới trang")
        self.page_spin.setRange(0, 0)
        self.page_spin.setEnabled(False)
        self.page_spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.page_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_spin.setMinimumWidth(64)
        self.page_slider = QScrollBar(Qt.Orientation.Horizontal, self)
        self.page_slider.setObjectName("page_slider")
        self.page_slider.setToolTip("Cuộn để chuyển trang")
        self.page_slider.setRange(0, 0)
        self.page_slider.setEnabled(False)
        self.page_label = QLabel("/ 0", self)
        self.page_label.setObjectName("page_indicator")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_page_btn = QPushButton("▶", self)
        self.next_page_btn.setObjectName("next_page_button")
        self.next_page_btn.setToolTip("Trang sau")
        self.next_page_btn.setEnabled(False)
        self._init_zoom_and_rotate_controls()

    def _init_zoom_and_rotate_controls(self) -> None:
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
        self.rotate_left_btn = QPushButton("↺", self)
        self.rotate_left_btn.setObjectName("rotate_left_button")
        self.rotate_left_btn.setToolTip("Xoay trái 90°")
        self.rotate_right_btn = QPushButton("↻", self)
        self.rotate_right_btn.setObjectName("rotate_right_button")
        self.rotate_right_btn.setToolTip("Xoay phải 90°")
        for btn in (
            self.zoom_out_btn,
            self.zoom_in_btn,
            self.rotate_left_btn,
            self.rotate_right_btn,
        ):
            btn.setMinimumSize(30, 30)
        self.zoom_reset_btn = QPushButton("Vừa trang", self)
        self.zoom_reset_btn.setObjectName("zoom_reset_button")
        self.zoom_reset_btn.setToolTip("Hiển thị vừa toàn trang")
        self.fit_width_btn = QPushButton("Vừa ngang", self)
        self.fit_width_btn.setObjectName("fit_width_button")
        self.fit_width_btn.setToolTip("Hiển thị vừa chiều ngang khung nhìn")

    def _connect_signals(self) -> None:
        self.canvas.block_selected.connect(self._focus_text_block)
        self.canvas.block_activated.connect(self.edit_block_table)
        self.canvas.region_selected.connect(self.region_ocr_requested)
        self.canvas.page_step_requested.connect(self._on_page_step_requested)
        self.canvas.region_mode_cancelled.connect(self.region_mode_cancelled)
        self.canvas.zoom_changed.connect(self._show_zoom)
        self.editor.cursorPositionChanged.connect(self._focus_canvas_block)
        self.editor.textChanged.connect(self._on_editor_text_changed)
        self.prev_page_btn.clicked.connect(self._prev_page)
        self.next_page_btn.clicked.connect(self._next_page)
        self.page_spin.editingFinished.connect(self._jump_to_spin_page)
        self.page_slider.valueChanged.connect(self._jump_to_slider_page)
        self.zoom_in_btn.clicked.connect(self.canvas.zoom_in)
        self.zoom_out_btn.clicked.connect(self.canvas.zoom_out)
        self.zoom_reset_btn.clicked.connect(self.canvas.reset_zoom)
        self.fit_width_btn.clicked.connect(self.canvas.fit_width)
        self.rotate_left_btn.clicked.connect(
            lambda: self.page_rotate_requested.emit(-90)
        )
        self.rotate_right_btn.clicked.connect(
            lambda: self.page_rotate_requested.emit(90)
        )
        self.uncertain_prev_btn.clicked.connect(self.jump_to_prev_uncertain)
        self.uncertain_next_btn.clicked.connect(self.jump_to_next_uncertain)
        self.spell_fix_btn.clicked.connect(self.apply_spell_correction)
        self.find_replace_btn.clicked.connect(self.open_find_replace)
        self.copy_transcript_btn.clicked.connect(self.copy_transcript)

    def _build_layout(self) -> None:
        canvas_pane = QWidget(self)
        canvas_layout = QVBoxLayout(canvas_pane)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(4)
        canvas_layout.addWidget(self.canvas, 1)
        canvas_layout.addWidget(self._build_nav_bar(canvas_pane))

        bar_layout = QHBoxLayout(self.transcript_bar)
        bar_layout.setContentsMargins(10, 6, 10, 6)
        bar_layout.setSpacing(6)
        bar_layout.addWidget(self.transcript_title_label)
        bar_layout.addWidget(self.word_count_label)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.spell_fix_btn)
        bar_layout.addWidget(self.find_replace_btn)
        bar_layout.addWidget(self.copy_transcript_btn)

        text_pane = QWidget(self)
        text_layout = QVBoxLayout(text_pane)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        text_layout.addWidget(self.transcript_bar)
        text_layout.addWidget(self.editor, 1)
        text_layout.addWidget(self.structure_panel)
        text_layout.addWidget(self.region_panel)
        self._build_subpanels()

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("comparison_splitter")
        splitter.addWidget(canvas_pane)
        splitter.addWidget(text_pane)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([_EVEN_SPLIT, _EVEN_SPLIT])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _build_subpanels(self) -> None:
        structure_layout = QVBoxLayout(self.structure_panel)
        structure_layout.setContentsMargins(10, 6, 10, 6)
        structure_layout.setSpacing(4)
        structure_layout.addWidget(self.structure_label)
        structure_actions = QHBoxLayout()
        structure_actions.setContentsMargins(0, 0, 0, 0)
        structure_actions.setSpacing(6)
        structure_actions.addWidget(self.uncertain_prev_btn)
        structure_actions.addWidget(self.uncertain_next_btn)
        structure_actions.addStretch(1)
        structure_actions.addWidget(self.table_combo)
        structure_actions.addWidget(self.edit_table_button)
        structure_layout.addLayout(structure_actions)
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

    def _build_nav_bar(self, parent: QWidget) -> QFrame:
        nav_bar = QFrame(parent)
        nav_bar.setObjectName("nav_bar")
        nav_layout = QVBoxLayout(nav_bar)
        nav_layout.setContentsMargins(8, 4, 8, 4)
        nav_layout.setSpacing(4)
        zoom_row = QHBoxLayout()
        zoom_row.setContentsMargins(0, 0, 0, 0)
        zoom_row.setSpacing(6)
        zoom_row.addWidget(_group_label("Thu phóng", nav_bar))
        zoom_row.addWidget(self.zoom_out_btn)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self.zoom_in_btn)
        zoom_row.addWidget(self.zoom_reset_btn)
        zoom_row.addWidget(self.fit_width_btn)
        zoom_row.addWidget(_separator(nav_bar))
        zoom_row.addWidget(self.rotate_left_btn)
        zoom_row.addWidget(self.rotate_right_btn)
        zoom_row.addStretch(1)
        page_row = QHBoxLayout()
        page_row.setContentsMargins(0, 0, 0, 0)
        page_row.setSpacing(6)
        page_row.addWidget(_group_label("Trang", nav_bar))
        page_row.addWidget(self.prev_page_btn)
        page_row.addWidget(self.page_spin)
        page_row.addWidget(self.next_page_btn)
        page_row.addWidget(self.page_slider, 1)
        page_row.addWidget(self.page_label)
        nav_layout.addLayout(zoom_row)
        nav_layout.addLayout(page_row)
        return nav_bar

    def set_confidence_threshold(self, threshold: float) -> None:
        """Update the low-confidence warning threshold and re-highlight live."""
        self._confidence_threshold = float(threshold)
        if self._page is None:
            return
        _, _, self._uncertain_spans = render_page_transcript(
            self._page, confidence_threshold=self._confidence_threshold
        )
        self._uncertain_index = -1
        with self._suspend_sync():
            self._apply_extra_selections()
        self._refresh_structure()

    def set_spell_options(
        self, *, custom_dictionary: str = "", tone_style: str = "modern"
    ) -> None:
        """Configure user dictionary rules and Vietnamese tone placement style."""
        self._custom_dictionary = custom_dictionary
        self._tone_style = tone_style

    def apply_spell_correction(self) -> None:
        """Run contextual Vietnamese N-gram spell correction on the transcript."""
        current = self.editor.toPlainText()
        if not current.strip():
            self.spell_correction_applied.emit(False)
            return
        corrector = VietnameseSpellCorrector(custom_dictionary=self._custom_dictionary)
        processor = Postprocessor(corrector, tone_style=self._tone_style)
        corrected = processor.correct_text(current, spell_check=True)
        if corrected == current:
            self.spell_correction_applied.emit(False)
            return
        cursor = QTextCursor(self.editor.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(corrected)
        cursor.endEditBlock()
        self.spell_correction_applied.emit(True)

    def copy_transcript(self) -> None:
        """Copy the entire transcript text of the current page to the clipboard."""
        text = self.transcript()
        QApplication.clipboard().setText(text)
        self.transcript_copied.emit()

    def highlight_search_query(self, query: str) -> int:
        """Highlight all case-insensitive occurrences of `query` and focus the first."""
        spans = find_search_spans(self.editor.toPlainText(), query)
        self._search_spans = spans
        self._apply_extra_selections()
        if spans:
            self._select_uncertain_span(spans[0])
        return len(spans)

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
        self._uncertain_spans = ()
        self._search_spans = ()
        self._uncertain_index = -1
        self._page = None
        self.canvas.set_image(image)
        with self._suspend_sync():
            self.editor.setPlainText(text)
            self.editor.setExtraSelections([])
        self._update_word_count()
        self.region_panel.hide()
        self._refresh_structure()

    def set_page(self, page: OCRPage, image: np.ndarray) -> None:
        """Show one recognised page beside the image it was recognised from."""
        if not isinstance(page, OCRPage):
            raise ValueError("Dữ liệu trang phải là đối tượng OCRPage.")
        transcript, blocks, uncertain = render_page_transcript(
            page, confidence_threshold=self._confidence_threshold
        )
        self._block_spans = blocks

        self._uncertain_spans = uncertain
        self._search_spans = ()
        self._uncertain_index = -1
        self._page = page
        self.canvas.set_image(image)
        self.canvas.set_blocks(page.blocks)
        with self._suspend_sync():
            self.editor.setPlainText(transcript)
            self._apply_extra_selections()
        self._update_word_count()
        self.region_panel.hide()
        self._refresh_structure()

    def clear(self) -> None:
        """Drop both panes so the next document starts from an empty state."""
        self._block_spans = ()
        self._uncertain_spans = ()
        self._search_spans = ()
        self._uncertain_index = -1
        self._page = None
        self.table_editor = None
        self.set_page_info(0, 0)
        self.canvas.clear_page()
        with self._suspend_sync():
            self.editor.clear()
            self.editor.setExtraSelections([])
        self._update_word_count()
        self.region_label.clear()
        self.region_panel.hide()
        self._refresh_structure()

    def transcript(self) -> str:
        return self.editor.toPlainText()

    def apply_zoom(self, step: int) -> None:
        """Route a zoom command from the window to the page view."""
        getattr(self.canvas, _ZOOM_ACTIONS[step])()

    def uncertain_count(self) -> int:
        return len(self._uncertain_spans)

    def jump_to_next_uncertain(self) -> None:
        if not self._uncertain_spans:
            return
        self._uncertain_index = (self._uncertain_index + 1) % len(self._uncertain_spans)
        self._select_uncertain_span(self._uncertain_spans[self._uncertain_index])

    def jump_to_prev_uncertain(self) -> None:
        if not self._uncertain_spans:
            return
        self._uncertain_index = (self._uncertain_index - 1) % len(self._uncertain_spans)
        self._select_uncertain_span(self._uncertain_spans[self._uncertain_index])

    def _select_uncertain_span(self, span: TextSpan) -> None:
        cursor = self.editor.textCursor()
        cursor.setPosition(span.start)
        cursor.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        block_idx = self._block_at(span.start)
        if block_idx is not None:
            with self._suspend_sync():
                self.canvas.focus_on_block(block_idx)

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
        summary, table_labels = summarize_page_structure(
            page, len(self._uncertain_spans)
        )
        for label in table_labels:
            self.table_combo.addItem(label)
        self.table_combo.blockSignals(False)
        has_tables = bool(page.tables)
        has_uncertain = bool(self._uncertain_spans)
        self.table_combo.setVisible(has_tables)
        self.edit_table_button.setVisible(has_tables)
        self.uncertain_prev_btn.setVisible(has_uncertain)
        self.uncertain_next_btn.setVisible(has_uncertain)
        self.structure_label.setText(summary)
        self.structure_panel.show()

    def _show_table_on_canvas(self, position: int) -> None:
        """Highlight the table picked in the list on the page image."""
        block_index = self._block_for_table(position)
        if block_index is not None:
            self.canvas.focus_on_block(block_index)

    def _block_for_table(self, position: int) -> int | None:
        return match_block_for_table(self._page, position)

    def _table_for_block(self, index: int) -> int | None:
        """Match a table block to the extracted table drawn inside it."""
        return match_table_for_block(self._page, index)

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
        """Display text recognised from a selected region beside the transcript."""
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

    def _apply_extra_selections(self) -> None:
        selections: list[QTextEdit.ExtraSelection] = []
        warning = QTextCharFormat()
        warning.setBackground(QColor(LOW_CONFIDENCE_COLOR))
        for span in self._uncertain_spans:
            selections.append(self._make_selection(span, warning))
        search_fmt = QTextCharFormat()
        search_fmt.setBackground(QColor(_SEARCH_HIGHLIGHT_COLOR))
        search_fmt.setForeground(QColor("#0f172a"))
        for span in self._search_spans:
            selections.append(self._make_selection(span, search_fmt))
        self.editor.setExtraSelections(selections)

    def _make_selection(
        self, span: TextSpan, fmt: QTextCharFormat
    ) -> QTextEdit.ExtraSelection:
        selection = QTextEdit.ExtraSelection()
        selection.format = fmt
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(span.start)
        cursor.setPosition(span.end, QTextCursor.MoveMode.KeepAnchor)
        selection.cursor = cursor
        return selection

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

    def _on_editor_text_changed(self) -> None:
        self._update_word_count()
        if not self._syncing:
            self.transcript_edited.emit(self.transcript())

    def _update_word_count(self) -> None:
        text = self.editor.toPlainText()
        words = len(text.split()) if text.strip() else 0
        chars = len(text)
        self.word_count_label.setText(f"{words} từ · {chars} ký tự")
        has_text = bool(text.strip())
        self.spell_fix_btn.setEnabled(has_text)
        self.copy_transcript_btn.setEnabled(has_text)

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

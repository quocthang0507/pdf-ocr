"""Bulk-correcting repeated OCR mistakes stays accurate and undoable."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QTextEdit

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.dialogs.find_replace import FindReplaceDialog

pytestmark = pytest.mark.gui

SAMPLE = "Tôi đuợc mời. Bạn đuợc nghỉ. Họ ĐUỢC thưởng."


@pytest.fixture
def editor(qtbot) -> QTextEdit:
    widget = QTextEdit()
    widget.setPlainText(SAMPLE)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def dialog(qtbot, editor: QTextEdit) -> FindReplaceDialog:
    widget = FindReplaceDialog(editor)
    qtbot.addWidget(widget)
    return widget


def _search_for(dialog: FindReplaceDialog, text: str, replacement: str = "") -> None:
    dialog.find_edit.setText(text)
    dialog.replace_edit.setText(replacement)


def test_finding_moves_the_cursor_to_the_first_match(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc")

    assert dialog.find_next() is True
    assert editor.textCursor().selectedText() == "đuợc"


def test_finding_again_advances_to_the_next_match(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc")
    dialog.find_next()
    first = editor.textCursor().selectionStart()

    dialog.find_next()

    assert editor.textCursor().selectionStart() > first


def test_search_wraps_around_the_end_of_the_document(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc")
    dialog.find_next()
    first = editor.textCursor().selectionStart()
    for _ in range(SAMPLE.casefold().count("đuợc") - 1):
        dialog.find_next()

    dialog.find_next()

    assert editor.textCursor().selectionStart() == first
    assert "quay lại từ đầu" in dialog.status_label.text()


def test_a_missing_phrase_reports_no_match(dialog: FindReplaceDialog) -> None:
    _search_for(dialog, "không có trong văn bản")

    assert dialog.find_next() is False
    assert "Không tìm thấy" in dialog.status_label.text()


def test_search_ignores_case_by_default(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "ĐUỢC")
    dialog.find_next()

    assert editor.textCursor().selectedText() == "đuợc"


def test_case_sensitive_search_matches_exactly(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    dialog.case_sensitive_box.setChecked(True)
    _search_for(dialog, "ĐUỢC")

    assert dialog.find_next() is True
    assert editor.textCursor().selectedText() == "ĐUỢC"


def test_replacing_changes_only_the_current_match(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc", "được")
    dialog.find_next()

    dialog.replace_current()

    assert editor.toPlainText().count("được") == 1
    assert editor.toPlainText().count("đuợc") == 1


def test_replace_all_fixes_every_occurrence(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc", "được")

    replaced = dialog.replace_all()

    assert replaced == 3
    assert "đuợc" not in editor.toPlainText()
    assert editor.toPlainText().count("được") == 3


def test_replace_all_reports_how_many_were_changed(
    dialog: FindReplaceDialog,
) -> None:
    _search_for(dialog, "đuợc", "được")

    dialog.replace_all()

    assert "3" in dialog.status_label.text()


def test_replace_all_is_a_single_undo_step(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc", "được")
    dialog.replace_all()

    editor.undo()

    assert editor.toPlainText() == SAMPLE


def test_undoing_a_bulk_replace_can_be_redone(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc", "được")
    dialog.replace_all()
    editor.undo()

    editor.redo()

    assert "đuợc" not in editor.toPlainText()


def test_replace_all_with_an_empty_search_changes_nothing(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "", "được")

    assert dialog.replace_all() == 0
    assert editor.toPlainText() == SAMPLE


def test_a_replacement_containing_the_search_text_terminates(
    dialog: FindReplaceDialog, editor: QTextEdit
) -> None:
    _search_for(dialog, "đuợc", "đuợc rồi")

    replaced = dialog.replace_all()

    assert replaced == 3
    assert editor.toPlainText().count("đuợc rồi") == 3


# -- wired into the verification editor -------------------------------------


def _page() -> OCRPage:
    box = BoundingBox(10, 10, 400, 60)
    word = OCRWord("đuợc", box, 0.99)
    return OCRPage(
        page_number=1,
        width=600,
        height=800,
        blocks=(OCRBlock(lines=(OCRLine(words=(word,), bbox=box),), bbox=box),),
    )


@pytest.fixture
def dock(qtbot) -> ComparisonDock:
    widget = ComparisonDock()
    qtbot.addWidget(widget)
    widget.set_page(_page(), np.full((800, 600, 3), 250, dtype=np.uint8))
    return widget


def test_the_editor_opens_find_and_replace(dock: ComparisonDock) -> None:
    dock.open_find_replace()

    assert isinstance(dock.find_replace_dialog, FindReplaceDialog)
    assert dock.find_replace_dialog.isVisible() is True


def test_reopening_reuses_the_same_dialog(dock: ComparisonDock) -> None:
    dock.open_find_replace()
    first = dock.find_replace_dialog

    dock.open_find_replace()

    assert dock.find_replace_dialog is first


def test_the_shortcut_for_find_and_replace_is_registered(
    dock: ComparisonDock,
) -> None:
    shortcuts = {item.key().toString() for item in dock.editor_shortcuts()}

    assert "Ctrl+H" in shortcuts


def test_replacing_through_the_dock_updates_the_transcript(
    dock: ComparisonDock,
) -> None:
    dock.open_find_replace()
    dialog = dock.find_replace_dialog
    assert dialog is not None
    _search_for(dialog, "đuợc", "được")

    dialog.replace_all()

    assert dock.transcript() == "được"


def test_the_window_edit_menu_opens_find_and_replace(qtbot, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from src.gui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)

    window.command_actions["find_replace"].trigger()

    assert isinstance(window.comparison.find_replace_dialog, FindReplaceDialog)

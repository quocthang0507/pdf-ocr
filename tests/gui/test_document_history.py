"""Tests for the DocumentHistoryDialog component."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from src.gui.dialogs.document_history import DocumentHistoryDialog
from src.gui.styles.style_manager import status_error_color, status_success_color


@pytest.fixture
def sample_entries(tmp_path: Path) -> list[str]:
    f1 = tmp_path / "tai_lieu_1.pdf"
    f1.write_bytes(b"pdf data 1")
    f2 = tmp_path / "bao_cao_quy_3.pdf"
    f2.write_bytes(b"pdf data 2" * 50)
    missing = tmp_path / "khong_ton_tai.pdf"
    return [str(f1), str(f2), str(missing)]


def test_dialog_initializes_with_entries(
    sample_entries: list[str], qtbot: QtBot
) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 3
    item0 = dialog.table.item(0, 0)
    item1 = dialog.table.item(1, 0)
    item2 = dialog.table.item(2, 0)
    assert item0 is not None and item0.text() == "tai_lieu_1.pdf"
    assert item1 is not None and item1.text() == "bao_cao_quy_3.pdf"
    assert item2 is not None and item2.text() == "khong_ton_tai.pdf"

    # Check status column and theme-aware colors
    status0 = dialog.table.item(0, 4)
    status2 = dialog.table.item(2, 4)
    assert status0 is not None and status0.text() == "Tồn tại"
    assert status2 is not None and status2.text() == "Không tìm thấy"
    assert status0.foreground().color().name() == status_success_color().name()
    assert status2.foreground().color().name() == status_error_color().name()


def test_search_filter_narrows_table_rows(
    sample_entries: list[str], qtbot: QtBot
) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    dialog.search_input.setText("quy_3")
    assert dialog.table.rowCount() == 1
    item = dialog.table.item(0, 0)
    assert item is not None and item.text() == "bao_cao_quy_3.pdf"

    dialog.search_input.clear()
    assert dialog.table.rowCount() == 3


def test_button_states_update_on_selection(
    sample_entries: list[str], qtbot: QtBot
) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    # Initial state: nothing selected
    assert dialog.btn_open.isEnabled() is False
    assert dialog.btn_remove.isEnabled() is False
    assert dialog.btn_reveal.isEnabled() is False
    assert dialog.btn_clear.isEnabled() is True

    # Select row 0
    dialog.table.selectRow(0)
    assert dialog.btn_open.isEnabled() is True
    assert dialog.btn_remove.isEnabled() is True
    assert dialog.btn_reveal.isEnabled() is True


def test_open_selected_file(sample_entries: list[str], qtbot: QtBot) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(1)
    with qtbot.waitSignal(dialog.file_selected) as blocker:
        dialog.btn_open.click()

    assert blocker.args == [sample_entries[1]]


def test_double_click_opens_file(sample_entries: list[str], qtbot: QtBot) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    item = dialog.table.item(0, 0)
    assert item is not None
    with qtbot.waitSignal(dialog.file_selected) as blocker:
        dialog.table.itemDoubleClicked.emit(item)

    assert blocker.args == [sample_entries[0]]


def test_remove_selected_item(sample_entries: list[str], qtbot: QtBot) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    dialog.table.selectRow(0)
    with qtbot.waitSignal(dialog.item_removed) as blocker:
        dialog.btn_remove.click()

    assert blocker.args == [sample_entries[0]]
    assert dialog.table.rowCount() == 2


def test_clear_all_history(
    sample_entries: list[str], qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialog = DocumentHistoryDialog(sample_entries)
    qtbot.addWidget(dialog)

    # Automatically confirm the message box
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    with qtbot.waitSignal(dialog.history_cleared):
        dialog.btn_clear.click()

    assert dialog.table.rowCount() == 0
    assert dialog.btn_clear.isEnabled() is False

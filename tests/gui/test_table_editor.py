"""The table editor edits a grid and hands back a valid immutable OCRTable."""

from __future__ import annotations

import numpy as np
import pytest

from src.constants import BlockType
from src.core.models import (
    BoundingBox,
    OCRBlock,
    OCRLine,
    OCRPage,
    OCRTable,
    OCRWord,
    TableCellSpan,
)
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.dialogs.table_editor import TableEditorDialog

pytestmark = pytest.mark.gui


def _table() -> OCRTable:
    return OCRTable(
        rows=(
            ("Mặt hàng", "Số lượng", "Đơn giá"),
            ("Sách", "2", "50.000"),
            ("Bút", "10", "5.000"),
        ),
        bbox=BoundingBox(10, 10, 500, 300),
    )


@pytest.fixture
def editor(qtbot) -> TableEditorDialog:
    dialog = TableEditorDialog(_table())
    qtbot.addWidget(dialog)
    return dialog


def test_the_grid_mirrors_the_recognised_table(editor: TableEditorDialog) -> None:
    grid = editor.table_widget

    assert (grid.rowCount(), grid.columnCount()) == (3, 3)
    assert grid.item(0, 0).text() == "Mặt hàng"
    assert grid.item(2, 2).text() == "5.000"


def test_editing_a_cell_reaches_the_returned_table(editor: TableEditorDialog) -> None:
    editor.table_widget.item(1, 2).setText("55.000")

    assert editor.updated_table().rows[1] == ("Sách", "2", "55.000")


def test_the_original_table_is_never_mutated(editor: TableEditorDialog) -> None:
    original = _table()
    editor.table_widget.item(0, 0).setText("Đã sửa")

    assert editor.updated_table() is not original
    assert original.rows[0][0] == "Mặt hàng"


def test_adding_a_row_appends_empty_cells(editor: TableEditorDialog) -> None:
    editor.add_row()

    updated = editor.updated_table()
    assert len(updated.rows) == 4
    assert updated.rows[3] == ("", "", "")


def test_adding_a_column_widens_every_row(editor: TableEditorDialog) -> None:
    editor.add_column()

    updated = editor.updated_table()
    assert all(len(row) == 4 for row in updated.rows)


def test_removing_the_selected_row_drops_it(editor: TableEditorDialog) -> None:
    editor.table_widget.setCurrentCell(1, 0)

    editor.remove_row()

    assert editor.updated_table().rows == (
        ("Mặt hàng", "Số lượng", "Đơn giá"),
        ("Bút", "10", "5.000"),
    )


def test_removing_the_selected_column_drops_it(editor: TableEditorDialog) -> None:
    editor.table_widget.setCurrentCell(0, 1)

    editor.remove_column()

    assert editor.updated_table().rows[0] == ("Mặt hàng", "Đơn giá")


def test_the_last_row_and_column_cannot_be_removed(qtbot) -> None:
    dialog = TableEditorDialog(
        OCRTable(rows=(("Chỉ một ô",),), bbox=BoundingBox(0, 0, 100, 40))
    )
    qtbot.addWidget(dialog)

    dialog.remove_row()
    dialog.remove_column()

    assert dialog.updated_table().rows == (("Chỉ một ô",),)


def test_merged_cells_outside_the_new_shape_are_dropped(qtbot) -> None:
    merged = OCRTable(
        rows=(("Tiêu đề", "", ""), ("A", "B", "C")),
        bbox=BoundingBox(0, 0, 300, 120),
        merged_cells=(TableCellSpan(0, 0, 1, 3),),
    )
    dialog = TableEditorDialog(merged)
    qtbot.addWidget(dialog)

    dialog.table_widget.setCurrentCell(0, 2)
    dialog.remove_column()

    assert dialog.updated_table().merged_cells == ()


def test_merged_cells_that_still_fit_are_kept(qtbot) -> None:
    merged = OCRTable(
        rows=(("Tiêu đề", "", ""), ("A", "B", "C")),
        bbox=BoundingBox(0, 0, 300, 120),
        merged_cells=(TableCellSpan(0, 0, 1, 2),),
    )
    dialog = TableEditorDialog(merged)
    qtbot.addWidget(dialog)

    dialog.add_row()

    assert dialog.updated_table().merged_cells == (TableCellSpan(0, 0, 1, 2),)


def test_accepting_publishes_the_edited_table(editor: TableEditorDialog, qtbot) -> None:
    editor.table_widget.item(2, 1).setText("12")

    with qtbot.waitSignal(editor.table_committed) as blocker:
        editor.accept()

    assert blocker.args[0].rows[2] == ("Bút", "12", "5.000")


def test_the_page_geometry_is_carried_through(editor: TableEditorDialog) -> None:
    assert editor.updated_table().bbox == _table().bbox


def test_a_non_table_input_is_refused() -> None:
    with pytest.raises(ValueError, match="OCRTable"):
        TableEditorDialog("không phải bảng")  # type: ignore[arg-type]


# -- opening the editor from the page ---------------------------------------


def _page_with_table() -> OCRPage:
    box = BoundingBox(20, 200, 400, 340)
    block = OCRBlock(
        lines=(OCRLine(words=(OCRWord("Bảng", box, 0.95),), bbox=box),),
        bbox=box,
        block_type=BlockType.TABLE,
    )
    text_box = BoundingBox(20, 20, 400, 80)
    heading = OCRBlock(
        lines=(OCRLine(words=(OCRWord("Báo cáo", text_box, 0.99),), bbox=text_box),),
        bbox=text_box,
        block_type=BlockType.TITLE,
    )
    return OCRPage(
        page_number=1,
        width=600,
        height=800,
        blocks=(heading, block),
        tables=(OCRTable(rows=(("A", "B"), ("1", "2")), bbox=box),),
    )


@pytest.fixture
def dock(qtbot) -> ComparisonDock:
    widget = ComparisonDock()
    qtbot.addWidget(widget)
    widget.set_page(_page_with_table(), np.full((800, 600, 3), 250, dtype=np.uint8))
    return widget


def test_double_clicking_a_table_block_opens_the_editor(dock: ComparisonDock) -> None:
    dock.canvas.block_activated.emit(1)

    assert isinstance(dock.table_editor, TableEditorDialog)
    assert dock.table_editor.updated_table().rows == (("A", "B"), ("1", "2"))


def test_double_clicking_a_text_block_opens_nothing(dock: ComparisonDock) -> None:
    dock.canvas.block_activated.emit(0)

    assert dock.table_editor is None


def test_committing_the_edited_table_reaches_the_page_owner(
    dock: ComparisonDock, qtbot
) -> None:
    dock.canvas.block_activated.emit(1)
    editor = dock.table_editor
    assert editor is not None
    editor.table_widget.item(1, 1).setText("22")

    with qtbot.waitSignal(dock.table_edited) as blocker:
        editor.accept()

    index, table = blocker.args
    assert index == 0
    assert table.rows[1] == ("1", "22")


def test_double_clicking_a_block_on_the_canvas_announces_it(qtbot) -> None:
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from src.gui.components.document_canvas import DocumentCanvas

    canvas = DocumentCanvas()
    canvas.resize(400, 300)
    qtbot.addWidget(canvas)
    page = _page_with_table()
    canvas.set_image(np.full((800, 600, 3), 250, dtype=np.uint8))
    canvas.set_blocks(page.blocks)
    canvas.select_block(1)
    position = QPointF(canvas.viewport().rect().center())
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick,
        position,
        canvas.viewport().mapToGlobal(position),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    with qtbot.waitSignal(canvas.block_activated) as blocker:
        canvas.mouseDoubleClickEvent(event)

    assert blocker.args == [1]


def test_the_editor_opens_wide_enough_to_show_every_column(qtbot) -> None:
    dialog = TableEditorDialog(_table())
    qtbot.addWidget(dialog)
    grid = dialog.table_widget
    columns = sum(grid.columnWidth(column) for column in range(grid.columnCount()))

    assert dialog.width() >= columns + grid.verticalHeader().width()

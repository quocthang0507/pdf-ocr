"""Interactive grid editor for one recognised table, before it is exported."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.models import OCRTable, TableCellSpan


def _spans_that_still_fit(
    spans: tuple[TableCellSpan, ...], rows: int, columns: int
) -> tuple[TableCellSpan, ...]:
    """Drop merges the user's edit pushed outside the new table shape."""
    return tuple(
        span
        for span in spans
        if span.row + span.row_span <= rows
        and span.column + span.column_span <= columns
    )


class TableEditorDialog(QDialog):
    """Stateful grid editor; the source table is read once and never mutated."""

    table_committed = Signal(OCRTable)

    def __init__(self, table: OCRTable, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if not isinstance(table, OCRTable):
            raise ValueError("Dữ liệu bảng phải là đối tượng OCRTable.")
        self.setObjectName("table_editor_dialog")
        self.setWindowTitle("Chỉnh sửa bảng biểu")
        self._source = table
        self.table_widget = QTableWidget(self)
        self.table_widget.setObjectName("table_grid")
        self._fill_grid(table)
        self._build_layout()

    def _fill_grid(self, table: OCRTable) -> None:
        columns = len(table.rows[0]) if table.rows else 1
        self.table_widget.setRowCount(len(table.rows) or 1)
        self.table_widget.setColumnCount(columns)
        for row_index, row in enumerate(table.rows):
            for column_index, cell in enumerate(row):
                self.table_widget.setItem(
                    row_index, column_index, QTableWidgetItem(cell)
                )
        self._fill_blanks()

    def _fill_blanks(self) -> None:
        """Qt leaves new cells empty; every cell must carry an editable item."""
        for row in range(self.table_widget.rowCount()):
            for column in range(self.table_widget.columnCount()):
                if self.table_widget.item(row, column) is None:
                    self.table_widget.setItem(row, column, QTableWidgetItem(""))

    def _build_layout(self) -> None:
        controls = QHBoxLayout()
        for label, handler, name in (
            ("Thêm dòng", self.add_row, "add_row"),
            ("Xóa dòng", self.remove_row, "remove_row"),
            ("Thêm cột", self.add_column, "add_column"),
            ("Xóa cột", self.remove_column, "remove_column"),
        ):
            button = QPushButton(label, self)
            button.setObjectName(f"button_{name}")
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table_widget)
        layout.addWidget(buttons)

    # -- grid commands ----------------------------------------------------

    def add_row(self) -> None:
        self.table_widget.insertRow(self.table_widget.rowCount())
        self._fill_blanks()

    def add_column(self) -> None:
        self.table_widget.insertColumn(self.table_widget.columnCount())
        self._fill_blanks()

    def remove_row(self) -> None:
        """Keep at least one row so the table stays a valid rectangle."""
        if self.table_widget.rowCount() <= 1:
            return
        self.table_widget.removeRow(max(self.table_widget.currentRow(), 0))

    def remove_column(self) -> None:
        if self.table_widget.columnCount() <= 1:
            return
        self.table_widget.removeColumn(max(self.table_widget.currentColumn(), 0))

    # -- result -----------------------------------------------------------

    def updated_table(self) -> OCRTable:
        """Build a new immutable table from the grid, keeping the page geometry."""
        rows = tuple(
            tuple(
                self._cell_text(row, column)
                for column in range(self.table_widget.columnCount())
            )
            for row in range(self.table_widget.rowCount())
        )
        return self._source.with_updates(
            rows=rows,
            merged_cells=_spans_that_still_fit(
                self._source.merged_cells,
                len(rows),
                len(rows[0]) if rows else 0,
            ),
        )

    def _cell_text(self, row: int, column: int) -> str:
        item = self.table_widget.item(row, column)
        return "" if item is None else item.text()

    def accept(self) -> None:
        self.table_committed.emit(self.updated_table())
        super().accept()

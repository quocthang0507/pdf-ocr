"""A layout that places widgets left to right and wraps them onto new rows.

A plain row of buttons demands its full width, which can push a narrow
window's right edge off the screen; this one only needs its widest item.
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    """Stateful wrapping row; each item keeps its preferred size."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802
        width = sum(item.sizeHint().width() for item in self._visible())
        width += self.spacing() * max(len(self._visible()) - 1, 0)
        height = max((item.sizeHint().height() for item in self._visible()), default=0)
        return QSize(width, height).grownBy(self.contentsMargins())

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._visible():
            size = size.expandedTo(item.minimumSize())
        return size.grownBy(self.contentsMargins())

    def _visible(self) -> list[QLayoutItem]:
        return [item for item in self._items if not item.isEmpty()]

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        margins: QMargins = self.contentsMargins()
        area = rect.marginsRemoved(margins)
        x, y, row_height = area.x(), area.y(), 0
        for item in self._visible():
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x = area.x()
                y += row_height + self.spacing()
                row_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()

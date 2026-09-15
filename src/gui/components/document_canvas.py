"""Interactive page viewer: free zoom, drag panning, and selectable blocks."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

from src.constants import BLOCK_TYPE_COLORS, SELECTION_COLOR
from src.core.models import OCRBlock
from src.utils.image_utils import ndarray_to_qimage

MIN_ZOOM = 0.05
MAX_ZOOM = 40.0
ZOOM_STEP = 1.25
_OUTLINE_WIDTH = 2.0
_SELECTED_WIDTH = 3.0
_FILL_ALPHA = 38


class BlockItem(QGraphicsRectItem):
    """One layout block drawn in page pixel coordinates and selectable by click."""

    def __init__(self, index: int, block: OCRBlock) -> None:
        bbox = block.bbox
        super().__init__(
            QRectF(bbox.x1, bbox.y1, bbox.width, bbox.height),
        )
        self.index = index
        self.block_type = block.block_type
        self._colour = QColor(BLOCK_TYPE_COLORS[block.block_type])
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setToolTip(block.text)
        self.setZValue(1)
        self._apply_style(selected=False)

    def _apply_style(self, *, selected: bool) -> None:
        colour = QColor(SELECTION_COLOR) if selected else self._colour
        width = _SELECTED_WIDTH if selected else _OUTLINE_WIDTH
        pen = QPen(colour, width)
        pen.setCosmetic(True)
        self.setPen(pen)
        fill = QColor(colour)
        fill.setAlpha(_FILL_ALPHA if selected else 0)
        self.setBrush(QBrush(fill))

    def itemChange(  # noqa: N802 - Qt override
        self, change: QGraphicsItem.GraphicsItemChange, value: object
    ) -> object:
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._apply_style(selected=bool(value))
        return super().itemChange(change, value)

    def outline_color(self) -> QColor:
        return QColor(self._colour)


class DocumentCanvas(QGraphicsView):
    """Stateful page view; geometry always stays in source-image pixel space.

    The view keeps its own zoom factor instead of reading the transform back,
    so clamping stays exact after many wheel steps.
    """

    block_selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("document_canvas")
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_item: QGraphicsPixmapItem | None = None
        self._block_items: list[BlockItem] = []
        self._zoom = 1.0
        self.scene().selectionChanged.connect(self._publish_selection)

    # -- page content -----------------------------------------------------

    def set_image(self, image: np.ndarray) -> None:
        """Replace the displayed page; blocks from the previous page are dropped."""
        pixmap = QPixmap.fromImage(ndarray_to_qimage(image))
        self.clear_page()
        self._page_item = self.scene().addPixmap(pixmap)
        self._page_item.setZValue(0)
        self.scene().setSceneRect(QRectF(pixmap.rect()))
        self.reset_zoom()

    def set_blocks(self, blocks: Sequence[OCRBlock]) -> None:
        """Draw layout boxes over the current page, colour coded by block type."""
        if self._page_item is None:
            raise ValueError("Cần nạp trang tài liệu trước khi vẽ khối bố cục.")
        self._remove_block_items()
        for index, block in enumerate(blocks):
            if not isinstance(block, OCRBlock):
                raise ValueError("Danh sách khối phải chứa đối tượng OCRBlock.")
            item = BlockItem(index, block)
            self.scene().addItem(item)
            self._block_items.append(item)

    def clear_page(self) -> None:
        """Drop every page item so a new document starts from a clean scene."""
        self._remove_block_items()
        self.scene().clear()
        self._page_item = None
        self.scene().setSceneRect(QRectF())

    def block_items(self) -> list[BlockItem]:
        return list(self._block_items)

    def page_size(self) -> QSizeF:
        if self._page_item is None:
            return QSizeF()
        return self._page_item.boundingRect().size()

    def _remove_block_items(self) -> None:
        for item in self._block_items:
            self.scene().removeItem(item)
        self._block_items.clear()

    # -- selection --------------------------------------------------------

    def selected_block(self) -> int | None:
        for item in self._block_items:
            if item.isSelected():
                return item.index
        return None

    def select_block(self, index: int) -> None:
        """Select exactly one block; unknown indexes clear the selection."""
        self.scene().clearSelection()
        if 0 <= index < len(self._block_items):
            self._block_items[index].setSelected(True)

    def focus_on_block(self, index: int) -> None:
        """Scroll the selected block into view without changing the zoom factor."""
        if not 0 <= index < len(self._block_items):
            return
        self.select_block(index)
        self.ensureVisible(self._block_items[index], 40, 40)

    def _publish_selection(self) -> None:
        index = self.selected_block()
        if index is not None:
            self.block_selected.emit(index)

    # -- zoom and pan -----------------------------------------------------

    def zoom_factor(self) -> float:
        return self._zoom

    def zoom_in(self) -> None:
        self._apply_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self._apply_zoom(self._zoom / ZOOM_STEP)

    def reset_zoom(self) -> None:
        """Fit the whole page in the viewport, the most useful default view."""
        if self._page_item is None:
            self._apply_zoom(1.0)
            return
        page = self._page_item.boundingRect()
        viewport = self.viewport().rect()
        if page.isEmpty() or viewport.isEmpty():
            self._apply_zoom(1.0)
            return
        self._apply_zoom(
            min(viewport.width() / page.width(), viewport.height() / page.height())
        )

    def _apply_zoom(self, factor: float) -> None:
        self._zoom = min(max(factor, MIN_ZOOM), MAX_ZOOM)
        self.setTransform(QTransform.fromScale(self._zoom, self._zoom))

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        steps = event.angleDelta().y()
        if steps == 0:
            super().wheelEvent(event)
            return
        self._apply_zoom(self._zoom * (ZOOM_STEP ** (steps / 120)))
        event.accept()

"""Interactive page viewer: free zoom, drag panning, and selectable blocks."""

from __future__ import annotations

import time
from collections.abc import Sequence

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QMouseEvent,
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
from src.core.models import BoundingBox, OCRBlock
from src.utils.image_utils import ndarray_to_qimage

MIN_ZOOM = 0.05
MAX_ZOOM = 40.0
ZOOM_STEP = 1.25
_OUTLINE_WIDTH = 2.0
_SELECTED_WIDTH = 3.0
_FILL_ALPHA = 38
_REGION_ALPHA = 28
_MIN_REGION_PIXELS = 4.0


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
    block_activated = Signal(int)
    region_selected = Signal(BoundingBox)
    zoom_changed = Signal(float)
    page_step_requested = Signal(int)
    region_mode_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("document_canvas")
        self.setScene(QGraphicsScene(self))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_item: QGraphicsPixmapItem | None = None
        self._block_items: list[BlockItem] = []
        self._region_item: QGraphicsRectItem | None = None
        self._region_origin: QPointF | None = None
        self._region_mode = False
        self._blocks_visible = True
        self._zoom = 1.0
        self._last_page_step_time = 0.0
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
            item.setVisible(self._blocks_visible)
            self.scene().addItem(item)
            self._block_items.append(item)

    def set_blocks_visible(self, visible: bool) -> None:
        """Show or hide the layout frames, remembering it for the next page."""
        self._blocks_visible = visible
        for item in self._block_items:
            item.setVisible(visible)

    def blocks_visible(self) -> bool:
        return self._blocks_visible

    def clear_page(self) -> None:
        """Drop every page item so a new document starts from a clean scene."""
        self._remove_block_items()
        self._region_item = None
        self._region_origin = None
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

    # -- region selection -------------------------------------------------

    def region_mode(self) -> bool:
        return self._region_mode

    def set_region_mode(self, enabled: bool) -> None:
        """Swap panning for rectangle drawing, and clear any previous region."""
        self._region_mode = enabled
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag
            if enabled
            else QGraphicsView.DragMode.ScrollHandDrag
        )
        self.setCursor(
            Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.clear_region()

    def selected_region(self) -> BoundingBox | None:
        """The drawn rectangle in page pixels, or None when nothing is drawn."""
        if self._region_item is None:
            return None
        rect = self._region_item.rect()
        return BoundingBox(rect.left(), rect.top(), rect.right(), rect.bottom())

    def region_item(self) -> QGraphicsRectItem | None:
        return self._region_item

    def clear_region(self) -> None:
        if self._region_item is not None:
            self.scene().removeItem(self._region_item)
        self._region_item = None
        self._region_origin = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._region_mode or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        self.clear_region()
        self._region_origin = self.mapToScene(event.position().toPoint())
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._region_origin is None:
            super().mouseMoveEvent(event)
            return
        self._draw_region(self.mapToScene(event.position().toPoint()))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._region_origin is None:
            super().mouseReleaseEvent(event)
            return
        rect = self._draw_region(self.mapToScene(event.position().toPoint()))
        self._region_origin = None
        event.accept()
        if rect.width() < _MIN_REGION_PIXELS or rect.height() < _MIN_REGION_PIXELS:
            self.clear_region()
            return
        region = self.selected_region()
        if region is not None:
            self.region_selected.emit(region)

    def _draw_region(self, corner: QPointF) -> QRectF:
        """Keep the rubber band inside the page, whichever way the user drags."""
        origin = self._region_origin or corner
        rect = QRectF(origin, corner).normalized().intersected(self._page_rect())
        if self._region_item is None:
            self._region_item = self.scene().addRect(rect, *_region_style())
            self._region_item.setZValue(2)
        else:
            self._region_item.setRect(rect)
        return rect

    def _page_rect(self) -> QRectF:
        if self._page_item is None:
            return QRectF()
        return self._page_item.boundingRect()

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

    def fit_page(self) -> None:
        """Fit the entire page within the viewport."""
        self.reset_zoom()

    def fit_width(self) -> None:
        """Fit the page width to the viewport width for comfortable reading."""
        if self._page_item is None:
            self._apply_zoom(1.0)
            return
        page = self._page_item.boundingRect()
        viewport = self.viewport().rect()
        if page.isEmpty() or viewport.isEmpty():
            self._apply_zoom(1.0)
            return
        self._apply_zoom(viewport.width() / page.width())

    def _apply_zoom(self, factor: float) -> None:
        self._zoom = min(max(factor, MIN_ZOOM), MAX_ZOOM)
        self.setTransform(QTransform.fromScale(self._zoom, self._zoom))
        self.zoom_changed.emit(self._zoom)

    def mouseDoubleClickEvent(  # noqa: N802 - Qt override
        self, event: QMouseEvent
    ) -> None:
        """A double click asks to work on the block under the cursor."""
        super().mouseDoubleClickEvent(event)
        index = self.selected_block()
        if index is not None:
            self.block_activated.emit(index)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt override
        if event.key() == Qt.Key.Key_Escape and self._region_mode:
            self.set_region_mode(False)
            self.region_mode_cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 - Qt override
        steps = event.angleDelta().y()
        if steps == 0:
            super().wheelEvent(event)
            return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._apply_zoom(self._zoom * (ZOOM_STEP ** (steps / 120)))
            event.accept()
            return

        v_bar = self.verticalScrollBar()
        at_bottom = v_bar.value() >= v_bar.maximum()
        at_top = v_bar.value() <= v_bar.minimum()

        current_time = time.monotonic()
        if current_time - self._last_page_step_time > 0.35:
            if steps < 0 and at_bottom:
                self._last_page_step_time = current_time
                self.page_step_requested.emit(1)
                event.accept()
                return
            if steps > 0 and at_top:
                self._last_page_step_time = current_time
                self.page_step_requested.emit(-1)
                event.accept()
                return

        super().wheelEvent(event)


def _region_style() -> tuple[QPen, QBrush]:
    """Dashed outline with a light wash, so the page stays readable underneath."""
    pen = QPen(QColor(SELECTION_COLOR), _SELECTED_WIDTH)
    pen.setCosmetic(True)
    pen.setStyle(Qt.PenStyle.DashLine)
    fill = QColor(SELECTION_COLOR)
    fill.setAlpha(_REGION_ALPHA)
    return pen, QBrush(fill)

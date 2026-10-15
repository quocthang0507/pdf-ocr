"""The canvas shows a page, zooms and pans freely, and selects layout blocks."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from src.constants import BLOCK_TYPE_COLORS, BlockType
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.components.document_canvas import (
    MAX_ZOOM,
    MIN_ZOOM,
    BlockItem,
    DocumentCanvas,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def canvas(qtbot) -> DocumentCanvas:
    view = DocumentCanvas()
    view.resize(400, 300)
    qtbot.addWidget(view)
    return view


def _image(width: int = 600, height: int = 800) -> np.ndarray:
    return np.full((height, width, 3), 240, dtype=np.uint8)


def _block(
    text: str, box: tuple[float, float, float, float], kind: BlockType
) -> OCRBlock:
    bbox = BoundingBox(*box)
    word = OCRWord(text=text, bbox=bbox, confidence=0.9)
    return OCRBlock(
        lines=(OCRLine(words=(word,), bbox=bbox),), bbox=bbox, block_type=kind
    )


def _page() -> OCRPage:
    return OCRPage(
        page_number=1,
        width=600,
        height=800,
        blocks=(
            _block("Tiêu đề", (20, 20, 560, 90), BlockType.TITLE),
            _block("Nội dung", (20, 120, 560, 400), BlockType.TEXT),
            _block("Bảng", (20, 430, 560, 700), BlockType.TABLE),
        ),
    )


def _wheel(
    canvas: DocumentCanvas,
    steps: int,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> QWheelEvent:
    position = QPointF(canvas.viewport().rect().center())
    return QWheelEvent(
        position,
        canvas.viewport().mapToGlobal(position),
        QPoint(0, 0),
        QPoint(0, 120 * steps),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_page_image_is_shown_at_its_pixel_size(canvas: DocumentCanvas) -> None:
    canvas.set_image(_image(640, 480))

    assert canvas.page_size().width() == 640
    assert canvas.page_size().height() == 480


def test_blocks_are_drawn_with_a_distinct_colour_per_type(
    canvas: DocumentCanvas,
) -> None:
    canvas.set_image(_image())
    canvas.set_blocks(_page().blocks)

    items = canvas.block_items()
    colours = [item.pen().color().name() for item in items]
    assert len(items) == 3
    assert colours[0] == BLOCK_TYPE_COLORS[BlockType.TITLE]
    assert colours[2] == BLOCK_TYPE_COLORS[BlockType.TABLE]
    assert len(set(colours)) == 3


def test_block_rectangles_match_the_recognised_geometry(
    canvas: DocumentCanvas,
) -> None:
    page = _page()
    canvas.set_image(_image())
    canvas.set_blocks(page.blocks)

    first = canvas.block_items()[0].rect()
    assert (first.x(), first.y()) == (20, 20)
    assert (first.width(), first.height()) == (540, 70)


def test_ctrl_wheel_zooms_in_and_out_around_the_cursor(
    canvas: DocumentCanvas,
) -> None:
    canvas.set_image(_image())
    canvas.reset_zoom()
    start = canvas.zoom_factor()

    canvas.wheelEvent(_wheel(canvas, 1, Qt.KeyboardModifier.ControlModifier))
    zoomed_in = canvas.zoom_factor()
    canvas.wheelEvent(_wheel(canvas, -1, Qt.KeyboardModifier.ControlModifier))

    assert zoomed_in > start
    assert canvas.zoom_factor() == pytest.approx(start, rel=1e-6)


def test_wheel_without_ctrl_requests_page_step_at_boundary(
    canvas: DocumentCanvas, qtbot
) -> None:
    canvas.set_image(_image())
    canvas.reset_zoom()
    canvas.verticalScrollBar().setValue(canvas.verticalScrollBar().maximum())

    with qtbot.waitSignal(canvas.page_step_requested) as blocker:
        canvas.wheelEvent(_wheel(canvas, -1))
    assert blocker.args == [1]

    canvas.verticalScrollBar().setValue(canvas.verticalScrollBar().minimum())
    canvas._last_page_step_time = 0.0
    with qtbot.waitSignal(canvas.page_step_requested) as blocker:
        canvas.wheelEvent(_wheel(canvas, 1))
    assert blocker.args == [-1]


def test_escape_cancels_region_mode(canvas: DocumentCanvas, qtbot) -> None:
    canvas.set_region_mode(True)
    assert canvas.region_mode() is True

    from PySide6.QtGui import QKeyEvent

    escape_event = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    with qtbot.waitSignal(canvas.region_mode_cancelled):
        canvas.keyPressEvent(escape_event)

    assert canvas.region_mode() is False


def test_zoom_is_clamped_to_a_usable_range(canvas: DocumentCanvas) -> None:
    canvas.set_image(_image())

    for _ in range(80):
        canvas.zoom_in()
    assert canvas.zoom_factor() == pytest.approx(MAX_ZOOM)

    for _ in range(200):
        canvas.zoom_out()
    assert canvas.zoom_factor() == pytest.approx(MIN_ZOOM)


def test_reset_zoom_fits_the_whole_page_in_the_viewport(
    canvas: DocumentCanvas,
) -> None:
    canvas.set_image(_image(1200, 1600))
    canvas.zoom_in()

    canvas.reset_zoom()

    viewport = canvas.viewport().size()
    assert canvas.zoom_factor() * 1200 <= viewport.width() + 1
    assert canvas.zoom_factor() * 1600 <= viewport.height() + 1


def test_panning_uses_drag_scrolling(canvas: DocumentCanvas) -> None:
    assert canvas.dragMode() == DocumentCanvas.DragMode.ScrollHandDrag


def test_clicking_a_block_announces_its_reading_index(
    canvas: DocumentCanvas, qtbot
) -> None:
    canvas.set_image(_image())
    canvas.set_blocks(_page().blocks)

    with qtbot.waitSignal(canvas.block_selected) as blocker:
        canvas.select_block(2)

    assert blocker.args == [2]
    assert canvas.selected_block() == 2


def test_selection_highlights_only_the_active_block(canvas: DocumentCanvas) -> None:
    canvas.set_image(_image())
    canvas.set_blocks(_page().blocks)

    canvas.select_block(1)

    highlighted = [item.isSelected() for item in canvas.block_items()]
    assert highlighted == [False, True, False]


def test_block_item_click_selects_it_on_the_canvas(
    canvas: DocumentCanvas, qtbot
) -> None:
    canvas.set_image(_image())
    canvas.set_blocks(_page().blocks)
    item: BlockItem = canvas.block_items()[1]

    with qtbot.waitSignal(canvas.block_selected) as blocker:
        canvas.scene().clearSelection()
        item.setSelected(True)

    assert blocker.args == [1]


def test_focusing_a_block_brings_it_into_view(canvas: DocumentCanvas) -> None:
    canvas.set_image(_image())
    canvas.set_blocks(_page().blocks)
    canvas.reset_zoom()

    canvas.focus_on_block(2)

    visible = canvas.mapToScene(canvas.viewport().rect()).boundingRect()
    assert visible.intersects(canvas.block_items()[2].rect())


def test_clearing_removes_every_page_item(canvas: DocumentCanvas) -> None:
    canvas.set_image(_image())
    canvas.set_blocks(_page().blocks)

    canvas.clear_page()

    assert canvas.block_items() == []
    assert canvas.selected_block() is None
    assert canvas.page_size().isEmpty()


def test_setting_blocks_without_a_page_is_rejected(canvas: DocumentCanvas) -> None:
    with pytest.raises(ValueError, match="trang tài liệu"):
        canvas.set_blocks(_page().blocks)

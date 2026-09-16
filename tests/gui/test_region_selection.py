"""Drawing a region on the page limits OCR to that rectangle."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QGraphicsView

from src.core.models import BoundingBox
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.components.document_canvas import DocumentCanvas

pytestmark = pytest.mark.gui


@pytest.fixture
def canvas(qtbot) -> DocumentCanvas:
    view = DocumentCanvas()
    view.resize(400, 300)
    qtbot.addWidget(view)
    view.set_image(np.full((800, 600, 3), 245, dtype=np.uint8))
    return view


def _mouse(
    canvas: DocumentCanvas, kind: QMouseEvent.Type, point: QPoint
) -> QMouseEvent:
    position = QPointF(point)
    return QMouseEvent(
        kind,
        position,
        canvas.viewport().mapToGlobal(position),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag(canvas: DocumentCanvas, start: QPoint, end: QPoint) -> None:
    canvas.mousePressEvent(_mouse(canvas, QMouseEvent.Type.MouseButtonPress, start))
    canvas.mouseMoveEvent(_mouse(canvas, QMouseEvent.Type.MouseMove, end))
    canvas.mouseReleaseEvent(_mouse(canvas, QMouseEvent.Type.MouseButtonRelease, end))


def test_region_mode_is_off_until_it_is_switched_on(canvas: DocumentCanvas) -> None:
    assert canvas.region_mode() is False
    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag


def test_region_mode_replaces_panning_with_drawing(canvas: DocumentCanvas) -> None:
    canvas.set_region_mode(True)

    assert canvas.region_mode() is True
    assert canvas.dragMode() == QGraphicsView.DragMode.NoDrag


def test_leaving_region_mode_restores_panning(canvas: DocumentCanvas) -> None:
    canvas.set_region_mode(True)

    canvas.set_region_mode(False)

    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    assert canvas.selected_region() is None


def test_dragging_publishes_the_region_in_page_pixels(
    canvas: DocumentCanvas, qtbot
) -> None:
    canvas.set_region_mode(True)

    with qtbot.waitSignal(canvas.region_selected) as blocker:
        _drag(canvas, QPoint(40, 40), QPoint(160, 120))

    region = blocker.args[0]
    assert isinstance(region, BoundingBox)
    assert region.width > 0 and region.height > 0
    assert 0 <= region.x1 < region.x2 <= canvas.page_size().width()
    assert 0 <= region.y1 < region.y2 <= canvas.page_size().height()


def test_dragging_backwards_still_yields_a_valid_rectangle(
    canvas: DocumentCanvas, qtbot
) -> None:
    canvas.set_region_mode(True)

    with qtbot.waitSignal(canvas.region_selected) as blocker:
        _drag(canvas, QPoint(200, 180), QPoint(60, 50))

    region = blocker.args[0]
    assert region.x1 < region.x2
    assert region.y1 < region.y2


def test_the_drawn_rectangle_stays_visible_after_the_drag(
    canvas: DocumentCanvas,
) -> None:
    canvas.set_region_mode(True)

    _drag(canvas, QPoint(40, 40), QPoint(160, 120))

    assert canvas.selected_region() is not None
    assert canvas.region_item() is not None


def test_a_stray_click_selects_nothing(canvas: DocumentCanvas) -> None:
    canvas.set_region_mode(True)
    published: list[BoundingBox] = []
    canvas.region_selected.connect(published.append)

    _drag(canvas, QPoint(80, 80), QPoint(81, 81))

    assert published == []
    assert canvas.selected_region() is None


def test_a_new_drag_replaces_the_previous_region(canvas: DocumentCanvas) -> None:
    canvas.set_region_mode(True)
    _drag(canvas, QPoint(30, 30), QPoint(120, 100))
    first = canvas.selected_region()

    _drag(canvas, QPoint(150, 150), QPoint(260, 240))

    assert canvas.selected_region() != first
    assert len([item for item in canvas.scene().items() if item.zValue() == 2]) == 1


def test_loading_a_new_page_clears_the_region(canvas: DocumentCanvas) -> None:
    canvas.set_region_mode(True)
    _drag(canvas, QPoint(30, 30), QPoint(120, 100))

    canvas.set_image(np.full((400, 300, 3), 200, dtype=np.uint8))

    assert canvas.selected_region() is None


def test_the_region_is_clipped_to_the_page(canvas: DocumentCanvas, qtbot) -> None:
    canvas.set_region_mode(True)

    with qtbot.waitSignal(canvas.region_selected) as blocker:
        _drag(canvas, QPoint(-500, -500), QPoint(5000, 5000))

    region = blocker.args[0]
    assert (region.x1, region.y1) == (0, 0)
    assert region.x2 == canvas.page_size().width()
    assert region.y2 == canvas.page_size().height()


# -- routed into the verification editor ------------------------------------


@pytest.fixture
def dock(qtbot) -> ComparisonDock:
    widget = ComparisonDock()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    widget.canvas.set_image(np.full((800, 600, 3), 245, dtype=np.uint8))
    return widget


def test_the_dock_forwards_a_region_for_recognition(
    dock: ComparisonDock, qtbot
) -> None:
    dock.set_region_mode(True)

    with qtbot.waitSignal(dock.region_ocr_requested) as blocker:
        _drag(dock.canvas, QPoint(40, 40), QPoint(200, 150))

    assert isinstance(blocker.args[0], BoundingBox)


def test_the_region_result_appears_in_the_editor(dock: ComparisonDock) -> None:
    dock.show_region_result("Tổng cộng: 150.000 đồng")

    assert dock.region_result() == "Tổng cộng: 150.000 đồng"
    assert dock.region_label.isVisibleTo(dock) is True


def test_the_window_command_toggles_region_drawing(qtbot, tmp_path) -> None:
    from PySide6.QtCore import QSettings

    from src.gui.main_window import MainWindow

    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    action = window.command_actions["select_region"]

    action.trigger()
    enabled = window.comparison.region_mode()
    action.trigger()

    assert action.isCheckable() is True
    assert enabled is True
    assert window.comparison.region_mode() is False

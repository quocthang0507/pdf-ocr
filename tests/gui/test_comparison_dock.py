"""The verification editor keeps image and transcript in step, both ways."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtGui import QTextCursor

from src.constants import LOW_CONFIDENCE_COLOR, BlockType
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.components.comparison_dock import ComparisonDock

pytestmark = pytest.mark.gui


@pytest.fixture
def dock(qtbot) -> ComparisonDock:
    widget = ComparisonDock()
    widget.resize(800, 600)
    qtbot.addWidget(widget)
    return widget


def _image(width: int = 600, height: int = 800) -> np.ndarray:
    return np.full((height, width, 3), 250, dtype=np.uint8)


def _line(words: tuple[OCRWord, ...], box: tuple[float, ...]) -> OCRLine:
    return OCRLine(words=words, bbox=BoundingBox(*box))


def _page() -> OCRPage:
    title = OCRWord("HÓA", BoundingBox(20, 20, 120, 70), 0.99)
    title_second = OCRWord("ĐƠN", BoundingBox(130, 20, 240, 70), 0.99)
    body_good = OCRWord("Khách", BoundingBox(20, 120, 140, 160), 0.97)
    body_bad = OCRWord("hàhg", BoundingBox(150, 120, 280, 160), 0.41)
    footer = OCRWord("Tổng", BoundingBox(20, 300, 150, 340), 0.95)
    return OCRPage(
        page_number=1,
        width=600,
        height=800,
        blocks=(
            OCRBlock(
                lines=(_line((title, title_second), (20, 20, 240, 70)),),
                bbox=BoundingBox(20, 20, 240, 70),
                block_type=BlockType.TITLE,
            ),
            OCRBlock(
                lines=(_line((body_good, body_bad), (20, 120, 280, 160)),),
                bbox=BoundingBox(20, 120, 280, 160),
            ),
            OCRBlock(
                lines=(_line((footer,), (20, 300, 150, 340)),),
                bbox=BoundingBox(20, 300, 150, 340),
            ),
        ),
    )


def _load(dock: ComparisonDock) -> OCRPage:
    page = _page()
    dock.set_page(page, _image())
    return page


def test_transcript_shows_every_block_in_reading_order(dock: ComparisonDock) -> None:
    _load(dock)

    assert dock.transcript() == "HÓA ĐƠN\n\nKhách hàhg\n\nTổng"


def test_page_image_and_boxes_reach_the_canvas(dock: ComparisonDock) -> None:
    page = _load(dock)

    assert len(dock.canvas.block_items()) == len(page.blocks)
    assert dock.canvas.page_size().width() == 600


def test_low_confidence_words_are_highlighted_in_the_editor(
    dock: ComparisonDock,
) -> None:
    _load(dock)

    highlights = dock.editor.extraSelections()
    colours = {item.format.background().color().name() for item in highlights}
    assert len(highlights) == 1
    assert colours == {LOW_CONFIDENCE_COLOR}


def test_highlight_covers_exactly_the_uncertain_word(dock: ComparisonDock) -> None:
    _load(dock)

    selection = dock.editor.extraSelections()[0]
    assert selection.cursor.selectedText() == "hàhg"


def test_moving_the_text_cursor_focuses_the_matching_block(
    dock: ComparisonDock, qtbot
) -> None:
    _load(dock)
    cursor = dock.editor.textCursor()
    cursor.setPosition(dock.transcript().index("Tổng"))

    with qtbot.waitSignal(dock.canvas.block_selected) as blocker:
        dock.editor.setTextCursor(cursor)

    assert blocker.args == [2]
    assert dock.canvas.selected_block() == 2


def test_selecting_a_box_moves_the_text_cursor_to_that_block(
    dock: ComparisonDock,
) -> None:
    _load(dock)

    dock.canvas.select_block(1)

    cursor = dock.editor.textCursor()
    cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
    assert "Khách hàhg" in cursor.selectedText()


def test_two_way_sync_does_not_loop_between_the_panes(dock: ComparisonDock) -> None:
    _load(dock)
    seen: list[int] = []
    dock.canvas.block_selected.connect(seen.append)

    dock.canvas.select_block(2)

    assert seen == [2]


def test_editing_the_transcript_supports_undo_and_redo(dock: ComparisonDock) -> None:
    _load(dock)
    original = dock.transcript()
    cursor = dock.editor.textCursor()
    cursor.setPosition(0)
    cursor.insertText("SỬA ")

    dock.editor.undo()
    after_undo = dock.transcript()
    dock.editor.redo()

    assert after_undo == original
    assert dock.transcript().startswith("SỬA ")


def test_redo_is_also_reachable_with_the_windows_shortcut(
    dock: ComparisonDock,
) -> None:
    shortcuts = {item.key().toString() for item in dock.editor_shortcuts()}

    assert "Ctrl+Y" in shortcuts


def test_edited_text_is_published_for_the_document_model(
    dock: ComparisonDock, qtbot
) -> None:
    _load(dock)

    with qtbot.waitSignal(dock.transcript_edited) as blocker:
        cursor = dock.editor.textCursor()
        cursor.setPosition(0)
        cursor.insertText("X")

    assert blocker.args[0].startswith("XHÓA")


def test_region_result_is_shown_without_losing_the_page_transcript(
    dock: ComparisonDock,
) -> None:
    _load(dock)

    dock.show_region_result("Đoạn trích vùng chọn")

    assert dock.region_result() == "Đoạn trích vùng chọn"
    assert dock.transcript() == "HÓA ĐƠN\n\nKhách hàhg\n\nTổng"


def test_clearing_resets_both_panes(dock: ComparisonDock) -> None:
    _load(dock)

    dock.clear()

    assert dock.transcript() == ""
    assert dock.canvas.block_items() == []
    assert dock.editor.extraSelections() == []


def test_zoom_requests_are_forwarded_to_the_canvas(dock: ComparisonDock) -> None:
    _load(dock)
    dock.apply_zoom(0)
    fitted = dock.canvas.zoom_factor()

    dock.apply_zoom(1)

    assert dock.canvas.zoom_factor() > fitted


def test_set_image_displays_page_without_blocks(dock: ComparisonDock) -> None:
    img = _image(500, 700)
    dock.set_image(img, text="Văn bản gốc trích xuất")

    assert dock.canvas.page_size().width() == 500
    assert dock.canvas.block_items() == []
    assert dock.transcript() == "Văn bản gốc trích xuất"


def test_page_navigation_controls(dock: ComparisonDock, qtbot) -> None:
    dock.set_page_info(current=1, total=3)

    assert dock.current_page() == 1
    assert dock.total_pages() == 3
    assert dock.page_label.text() == "Trang 1 / 3"
    assert dock.prev_page_btn.isEnabled() is False
    assert dock.next_page_btn.isEnabled() is True

    with qtbot.waitSignal(dock.page_change_requested) as blocker:
        dock.next_page_btn.click()

    assert blocker.args == [2]

    dock.set_page_info(current=2, total=3)
    assert dock.prev_page_btn.isEnabled() is True
    assert dock.next_page_btn.isEnabled() is True

    with qtbot.waitSignal(dock.page_change_requested) as blocker:
        dock.prev_page_btn.click()

    assert blocker.args == [1]


def test_page_navigation_buttons_have_icons_and_tooltips(
    dock: ComparisonDock,
) -> None:
    assert not dock.prev_page_btn.icon().isNull() or bool(dock.prev_page_btn.text())
    assert not dock.next_page_btn.icon().isNull() or bool(dock.next_page_btn.text())
    assert dock.prev_page_btn.toolTip() == "Trang trước"
    assert dock.next_page_btn.toolTip() == "Trang sau"


def test_render_joins_paragraph_lines_smoothly(dock: ComparisonDock) -> None:
    word1 = OCRWord("Dòng", BoundingBox(20, 20, 80, 40))
    word2 = OCRWord("thứ", BoundingBox(90, 20, 140, 40))
    line1 = _line((word1, word2), (20, 20, 140, 40))
    word3 = OCRWord("nhất", BoundingBox(20, 45, 80, 65))
    word4 = OCRWord("tiếp", BoundingBox(90, 45, 140, 65))
    line2 = _line((word3, word4), (20, 45, 140, 65))
    block = OCRBlock(lines=(line1, line2), bbox=BoundingBox(20, 20, 140, 65))
    page = OCRPage(page_number=1, width=400, height=400, blocks=(block,))

    dock.set_page(page, _image(400, 400))
    assert dock.transcript() == "Dòng thứ nhất tiếp"


def test_page_slider_navigation(dock: ComparisonDock, qtbot) -> None:
    dock.set_page_info(current=1, total=5)
    assert dock.page_slider.isEnabled() is True
    assert dock.page_slider.value() == 1
    assert dock.page_slider.maximum() == 5

    with qtbot.waitSignal(dock.page_change_requested) as blocker:
        dock.page_slider.setValue(4)
    assert blocker.args == [4]

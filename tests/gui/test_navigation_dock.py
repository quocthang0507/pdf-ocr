"""NavigationDock displays file info, OCR progress bar, outline, and search."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.components.navigation_dock import NavigationDock
from src.gui.document_session import DocumentSession

pytestmark = pytest.mark.gui


def _sample_pdf(tmp_path: Path) -> Path:
    import pymupdf

    pdf_path = tmp_path / "sample.pdf"
    with pymupdf.open() as doc:
        p1 = doc.new_page(width=300, height=400)
        p1.insert_text((30, 50), "Chương 1: Giới thiệu hợp đồng")
        p2 = doc.new_page(width=300, height=400)
        p2.insert_text((30, 50), "Chương 2: Điều khoản thanh toán")
        doc.set_toc([[1, "Chương 1", 1], [1, "Chương 2", 2]])
        doc.save(pdf_path)
    return pdf_path


def test_navigation_dock_shows_progress_bar_and_updates_on_ocr(
    qtbot, tmp_path: Path
) -> None:
    dock = NavigationDock()
    qtbot.addWidget(dock)
    session = DocumentSession(_sample_pdf(tmp_path))
    try:
        dock.set_session(session)
        assert dock.ocr_progress_bar.maximum() == 2
        assert dock.ocr_progress_bar.value() == 0

        box = BoundingBox(10, 10, 100, 40)
        page1 = OCRPage(
            page_number=1,
            width=300,
            height=400,
            blocks=(
                OCRBlock(
                    lines=(OCRLine(words=(OCRWord("Xin", box, 0.95),), bbox=box),),
                    bbox=box,
                ),
            ),
        )
        session.store(page1)
        dock.refresh_status()

        assert dock.ocr_progress_bar.value() == 1
        assert "1 / 2" in dock.ocr_progress_label.text()
    finally:
        session.close()


def test_navigation_dock_search_emits_page_and_query(qtbot, tmp_path: Path) -> None:
    dock = NavigationDock()
    qtbot.addWidget(dock)
    session = DocumentSession(_sample_pdf(tmp_path))
    try:
        dock.set_session(session)
        dock.search_input.setText("thanh toán")
        dock.run_search()

        assert dock.search_results.count() == 1
        item = dock.search_results.item(0)
        assert item is not None

        with qtbot.waitSignal(dock.search_result_selected) as blocker:
            dock._on_search_item_clicked(item)

        assert blocker.args == [2, "thanh toán"]
    finally:
        session.close()


def test_document_session_supports_color_modes_thumbnails_and_reload(
    tmp_path: Path,
) -> None:
    pdf_path = _sample_pdf(tmp_path)
    session = DocumentSession(pdf_path)
    try:
        assert session.is_pdf is True
        normal_img = session.image(1, dpi=72)
        session.set_page_color_mode("night")
        assert session.page_color_mode == "night"
        night_img = session.image(1, dpi=72)
        assert not (normal_img == night_img).all()

        thumb = session.thumbnail(1, max_side=64)
        assert max(thumb.shape[:2]) <= 64

        session.reload()
        assert session.page_count == 2
    finally:
        session.close()


def test_navigation_dock_renders_page_thumbnails_and_context_actions(
    qtbot, tmp_path: Path
) -> None:
    dock = NavigationDock()
    qtbot.addWidget(dock)
    session = DocumentSession(_sample_pdf(tmp_path))
    try:
        dock.set_session(session)
        item = dock.page_list.item(0)
        assert item is not None
        assert not item.icon().isNull()

        with qtbot.waitSignal(dock.page_context_action) as blocker:
            dock.trigger_page_action("rotate_right", 2)
        assert blocker.args == ["rotate_right", 2]
    finally:
        session.close()


def test_document_properties_dialog_displays_metadata_and_fonts(
    qtbot, tmp_path: Path
) -> None:
    from src.gui.dialogs.document_properties_dialog import DocumentPropertiesDialog

    pdf_path = _sample_pdf(tmp_path)
    dlg = DocumentPropertiesDialog(pdf_path)
    qtbot.addWidget(dlg)

    assert "2" in dlg.page_count_value.text()
    assert dlg.fonts_list.count() >= 1

"""Tests for PDF reader navigation, page rotation, search, and uncertain word review."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PySide6.QtCore import QSettings

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.components.comparison_dock import ComparisonDock
from src.gui.components.navigation_dock import NavigationDock
from src.gui.document_session import DocumentSession
from src.gui.main_window import MainWindow

pytestmark = pytest.mark.gui


def _make_pdf(tmp_path: Path, pages: int = 2) -> Path:
    pdf_path = tmp_path / "sample_reader.pdf"
    with pymupdf.open() as doc:
        for i in range(1, pages + 1):
            page = doc.new_page(width=200, height=100)
            page.insert_text((20, 40), f"Nội dung trang {i} kiểm thử tìm kiếm")
        doc.set_toc([[1, "Chương 1", 1], [1, "Chương 2", 2]])
        doc.save(pdf_path)
    return pdf_path


def test_document_session_rotation_outline_and_search(tmp_path: Path) -> None:
    pdf_path = _make_pdf(tmp_path, pages=2)
    session = DocumentSession(pdf_path)
    try:
        assert session.file_size_bytes() > 0
        outline = session.outline()
        assert len(outline) == 2
        assert outline[0] == (1, "Chương 1", 1)

        img0 = session.image(1, dpi=72)
        deg = session.rotate_page(1, 90)
        assert deg == 90
        img90 = session.image(1, dpi=72)
        assert img90.shape[0] == img0.shape[1]
        assert img90.shape[1] == img0.shape[0]

        hits = session.search_text("trang 2")
        assert any(page_num == 2 for page_num, _snippet in hits)
    finally:
        session.close()


def test_comparison_dock_fit_width_rotation_and_uncertain_word_navigation(
    qtbot,
) -> None:
    dock = ComparisonDock()
    qtbot.addWidget(dock)
    dock.resize(800, 600)

    low_word = OCRWord("nhoe", BoundingBox(10, 10, 40, 30), confidence=0.45)
    high_word = OCRWord("ro", BoundingBox(50, 10, 80, 30), confidence=0.98)
    line = OCRLine(words=(low_word, high_word), bbox=BoundingBox(10, 10, 80, 30))
    block = OCRBlock(lines=(line,), bbox=BoundingBox(10, 10, 80, 30))
    page = OCRPage(page_number=1, width=200, height=100, blocks=(block,))
    image = np.zeros((100, 200, 3), dtype=np.uint8)

    dock.set_page(page, image)
    assert dock.uncertain_count() == 1
    assert dock.uncertain_next_btn.isEnabled()

    dock.jump_to_next_uncertain()
    assert dock.editor.textCursor().selectedText() == "nhoe"

    with qtbot.waitSignal(dock.page_rotate_requested) as blocker:
        dock.rotate_right_btn.click()
    assert blocker.args == [90]

    dock.fit_width_btn.click()
    assert dock.canvas.zoom_factor() > 0


def test_navigation_dock_and_main_window_integration(qtbot, tmp_path: Path) -> None:
    store = QSettings(str(tmp_path / "nav_session.ini"), QSettings.Format.IniFormat)
    store.setFallbacksEnabled(False)
    window = MainWindow(settings=store)
    qtbot.addWidget(window)

    pdf_path = _make_pdf(tmp_path, pages=2)
    window.open_path(pdf_path)

    nav: NavigationDock = window.navigation_dock
    assert pdf_path.name in nav.file_name_label.text()
    assert nav.page_list.count() == 2
    assert nav.outline_tree.topLevelItemCount() == 2

    nav.search_input.setText("trang 2")
    nav.run_search()
    assert nav.search_results.count() >= 1

    window.rotate_current_page(90)
    assert window.document_session is not None
    assert window.document_session.page_rotation(1) == 90

"""GUI tests for the unified PDFToolsDialog (pages, annotations, metadata, security)."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from PySide6.QtWidgets import QFileDialog

from src.gui.dialogs.pdf_tools_dialog import PDFToolsDialog, parse_page_range

pytestmark = pytest.mark.gui


def _create_pdf(path: Path, pages: int = 3) -> Path:
    doc = pymupdf.open()
    for idx in range(1, pages + 1):
        page = doc.new_page(width=400, height=600)
        page.insert_text((50, 100), f"Page {idx} confidential-{idx}", fontsize=14)
    doc.set_metadata({"title": "Original", "author": "Author A"})
    doc.set_toc([[1, "Intro", 1]])
    doc.save(str(path))
    doc.close()
    return path


def test_parse_page_range_handles_single_and_ranges() -> None:
    assert parse_page_range("1, 3-4", max_page=5) == [1, 3, 4]


def test_pdf_tools_dialog_rotates_and_reorders_pages(qtbot, tmp_path: Path) -> None:
    pdf_path = _create_pdf(tmp_path / "doc.pdf", pages=3)
    dlg = PDFToolsDialog(pdf_path, current_page=1)
    qtbot.addWidget(dlg)

    with qtbot.waitSignal(dlg.pdf_modified):
        dlg.rotate_right_btn.click()

    with pymupdf.open(str(pdf_path)) as doc:
        assert doc[0].rotation == 90

    dlg.reorder_edit.setText("3, 1, 2")
    with qtbot.waitSignal(dlg.pdf_modified):
        dlg.reorder_btn.click()

    with pymupdf.open(str(pdf_path)) as doc:
        assert "Page 3" in doc[0].get_text("text")


def test_pdf_tools_dialog_adds_annotations_stamp_and_redaction(
    qtbot, tmp_path: Path
) -> None:
    pdf_path = _create_pdf(tmp_path / "annot.pdf", pages=1)
    stamp = tmp_path / "stamp.png"
    Image.new("RGBA", (60, 30), (0, 120, 215, 255)).save(stamp)

    dlg = PDFToolsDialog(
        pdf_path, current_page=1, selection_norm=(0.05, 0.10, 0.85, 0.22)
    )
    qtbot.addWidget(dlg)

    dlg.highlight_btn.click()
    dlg.note_text_edit.setText("Ghi chú quan trọng")
    dlg.add_note_btn.click()
    dlg.stamp_path_edit.setText(str(stamp))
    dlg.apply_stamp_btn.click()

    with pymupdf.open(str(pdf_path)) as doc:
        assert len(list(doc[0].annots() or [])) >= 2
        assert len(doc[0].get_images()) == 1

    # Now redact the region containing confidential-1
    dlg.redact_btn.click()
    with pymupdf.open(str(pdf_path)) as doc:
        assert "confidential-1" not in doc[0].get_text("text")


def test_pdf_tools_dialog_updates_metadata_and_bookmarks(qtbot, tmp_path: Path) -> None:
    pdf_path = _create_pdf(tmp_path / "meta.pdf", pages=2)
    dlg = PDFToolsDialog(pdf_path, current_page=1)
    qtbot.addWidget(dlg)

    dlg.title_edit.setText("Báo cáo tài chính")
    dlg.author_edit.setText("Phòng Kế toán")
    dlg.save_metadata_btn.click()

    dlg.bookmarks_edit.setPlainText("1 | Phần I | 1\n1 | Phần II | 2")
    dlg.save_bookmarks_btn.click()

    with pymupdf.open(str(pdf_path)) as doc:
        assert doc.metadata["title"] == "Báo cáo tài chính"
        assert len(doc.get_toc()) == 2


def test_pdf_tools_dialog_compresses_and_encrypts_pdf(
    qtbot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = _create_pdf(tmp_path / "sec.pdf", pages=2)
    encrypted_out = tmp_path / "locked.pdf"
    dlg = PDFToolsDialog(pdf_path, current_page=1)
    qtbot.addWidget(dlg)

    dlg.compress_btn.click()
    assert "KB" in dlg.status_label.text() or "byte" in dlg.status_label.text()

    dlg.user_password_edit.setText("123456")
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(encrypted_out), "PDF")
    )
    dlg.encrypt_btn.click()
    assert encrypted_out.is_file()

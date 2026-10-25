"""One open document: rendered pages, recognised results, and user edits."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymupdf
import pytest

from src.core.exceptions import DocumentLoadError
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.document_session import DocumentSession

pytestmark = pytest.mark.unit


def _pdf(tmp_path: Path, pages: int = 3) -> Path:
    path = tmp_path / "tai-lieu.pdf"
    with pymupdf.open() as pdf:
        for number in range(1, pages + 1):
            page = pdf.new_page(width=200, height=100)
            page.insert_text((20, 50), f"Trang {number}", fontsize=12)
        pdf.save(path)
    return path


def _page(number: int, *, width: float = 400, height: float = 200) -> OCRPage:
    box = BoundingBox(10, 10, 90, 30)
    word = OCRWord(f"trang {number}", box, 0.99)
    line = OCRLine(words=(word,), bbox=box)
    return OCRPage(
        page_number=number,
        width=width,
        height=height,
        blocks=(OCRBlock(lines=(line,), bbox=box),),
        dpi=144,
    )


@pytest.fixture
def session(tmp_path: Path) -> DocumentSession:
    opened = DocumentSession(_pdf(tmp_path))
    yield opened
    opened.close()


def test_a_session_knows_how_many_pages_the_document_has(
    session: DocumentSession,
) -> None:
    assert session.page_count == 3
    assert session.current_page == 1


def test_a_page_renders_at_the_requested_resolution(session: DocumentSession) -> None:
    image = session.image(1, dpi=144)

    assert isinstance(image, np.ndarray)
    assert image.shape[:2] == (200, 400)


def test_rendered_pages_are_cached(session: DocumentSession) -> None:
    first = session.image(2, dpi=72)

    assert session.image(2, dpi=72) is first


def test_the_cache_stays_small(session: DocumentSession) -> None:
    for number in (1, 2, 3):
        session.image(number, dpi=72)

    assert session.cached_images() <= 2


def test_session_cache_size_is_configurable_and_evicts_excess_pages(
    tmp_path: Path,
) -> None:
    opened = DocumentSession(_pdf(tmp_path, pages=4), cache_size=3, color_mode="sepia")
    try:
        assert opened.cache_size == 3
        assert opened.page_color_mode == "sepia"
        for number in (1, 2, 3):
            opened.image(number, dpi=72)
        assert opened.cached_images() == 3

        opened.set_cache_size(1)
        assert opened.cache_size == 1
        assert opened.cached_images() == 1
    finally:
        opened.close()


def test_moving_between_pages_stays_inside_the_document(
    session: DocumentSession,
) -> None:
    assert session.go_to(3) == 3
    assert session.go_to(9) == 3
    assert session.go_to(0) == 1
    assert session.step(1) == 2
    assert session.step(-5) == 1


def test_a_corrupt_file_is_reported_as_a_load_error(tmp_path: Path) -> None:
    broken = tmp_path / "hong.pdf"
    broken.write_bytes(b"%PDF-1.4 hong")

    with pytest.raises(DocumentLoadError):
        _ = DocumentSession(broken).page_count


def test_the_image_of_a_result_matches_its_coordinate_space(
    session: DocumentSession,
) -> None:
    page = _page(1)
    session.store(page)

    image = session.image_for(page)

    assert image.shape[:2] == (200, 400)


def test_results_are_kept_per_page(session: DocumentSession) -> None:
    session.store(_page(2))

    assert session.result(2) is not None
    assert session.result(1) is None
    assert session.recognised_pages() == (2,)


def test_closing_releases_the_file_but_keeps_results(
    session: DocumentSession,
) -> None:
    session.image(1, dpi=72)
    session.store(_page(1))

    session.close()

    assert session.cached_images() == 0
    assert session.result(1) is not None


def test_a_text_based_page_offers_its_own_text(session: DocumentSession) -> None:
    assert "Trang 2" in session.native_text(2, dpi=72)


def test_a_scanned_page_offers_no_text(tmp_path: Path) -> None:
    path = tmp_path / "quet.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=100)
        pdf.save(path)
    scanned = DocumentSession(path)

    assert scanned.native_text(1, dpi=72) == ""
    scanned.close()


def test_document_session_restores_and_clears_cached_ocr_results(
    tmp_path: Path,
) -> None:
    from src.services.settings_store import SettingsStore

    pdf_path = _pdf(tmp_path, pages=2)
    store = SettingsStore(tmp_path / "settings.db")
    try:
        first = DocumentSession(pdf_path, session_store=store)
        first.store(_page(1))
        first.close()

        reopened = DocumentSession(pdf_path, session_store=store)
        assert reopened.recognised_pages() == (1,)
        assert reopened.result(1) == _page(1)

        reopened.clear_results()
        assert reopened.recognised_pages() == ()
        reopened.close()

        after_clear = DocumentSession(pdf_path, session_store=store)
        assert after_clear.recognised_pages() == ()
        after_clear.close()
    finally:
        store.close()


def test_document_session_opens_encrypted_pdf_with_password(tmp_path: Path) -> None:
    locked = tmp_path / "locked.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_text((20, 40), "Tai lieu mat 2026", fontsize=12)
        doc.save(
            locked,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="pass123",
        )
    opened = DocumentSession(locked, password="pass123")
    try:
        assert opened.page_count == 1
        assert "Tai lieu mat 2026" in opened.native_text(1, dpi=72)
    finally:
        opened.close()

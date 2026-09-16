"""Batch progress stays honest, and pause and cancel stay safe."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRWord
from src.gui.components.status_bar import BatchStatusBar, format_duration
from src.gui.dialogs.batch_dialog import BatchDialog, DocumentState
from src.workers.batch_manager import BatchManager
from src.workers.signals import BatchProgress, PageTask

pytestmark = pytest.mark.gui

TIMEOUT_MS = 20_000


def _page(task: PageTask) -> OCRPage:
    box = BoundingBox(0, 0, 90, 30)
    word = OCRWord(f"trang {task.page_number}", box, 0.97)
    return OCRPage(
        page_number=task.page_number,
        width=600,
        height=800,
        blocks=(OCRBlock(lines=(OCRLine(words=(word,), bbox=box),), bbox=box),),
    )


@pytest.fixture
def documents(tmp_path: Path) -> list[Path]:
    paths = []
    for name in ("hoa-don.pdf", "bao-cao.pdf"):
        path = tmp_path / name
        path.write_bytes(b"%PDF-1.4 fake")
        paths.append(path)
    return paths


def _manager(processor=_page, *, pages: int = 3) -> BatchManager:
    return BatchManager(processor, page_counter=lambda _path: pages, max_workers=1)


@pytest.fixture
def dialog(qtbot, documents: list[Path]) -> BatchDialog:
    widget = BatchDialog(_manager(), documents)
    qtbot.addWidget(widget)
    return widget


# -- duration formatting ----------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "—"),
        (9.0, "9 giây"),
        (75.0, "1 phút 15 giây"),
        (3700.0, "1 giờ 1 phút"),
    ],
)
def test_remaining_time_reads_naturally(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


# -- status bar -------------------------------------------------------------


@pytest.fixture
def status_bar(qtbot) -> BatchStatusBar:
    bar = BatchStatusBar()
    qtbot.addWidget(bar)
    return bar


def test_the_status_bar_starts_idle(status_bar: BatchStatusBar) -> None:
    assert status_bar.progress_bar.isVisibleTo(status_bar) is False
    assert status_bar.pause_button.isEnabled() is False
    assert status_bar.cancel_button.isEnabled() is False


def test_the_status_bar_shows_percentage_and_remaining_time(
    status_bar: BatchStatusBar,
) -> None:
    status_bar.show_progress(
        BatchProgress(completed=2, failed=0, total=8, elapsed_seconds=4.0)
    )

    assert status_bar.progress_bar.value() == 25
    assert "12 giây" in status_bar.eta_label.text()


def test_the_status_bar_counts_failures_separately(
    status_bar: BatchStatusBar,
) -> None:
    status_bar.show_progress(
        BatchProgress(completed=3, failed=1, total=10, elapsed_seconds=5.0)
    )

    assert "3" in status_bar.count_label.text()
    assert "1" in status_bar.count_label.text()


def test_the_status_bar_enables_its_controls_while_running(
    status_bar: BatchStatusBar,
) -> None:
    status_bar.set_running(True)

    assert status_bar.progress_bar.isVisibleTo(status_bar) is True
    assert status_bar.pause_button.isEnabled() is True
    assert status_bar.cancel_button.isEnabled() is True


def test_the_pause_button_reports_both_directions(
    status_bar: BatchStatusBar, qtbot
) -> None:
    status_bar.set_running(True)
    states: list[bool] = []
    status_bar.pause_toggled.connect(states.append)

    status_bar.pause_button.click()
    label_when_paused = status_bar.pause_button.text()
    status_bar.pause_button.click()

    assert states == [True, False]
    assert label_when_paused == "Tiếp tục"
    assert status_bar.pause_button.text() == "Tạm dừng"


def test_the_cancel_button_asks_once(status_bar: BatchStatusBar) -> None:
    status_bar.set_running(True)
    cancels: list[bool] = []
    status_bar.cancel_requested.connect(lambda: cancels.append(True))

    status_bar.cancel_button.click()

    assert cancels == [True]
    assert status_bar.cancel_button.isEnabled() is False


# -- batch dialog -----------------------------------------------------------


def test_the_dialog_lists_every_document_as_waiting(
    dialog: BatchDialog, documents: list[Path]
) -> None:
    names = [dialog.document_list.item(row).text() for row in range(2)]

    assert all(path.name in " ".join(names) for path in documents)
    assert dialog.state_of(documents[0]) is DocumentState.WAITING


def test_running_the_batch_completes_every_document(
    dialog: BatchDialog, qtbot, documents: list[Path]
) -> None:
    with qtbot.waitSignal(dialog.batch_finished, timeout=TIMEOUT_MS):
        dialog.start()
        dialog.manager.wait_for_completion(TIMEOUT_MS)

    assert dialog.progress_bar.value() == 100
    assert dialog.state_of(documents[0]) is DocumentState.DONE
    assert dialog.state_of(documents[1]) is DocumentState.DONE


def test_a_document_is_marked_running_until_its_last_page_lands(
    qtbot, documents: list[Path]
) -> None:
    def slow(task: PageTask) -> OCRPage:
        time.sleep(0.02)
        return _page(task)

    dialog = BatchDialog(_manager(slow, pages=6), documents)
    qtbot.addWidget(dialog)
    dialog.start()
    qtbot.waitUntil(
        lambda: dialog.state_of(documents[0]) is DocumentState.RUNNING,
        timeout=TIMEOUT_MS,
    )
    mid_run = dialog.state_of(documents[0])
    dialog.manager.wait_for_completion(TIMEOUT_MS)

    assert mid_run is DocumentState.RUNNING
    assert dialog.state_of(documents[0]) is DocumentState.DONE


def test_a_failing_page_marks_its_document(qtbot, documents: list[Path]) -> None:
    from src.core.exceptions import OCREngineError

    def failing(task: PageTask) -> OCRPage:
        if Path(task.document_path).name == "bao-cao.pdf":
            raise OCREngineError("Không nhận diện được trang.")
        return _page(task)

    dialog = BatchDialog(_manager(failing, pages=2), documents)
    qtbot.addWidget(dialog)

    dialog.start()
    dialog.manager.wait_for_completion(TIMEOUT_MS)

    assert dialog.state_of(documents[0]) is DocumentState.DONE
    assert dialog.state_of(documents[1]) is DocumentState.FAILED


def test_the_dialog_reports_progress_and_an_estimate(
    dialog: BatchDialog, qtbot
) -> None:
    with qtbot.waitSignal(dialog.batch_finished, timeout=TIMEOUT_MS):
        dialog.start()
        dialog.manager.wait_for_completion(TIMEOUT_MS)

    assert "6" in dialog.summary_label.text()
    assert dialog.eta_label.text() != ""


def test_pausing_the_dialog_pauses_the_queue(qtbot, documents: list[Path]) -> None:
    def slow(task: PageTask) -> OCRPage:
        time.sleep(0.01)
        return _page(task)

    dialog = BatchDialog(_manager(slow, pages=40), documents)
    qtbot.addWidget(dialog)
    dialog.start()

    dialog.pause_button.click()

    assert dialog.manager.is_paused is True
    assert dialog.pause_button.text() == "Tiếp tục"
    dialog.cancel()
    dialog.manager.wait_for_completion(TIMEOUT_MS)


def test_resuming_the_dialog_resumes_the_queue(qtbot, documents: list[Path]) -> None:
    dialog = BatchDialog(_manager(pages=4), documents)
    qtbot.addWidget(dialog)
    dialog.pause_button.click()
    dialog.start()

    dialog.pause_button.click()
    dialog.manager.wait_for_completion(TIMEOUT_MS)

    assert dialog.manager.is_paused is False
    assert dialog.progress_bar.value() == 100


def test_cancelling_stops_the_batch_without_crashing(
    qtbot, documents: list[Path]
) -> None:
    def slow(task: PageTask) -> OCRPage:
        time.sleep(0.01)
        return _page(task)

    dialog = BatchDialog(_manager(slow, pages=50), documents)
    qtbot.addWidget(dialog)
    dialog.start()

    dialog.cancel()

    assert dialog.manager.wait_for_completion(TIMEOUT_MS) is True
    assert dialog.manager.is_cancelled is True
    assert "hủy" in dialog.summary_label.text().lower()


def test_closing_the_dialog_cancels_any_running_batch(
    qtbot, documents: list[Path]
) -> None:
    def slow(task: PageTask) -> OCRPage:
        time.sleep(0.01)
        return _page(task)

    dialog = BatchDialog(_manager(slow, pages=50), documents)
    qtbot.addWidget(dialog)
    dialog.start()

    dialog.close()

    assert dialog.manager.is_cancelled is True
    assert dialog.manager.wait_for_completion(TIMEOUT_MS) is True


def test_recognised_pages_are_published_for_the_document_model(
    dialog: BatchDialog, qtbot
) -> None:
    received: list[tuple[PageTask, OCRPage]] = []
    dialog.page_ready.connect(lambda task, page: received.append((task, page)))

    dialog.start()
    dialog.manager.wait_for_completion(TIMEOUT_MS)

    assert len(received) == 6


# -- reachable from the window ----------------------------------------------


def test_the_window_runs_a_batch_in_the_background(qtbot, tmp_path: Path) -> None:
    """Running OCR from the window must not recognise anything on its thread."""
    import pymupdf
    from PySide6.QtCore import QSettings

    from src.gui.main_window import MainWindow

    document = tmp_path / "hai-trang.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=120, height=160)
        pdf.new_page(width=120, height=160)
        pdf.save(document)

    class StubSession:
        def __init__(self) -> None:
            self.closed = False

        def page_count(self, _path: object) -> int:
            return 2

        def recognise(self, _path: object, page_number: int) -> OCRPage:
            return _page(PageTask(str(document), page_number))

        def close(self) -> None:
            self.closed = True

    session = StubSession()

    class StubPipeline:
        def open_page_session(self, **_options: object) -> StubSession:
            return session

    settings = QSettings(str(tmp_path / "session.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings, pipeline=StubPipeline())
    qtbot.addWidget(window)
    window.open_path(document)

    window.command_actions["run_ocr"].trigger()
    batch = window.batch_dialog
    assert batch is not None
    batch.manager.wait_for_completion(TIMEOUT_MS)

    assert batch.progress_bar.value() == 100
    assert session.closed is True
    batch.close()

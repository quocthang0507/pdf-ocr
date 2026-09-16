"""The batch queue keeps the interface free and stays controllable throughout."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.core.exceptions import OCREngineError
from src.core.models import BoundingBox, OCRLine, OCRPage, OCRWord
from src.workers.batch_manager import BatchControl, BatchManager
from src.workers.signals import BatchProgress, PageTask

pytestmark = pytest.mark.unit

TIMEOUT_MS = 15_000


def _page(task: PageTask) -> OCRPage:
    box = BoundingBox(0, 0, 100, 40)
    word = OCRWord(f"trang {task.page_number}", box, 0.99)
    return OCRPage(
        page_number=task.page_number,
        width=600,
        height=800,
        blocks=(),
        tables=(),
    ).with_updates(blocks=(_block(word, box),))


def _block(word: OCRWord, box: BoundingBox):
    from src.core.models import OCRBlock

    return OCRBlock(lines=(OCRLine(words=(word,), bbox=box),), bbox=box)


@pytest.fixture
def documents(tmp_path: Path) -> list[Path]:
    paths = []
    for name in ("mot.pdf", "hai.pdf"):
        path = tmp_path / name
        path.write_bytes(b"%PDF-1.4 fake")
        paths.append(path)
    return paths


def _manager(processor, *, pages: int = 3, workers: int = 1) -> BatchManager:
    return BatchManager(
        processor,
        page_counter=lambda _path: pages,
        max_workers=workers,
    )


# -- queueing ---------------------------------------------------------------


def test_every_page_of_every_document_is_queued(qapp, documents: list[Path]) -> None:
    manager = _manager(_page, pages=4)

    queued = manager.start(documents)

    assert queued == 8
    assert manager.progress_snapshot().total == 8


def test_starting_without_documents_queues_nothing(qapp) -> None:
    manager = _manager(_page)

    assert manager.start([]) == 0
    assert manager.progress_snapshot().is_finished is True


def test_all_pages_are_recognised_in_the_background(
    qapp, documents: list[Path]
) -> None:
    done: list[PageTask] = []
    manager = _manager(_page, pages=5)
    manager.page_ready.connect(lambda task, _page: done.append(task))

    manager.start(documents)

    assert manager.wait_for_completion(TIMEOUT_MS) is True
    assert len(done) == 10
    assert manager.progress_snapshot().completed == 10


def test_recognition_runs_off_the_calling_thread(qapp, documents: list[Path]) -> None:
    threads: set[int] = set()

    def record(task: PageTask) -> OCRPage:
        threads.add(threading.get_ident())
        return _page(task)

    manager = _manager(record, pages=2)
    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)

    assert threading.get_ident() not in threads


def test_pages_arrive_with_their_document_and_number(
    qapp, documents: list[Path]
) -> None:
    seen: list[tuple[str, int]] = []
    manager = _manager(_page, pages=3)
    manager.page_ready.connect(
        lambda task, page: seen.append(
            (Path(task.document_path).name, page.page_number)
        )
    )

    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)

    assert sorted(seen) == [("mot.pdf", 1), ("mot.pdf", 2), ("mot.pdf", 3)]


# -- failures ---------------------------------------------------------------


def test_a_failing_page_does_not_stop_the_rest(qapp, documents: list[Path]) -> None:
    def sometimes_fails(task: PageTask) -> OCRPage:
        if task.page_number == 2:
            raise OCREngineError("Không nhận diện được trang này.")
        return _page(task)

    failures: list[str] = []
    manager = _manager(sometimes_fails, pages=3)
    manager.page_failed.connect(lambda _task, message: failures.append(message))

    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)

    snapshot = manager.progress_snapshot()
    assert failures == ["Không nhận diện được trang này."]
    assert (snapshot.completed, snapshot.failed) == (2, 1)


def test_an_unexpected_failure_is_reported_without_technical_detail(
    qapp, documents: list[Path]
) -> None:
    def explodes(_task: PageTask) -> OCRPage:
        raise ZeroDivisionError("/home/user/secret/token.txt")

    failures: list[str] = []
    manager = _manager(explodes, pages=1)
    manager.page_failed.connect(lambda _task, message: failures.append(message))

    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)

    assert failures and "secret" not in failures[0]


def test_a_document_that_cannot_be_counted_is_reported_not_fatal(
    qapp, documents: list[Path]
) -> None:
    def unreadable(_path: Path) -> int:
        raise OCREngineError("Không mở được tài liệu.")

    failures: list[str] = []
    manager = BatchManager(_page, page_counter=unreadable, max_workers=1)
    manager.page_failed.connect(lambda _task, message: failures.append(message))

    assert manager.start(documents) == 0
    assert len(failures) == 2


# -- control ----------------------------------------------------------------


def test_pausing_stops_new_pages_from_starting(qapp, documents: list[Path]) -> None:
    started = threading.Event()
    processed: list[int] = []

    def slow(task: PageTask) -> OCRPage:
        started.set()
        processed.append(task.page_number)
        time.sleep(0.02)
        return _page(task)

    manager = _manager(slow, pages=40)
    manager.start(documents[:1])
    started.wait(timeout=5)
    manager.pause()
    time.sleep(0.15)
    settled = len(processed)
    time.sleep(0.15)

    assert manager.is_paused is True
    assert len(processed) == settled
    manager.cancel()
    manager.wait_for_completion(TIMEOUT_MS)


def test_resuming_finishes_the_remaining_pages(qapp, documents: list[Path]) -> None:
    manager = _manager(_page, pages=6)
    manager.pause()
    manager.start(documents[:1])
    time.sleep(0.05)
    paused_progress = manager.progress_snapshot().completed

    manager.resume()

    assert manager.wait_for_completion(TIMEOUT_MS) is True
    assert paused_progress < manager.progress_snapshot().completed == 6


def test_cancelling_leaves_the_queue_empty_and_safe(
    qapp, documents: list[Path]
) -> None:
    def slow(task: PageTask) -> OCRPage:
        time.sleep(0.01)
        return _page(task)

    manager = _manager(slow, pages=60)
    manager.start(documents)
    manager.cancel()

    assert manager.wait_for_completion(TIMEOUT_MS) is True
    assert manager.is_cancelled is True
    assert manager.progress_snapshot().completed < 120


def test_a_new_batch_does_not_inherit_a_previous_cancel(
    qapp, documents: list[Path]
) -> None:
    manager = _manager(_page, pages=5)
    manager.cancel()

    manager.start(documents[:1])

    assert manager.wait_for_completion(TIMEOUT_MS) is True
    assert manager.is_cancelled is False
    assert manager.progress_snapshot().completed == 5


# -- progress and estimation ------------------------------------------------


def test_progress_is_published_as_pages_complete(qapp, documents: list[Path]) -> None:
    updates: list[BatchProgress] = []
    manager = _manager(_page, pages=4)
    manager.progress.connect(updates.append)

    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)

    assert [item.completed for item in updates] == [1, 2, 3, 4]
    assert updates[-1].percent == 100


def test_the_finished_signal_carries_the_final_tally(
    qapp, documents: list[Path]
) -> None:
    summaries: list[BatchProgress] = []
    manager = _manager(_page, pages=3)
    manager.finished.connect(summaries.append)

    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)

    assert len(summaries) == 1
    assert summaries[0].completed == 3
    assert summaries[0].is_finished is True


@pytest.mark.parametrize(
    ("completed", "total", "elapsed", "expected"),
    [(0, 10, 0.0, 0.0), (5, 10, 10.0, 10.0), (10, 10, 20.0, 0.0), (2, 8, 4.0, 12.0)],
)
def test_remaining_time_is_estimated_from_the_pace(
    completed: int, total: int, elapsed: float, expected: float
) -> None:
    progress = BatchProgress(completed, 0, total, elapsed)

    assert progress.seconds_remaining == pytest.approx(expected)


@pytest.mark.parametrize(
    ("completed", "failed", "total", "percent"),
    [(0, 0, 4, 0), (1, 1, 4, 50), (4, 0, 4, 100), (0, 0, 0, 100)],
)
def test_percentage_counts_finished_pages_however_they_ended(
    completed: int, failed: int, total: int, percent: int
) -> None:
    assert BatchProgress(completed, failed, total, 1.0).percent == percent


def test_a_batch_cannot_be_started_twice_at_once(qapp, documents: list[Path]) -> None:
    def slow(task: PageTask) -> OCRPage:
        time.sleep(0.01)
        return _page(task)

    manager = _manager(slow, pages=30)
    manager.start(documents[:1])

    with pytest.raises(RuntimeError, match="đang chạy"):
        manager.start(documents[1:])

    manager.cancel()
    manager.wait_for_completion(TIMEOUT_MS)


# -- control primitive ------------------------------------------------------


def test_control_starts_running() -> None:
    control = BatchControl()

    assert (control.is_paused, control.is_cancelled) == (False, False)


def test_control_pause_and_resume_flip_the_flag() -> None:
    control = BatchControl()

    control.pause()
    paused = control.is_paused
    control.resume()

    assert paused is True
    assert control.is_paused is False


def test_cancelling_releases_a_paused_worker() -> None:
    control = BatchControl()
    control.pause()

    control.cancel()

    assert control.wait_while_paused(timeout=1.0) is False
    assert control.is_cancelled is True


def test_a_running_control_lets_work_through_immediately() -> None:
    control = BatchControl()

    assert control.wait_while_paused(timeout=1.0) is True


def test_cancelling_announces_the_end_of_the_batch(qapp, documents: list[Path]) -> None:
    summaries: list[BatchProgress] = []
    manager = _manager(_page, pages=30)
    manager.cancelled.connect(summaries.append)
    manager.start(documents)

    manager.cancel()
    manager.wait_for_completion(TIMEOUT_MS)

    assert len(summaries) == 1
    assert manager.is_running is False


def test_a_batch_announces_its_end_only_once(qapp, documents: list[Path]) -> None:
    endings: list[str] = []
    manager = _manager(_page, pages=2)
    manager.finished.connect(lambda _p: endings.append("finished"))
    manager.cancelled.connect(lambda _p: endings.append("cancelled"))

    manager.start(documents[:1])
    manager.wait_for_completion(TIMEOUT_MS)
    manager.cancel()

    assert endings == ["finished"]


def test_a_cancelled_batch_can_be_started_again(qapp, documents: list[Path]) -> None:
    manager = _manager(_page, pages=3)
    manager.start(documents[:1])
    manager.cancel()
    manager.wait_for_completion(TIMEOUT_MS)

    queued = manager.start(documents[1:])

    assert queued == 3
    assert manager.wait_for_completion(TIMEOUT_MS) is True
    assert manager.progress_snapshot().completed == 3

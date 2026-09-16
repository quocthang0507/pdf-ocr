"""Weight downloads retry, verify their hash, and cancel without corruption."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from urllib.error import URLError

import pytest

from src.core.exceptions import WeightsError
from src.gui.dialogs.download_dialog import DownloadDialog, format_eta, format_rate
from src.services.weights_manager import DownloadProgress, download_weights

pytestmark = pytest.mark.gui

PAYLOAD = b"trong so mo hinh VietOCR" * 500
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://example.invalid/vietocr.pth"


class _Response(BytesIO):
    """Minimal stand-in for the object urlopen returns."""

    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()


def _opener(payload: bytes = PAYLOAD):
    def open_url(url: str, timeout: float = 0) -> _Response:
        return _Response(payload)

    return open_url


def _flaky_opener(failures: int, payload: bytes = PAYLOAD):
    attempts = {"count": 0}

    def open_url(url: str, timeout: float = 0) -> _Response:
        attempts["count"] += 1
        if attempts["count"] <= failures:
            raise URLError("mạng chập chờn")
        return _Response(payload)

    open_url.attempts = attempts  # type: ignore[attr-defined]
    return open_url


# -- download service -------------------------------------------------------


def test_a_verified_download_lands_at_the_destination(tmp_path: Path) -> None:
    destination = tmp_path / "vietocr.pth"

    download_weights(URL, destination, sha256=DIGEST, opener=_opener(), backoff=0)

    assert destination.read_bytes() == PAYLOAD


def test_progress_reports_share_of_bytes_speed_and_eta(tmp_path: Path) -> None:
    updates: list[DownloadProgress] = []

    download_weights(
        URL,
        tmp_path / "vietocr.pth",
        sha256=DIGEST,
        opener=_opener(),
        on_progress=updates.append,
        backoff=0,
    )

    assert updates[-1].percent == 100
    assert updates[-1].downloaded_bytes == len(PAYLOAD)
    assert updates[-1].total_bytes == len(PAYLOAD)
    assert all(item.bytes_per_second >= 0 for item in updates)


def test_a_flaky_network_is_retried_before_giving_up(tmp_path: Path) -> None:
    opener = _flaky_opener(failures=2)

    download_weights(
        URL, tmp_path / "vietocr.pth", sha256=DIGEST, opener=opener, backoff=0
    )

    assert opener.attempts["count"] == 3


def test_a_persistent_outage_reports_a_friendly_error(tmp_path: Path) -> None:
    opener = _flaky_opener(failures=99)

    with pytest.raises(WeightsError, match="kết nối"):
        download_weights(
            URL, tmp_path / "vietocr.pth", sha256=DIGEST, opener=opener, backoff=0
        )

    assert opener.attempts["count"] == 3


def test_a_failed_download_leaves_no_partial_file(tmp_path: Path) -> None:
    destination = tmp_path / "vietocr.pth"

    with pytest.raises(WeightsError):
        download_weights(
            URL,
            destination,
            sha256=DIGEST,
            opener=_flaky_opener(failures=99),
            backoff=0,
        )

    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_a_mismatched_hash_is_rejected_and_discarded(tmp_path: Path) -> None:
    destination = tmp_path / "vietocr.pth"

    with pytest.raises(WeightsError, match="toàn vẹn"):
        download_weights(URL, destination, sha256="0" * 64, opener=_opener(), backoff=0)

    assert not destination.exists()


def test_an_existing_verified_file_is_kept_untouched(tmp_path: Path) -> None:
    destination = tmp_path / "vietocr.pth"
    destination.write_bytes(PAYLOAD)

    def refuse(url: str, timeout: float = 0) -> _Response:
        raise AssertionError("Không được tải lại tệp đã hợp lệ.")

    download_weights(URL, destination, sha256=DIGEST, opener=refuse, backoff=0)

    assert destination.read_bytes() == PAYLOAD


def test_cancelling_stops_the_transfer_and_removes_the_partial_file(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "vietocr.pth"

    with pytest.raises(WeightsError, match="hủy"):
        download_weights(
            URL,
            destination,
            sha256=DIGEST,
            opener=_opener(),
            should_cancel=lambda: True,
            backoff=0,
        )

    assert not destination.exists()


@pytest.mark.parametrize("url", ["ftp://host/x.pth", "file:///etc/passwd", "notaurl"])
def test_only_http_downloads_are_allowed(tmp_path: Path, url: str) -> None:
    with pytest.raises(WeightsError, match="Địa chỉ"):
        download_weights(url, tmp_path / "x.pth", sha256=DIGEST, backoff=0)


@pytest.mark.parametrize("digest", ["", "abc", "z" * 64])
def test_a_download_without_a_valid_checksum_is_refused(
    tmp_path: Path, digest: str
) -> None:
    with pytest.raises(WeightsError, match="mã băm"):
        download_weights(URL, tmp_path / "x.pth", sha256=digest, backoff=0)


# -- progress formatting ----------------------------------------------------


@pytest.mark.parametrize(
    ("rate", "expected"),
    [(0.0, "0 KB/s"), (2048.0, "2.0 KB/s"), (5 * 1024**2, "5.0 MB/s")],
)
def test_transfer_rate_is_shown_in_readable_units(rate: float, expected: str) -> None:
    assert format_rate(rate) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.0, "—"), (45.0, "45 giây"), (150.0, "2 phút 30 giây")],
)
def test_remaining_time_is_shown_in_readable_units(
    seconds: float, expected: str
) -> None:
    assert format_eta(seconds) == expected


# -- dialog -----------------------------------------------------------------


@pytest.fixture
def dialog(qtbot, tmp_path: Path) -> DownloadDialog:
    widget = DownloadDialog(
        URL,
        tmp_path / "vietocr.pth",
        sha256=DIGEST,
        model_name="VietOCR",
        opener=_opener(),
    )
    qtbot.addWidget(widget)
    return widget


def test_the_dialog_names_the_model_being_downloaded(dialog: DownloadDialog) -> None:
    assert "VietOCR" in dialog.title_label.text()


def test_a_completed_download_reports_the_saved_file(
    dialog: DownloadDialog, qtbot, tmp_path: Path
) -> None:
    with qtbot.waitSignal(dialog.download_finished, timeout=15000) as blocker:
        dialog.start()

    assert blocker.args == [str(tmp_path / "vietocr.pth")]
    assert dialog.progress_bar.value() == 100
    assert (tmp_path / "vietocr.pth").read_bytes() == PAYLOAD


def test_the_dialog_shows_speed_and_remaining_time(
    dialog: DownloadDialog, qtbot
) -> None:
    with qtbot.waitSignal(dialog.download_finished, timeout=15000):
        dialog.start()

    assert "/s" in dialog.rate_label.text()
    assert dialog.eta_label.text() != ""


def test_a_failed_download_is_reported_without_technical_detail(
    qtbot, tmp_path: Path
) -> None:
    widget = DownloadDialog(
        URL,
        tmp_path / "vietocr.pth",
        sha256=DIGEST,
        model_name="VietOCR",
        opener=_flaky_opener(failures=99),
        backoff=0,
    )
    qtbot.addWidget(widget)

    with qtbot.waitSignal(widget.download_failed, timeout=15000) as blocker:
        widget.start()

    assert "Traceback" not in blocker.args[0]
    assert "URLError" not in blocker.args[0]


def test_cancelling_closes_the_dialog_without_a_partial_file(
    dialog: DownloadDialog, qtbot, tmp_path: Path
) -> None:
    dialog.start()

    dialog.cancel()
    dialog.wait_for_completion()

    assert not (tmp_path / "vietocr.pth.part").exists()

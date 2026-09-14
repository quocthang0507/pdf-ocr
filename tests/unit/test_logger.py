"""Application logging writes UTF-8, rotates, and avoids duplicate sinks."""

from pathlib import Path

import pytest

from src.utils.logger import configure_logging, logger

pytestmark = pytest.mark.unit


def test_logs_reach_console_and_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        path = configure_logging(tmp_path)
        logger.info("Nhận diện tiếng Việt")
        assert path == tmp_path / "app.log"
        assert "Nhận diện tiếng Việt" in path.read_text("utf-8")
        assert "Nhận diện tiếng Việt" in capsys.readouterr().err
    finally:
        logger.remove()


def test_reconfiguration_does_not_duplicate_logs(tmp_path: Path) -> None:
    try:
        configure_logging(tmp_path)
        configure_logging(tmp_path)
        logger.warning("unique-event")
        assert (tmp_path / "app.log").read_text("utf-8").count("unique-event") == 1
    finally:
        logger.remove()


def test_rotates_file_at_configured_limit(tmp_path: Path) -> None:
    try:
        configure_logging(tmp_path, rotation=200)
        for _ in range(5):
            logger.info("a" * 150)
        assert len(list(tmp_path.glob("app*.log"))) > 1
        assert (tmp_path / "app.log").stat().st_size > 0
    finally:
        logger.remove()


def test_windowless_process_still_writes_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.setattr(sys, "stderr", None)
    try:
        path = configure_logging(tmp_path)
        logger.info("windowless-event")
        assert "windowless-event" in path.read_text("utf-8")
    finally:
        logger.remove()

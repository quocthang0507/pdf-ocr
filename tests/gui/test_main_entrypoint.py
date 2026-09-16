"""Startup applies the saved appearance and never dies on a weights problem."""

from __future__ import annotations

from pathlib import Path

import pytest

from src import main as entrypoint
from src.core.exceptions import WeightsError

pytestmark = pytest.mark.gui


@pytest.fixture
def started(qapp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Run main() against the live QApplication, without entering its event loop."""
    record: dict[str, object] = {}

    class Window:
        def __init__(self) -> None:
            record["window"] = self

        def show(self) -> None:
            record["shown"] = True

    monkeypatch.setattr(entrypoint, "QApplication", lambda _argv: qapp)
    monkeypatch.setattr(entrypoint, "MainWindow", Window)
    monkeypatch.setattr(entrypoint, "configure_logging", lambda: tmp_path / "app.log")
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    record["applied"] = []
    return record


def test_the_window_is_created_and_shown(started: dict[str, object]) -> None:
    code = entrypoint.main([])

    assert code == 0
    assert started["shown"] is True


def test_the_saved_language_and_theme_are_applied_before_the_window(
    started: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    applied: list[str] = []
    monkeypatch.setattr(
        entrypoint,
        "TranslationManager",
        lambda _app: type(
            "T", (), {"apply": lambda _s, value: applied.append(value)}
        )(),
    )
    monkeypatch.setattr(
        entrypoint,
        "StyleManager",
        lambda _app: type(
            "S", (), {"apply": lambda _s, value: applied.append(value)}
        )(),
    )

    entrypoint.main([])

    assert len(applied) == 2


def test_a_broken_appearance_setting_does_not_stop_startup(
    started: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(_application: object) -> object:
        raise RuntimeError("giao diện hỏng")

    monkeypatch.setattr(entrypoint, "StyleManager", failing)

    assert entrypoint.main([]) == 0
    assert started["shown"] is True


def test_an_unusable_weights_folder_is_reported_not_fatal(
    started: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    warnings: list[str] = []

    def failing() -> None:
        raise WeightsError("Không ghi được thư mục weights.")

    monkeypatch.setattr(entrypoint, "ModelWeightsManager", failing)
    monkeypatch.setattr(
        entrypoint.QMessageBox,
        "warning",
        lambda _p, _t, text, *a, **k: warnings.append(text),
    )

    assert entrypoint.main([]) == 0
    assert warnings == ["Không ghi được thư mục weights."]

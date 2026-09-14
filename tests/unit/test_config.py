"""Preferences remain durable across Qt availability and storage failures."""

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.config import ConfigManager, Preferences
from src.core.exceptions import ConfigError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("use_qsettings", [True, False])
def test_preferences_round_trip(tmp_path: Path, use_qsettings: bool) -> None:
    preferences = Preferences(
        weights_dir=str(tmp_path / "mô hình"), device="cpu", theme="dark"
    )
    manager = ConfigManager(tmp_path, use_qsettings=use_qsettings)
    manager.save(preferences)
    restored = ConfigManager(tmp_path, use_qsettings=use_qsettings).load()
    assert restored == preferences
    assert (
        json.loads((tmp_path / "preferences.json").read_text("utf-8"))["weights_dir"]
        == preferences.weights_dir
    )


def test_missing_settings_return_portable_defaults(tmp_path: Path) -> None:
    assert ConfigManager(tmp_path).load() == Preferences()
    assert Preferences().weights_dir is None


def test_qsettings_can_restore_without_json_backup(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path)
    manager.save(Preferences(theme="light"))
    (tmp_path / "preferences.json").unlink()
    assert ConfigManager(tmp_path).load().theme == "light"


def test_json_survives_unavailable_qt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.config as config

    ConfigManager(tmp_path).save(Preferences(device="cuda"))

    def unavailable(path: Path) -> None:
        raise ImportError("Qt unavailable")

    monkeypatch.setattr(config, "_create_qsettings", unavailable)
    manager = ConfigManager(tmp_path)
    assert manager.load().device == "cuda"
    manager.save(Preferences(device="cpu"))
    assert ConfigManager(tmp_path, use_qsettings=False).load().device == "cpu"


@pytest.mark.parametrize("content", ["{broken", "[]", '{"device": "invalid"}'])
def test_corrupt_json_returns_defaults_without_overwriting(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "preferences.json"
    path.write_text(content, encoding="utf-8")
    assert ConfigManager(tmp_path, use_qsettings=False).load() == Preferences()
    assert path.read_text("utf-8") == content


def test_failed_atomic_write_preserves_previous_preferences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.config as config

    manager = ConfigManager(tmp_path, use_qsettings=False)
    manager.save(Preferences(theme="light"))

    def denied(source: object, destination: object) -> None:
        raise PermissionError("private system path")

    monkeypatch.setattr(config.os, "replace", denied)
    with pytest.raises(ConfigError, match="Không thể lưu") as error:
        manager.save(Preferences(theme="dark"))
    assert "private system path" not in str(error.value)
    assert manager.load().theme == "light"
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize(
    "values",
    [{"theme": "unknown"}, {"device": "gpu"}, {"weights_dir": 42}],
)
def test_invalid_preferences_fail_fast(values: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Preferences(**values)


def test_preferences_are_immutable() -> None:
    preferences = Preferences()
    with pytest.raises(FrozenInstanceError):
        preferences.theme = "dark"


def test_cleanup_failure_does_not_mask_safe_storage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.config as config

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("sensitive/path")

    monkeypatch.setattr(config.os, "replace", denied)
    monkeypatch.setattr(Path, "unlink", denied)
    with pytest.raises(ConfigError) as caught:
        ConfigManager(tmp_path, use_qsettings=False).save(Preferences())
    assert "sensitive/path" not in str(caught.value)

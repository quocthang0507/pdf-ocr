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


def test_extended_preferences_round_trip_across_sqlite_and_json(
    tmp_path: Path,
) -> None:
    prefs = Preferences(
        theme="dark",
        restore_session=False,
        confirm_page_delete=False,
        default_zoom_mode="fit_width",
        page_color_mode="sepia",
        show_thumbnails=False,
        cache_size_pages=8,
        default_engine="paddle",
        default_dpi=400,
        auto_ocr_on_open=True,
        default_deskew=False,
        default_denoise=True,
        default_binarize=False,
        auto_spell_correction=False,
        confidence_threshold=0.75,
        custom_dictionary="UBND, HĐND",
        default_export_format="pdf",
        pdf_compression_level="max",
        max_worker_threads=8,
    )
    manager = ConfigManager(tmp_path, use_qsettings=False)
    manager.save(prefs)

    loaded = ConfigManager(tmp_path, use_qsettings=False).load()
    assert loaded == prefs


def test_export_and_import_profile_round_trip(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "cfg", use_qsettings=False)
    custom = Preferences(
        theme="dark",
        page_color_mode="night",
        default_dpi=350,
        custom_dictionary="Việt Nam, Hà Nội",
        pdf_compression_level="max",
    )
    profile_path = tmp_path / "my_profile.json"

    exported = manager.export_profile(profile_path, custom)
    imported = manager.import_profile(exported)

    assert exported == profile_path.resolve()
    assert imported == custom
    assert manager.load() == custom


def test_preferences_tone_style_round_trip_and_validation(tmp_path: Path) -> None:
    manager = ConfigManager(tmp_path / "tone_cfg", use_qsettings=False)
    prefs = Preferences(tone_style="traditional", custom_dictionary="cty => công ty")
    manager.save(prefs)

    restored = manager.load()
    assert restored.tone_style == "traditional"
    assert restored.custom_dictionary == "cty => công ty"

    with pytest.raises(ValueError, match="dấu thanh"):
        Preferences(tone_style="invalid_style")

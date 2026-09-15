"""The application database keeps settings durable, isolated, and injection-proof."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.config import ConfigManager, Preferences
from src.core.exceptions import ConfigError
from src.services.settings_store import PREFERENCES_SECTION, SettingsStore

pytestmark = pytest.mark.unit


@pytest.fixture
def store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "settings.db")


def test_stored_values_can_be_read_back(store: SettingsStore) -> None:
    store.set("giao diện", "theme", "dark")

    assert store.get("giao diện", "theme") == "dark"


def test_missing_values_fall_back_to_the_supplied_default(
    store: SettingsStore,
) -> None:
    assert store.get("giao diện", "theme") is None
    assert store.get("giao diện", "theme", "light") == "light"


def test_writing_the_same_key_twice_replaces_the_value(store: SettingsStore) -> None:
    store.set("engine", "device", "cpu")
    store.set("engine", "device", "cuda")

    assert store.section("engine") == {"device": "cuda"}


def test_sections_do_not_leak_into_each_other(store: SettingsStore) -> None:
    store.set("engine", "device", "cuda")
    store.set("session", "device", "ghi chú")

    assert store.section("engine") == {"device": "cuda"}
    assert store.section("session") == {"device": "ghi chú"}


def test_many_values_are_written_together(store: SettingsStore) -> None:
    store.set_many("engine", {"device": "cpu", "beam_width": "4"})

    assert store.section("engine") == {"device": "cpu", "beam_width": "4"}


def test_deleting_one_key_leaves_the_rest_of_the_section(store: SettingsStore) -> None:
    store.set_many("engine", {"device": "cpu", "beam_width": "4"})

    store.delete("engine", "device")

    assert store.section("engine") == {"beam_width": "4"}


def test_deleting_a_section_clears_every_key_in_it(store: SettingsStore) -> None:
    store.set_many("engine", {"device": "cpu", "beam_width": "4"})
    store.set("session", "last_file", "hoa-don.pdf")

    store.delete("engine")

    assert store.section("engine") == {}
    assert store.section("session") == {"last_file": "hoa-don.pdf"}


def test_values_survive_reopening_the_database(tmp_path: Path) -> None:
    path = tmp_path / "settings.db"
    with SettingsStore(path) as first:
        first.set("session", "last_file", "báo cáo.pdf")

    with SettingsStore(path) as second:
        assert second.get("session", "last_file") == "báo cáo.pdf"


def test_a_failed_transaction_writes_nothing(store: SettingsStore) -> None:
    store.set("engine", "device", "cpu")

    with pytest.raises(RuntimeError):
        with store.transaction() as write:
            write("engine", {"device": "cuda"})
            raise RuntimeError("bước lưu sau thất bại")

    assert store.get("engine", "device") == "cpu"


def test_a_successful_transaction_commits_every_write(store: SettingsStore) -> None:
    with store.transaction() as write:
        write("engine", {"device": "cuda"})
        write("session", {"page": "3"})

    assert store.get("engine", "device") == "cuda"
    assert store.get("session", "page") == "3"


@pytest.mark.parametrize(
    "name", ["", "  ", "a" * 65, "engine; DROP TABLE settings", "engine'--", "khối\x00"]
)
def test_unsafe_section_and_key_names_are_rejected(
    store: SettingsStore, name: str
) -> None:
    with pytest.raises(ValueError):
        store.set(name, "device", "cpu")
    with pytest.raises(ValueError):
        store.set("engine", name, "cpu")


def test_a_quoted_value_is_stored_verbatim_not_executed(store: SettingsStore) -> None:
    store.set("engine", "note", "'); DROP TABLE settings; --")

    assert store.get("engine", "note") == "'); DROP TABLE settings; --"
    assert store.section("engine") != {}


def test_non_text_values_are_rejected(store: SettingsStore) -> None:
    with pytest.raises(ValueError):
        store.set("engine", "device", 42)  # type: ignore[arg-type]


def test_a_damaged_database_reports_a_safe_error(tmp_path: Path) -> None:
    path = tmp_path / "settings.db"
    path.write_bytes(b"not a database at all, just noise" * 40)

    with pytest.raises(ConfigError) as caught:
        SettingsStore(path)

    assert "sqlite" not in str(caught.value).lower()


def test_an_unusable_location_reports_a_safe_error(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("tệp thường", encoding="utf-8")

    with pytest.raises(ConfigError):
        SettingsStore(blocker / "settings.db")


def test_closing_the_store_releases_the_connection(store: SettingsStore) -> None:
    store.set("engine", "device", "cpu")

    store.close()

    with pytest.raises(sqlite3.ProgrammingError):
        store.get("engine", "device")


def test_preferences_are_stored_in_the_application_database(tmp_path: Path) -> None:
    ConfigManager(tmp_path, use_qsettings=False).save(Preferences(theme="dark"))

    with SettingsStore(tmp_path / "settings.db") as store:
        assert store.get(PREFERENCES_SECTION, "theme") == "dark"


def test_the_database_is_preferred_over_the_json_copy(tmp_path: Path) -> None:
    ConfigManager(tmp_path, use_qsettings=False).save(Preferences(theme="dark"))
    (tmp_path / "preferences.json").write_text('{"theme": "light"}', encoding="utf-8")

    assert ConfigManager(tmp_path, use_qsettings=False).load().theme == "dark"


def test_legacy_json_preferences_are_imported_on_first_use(tmp_path: Path) -> None:
    (tmp_path / "preferences.json").write_text(
        '{"theme": "light", "device": "cuda"}', encoding="utf-8"
    )

    loaded = ConfigManager(tmp_path, use_qsettings=False).load()

    assert (loaded.theme, loaded.device) == ("light", "cuda")
    with SettingsStore(tmp_path / "settings.db") as store:
        assert store.get(PREFERENCES_SECTION, "device") == "cuda"


def test_an_unusable_database_still_leaves_json_preferences_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.config as config

    def unavailable(path: Path) -> SettingsStore:
        raise ConfigError()

    monkeypatch.setattr(config, "_create_store", unavailable)
    manager = ConfigManager(tmp_path, use_qsettings=False)

    manager.save(Preferences(device="cpu"))

    assert manager.load().device == "cpu"

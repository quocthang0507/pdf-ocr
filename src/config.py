"""Portable QSettings preferences backed by an atomic, durable JSON copy."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.constants import DEFAULT_LANGUAGE, LANGUAGE_NAMES
from src.core.exceptions import ConfigError
from src.services.settings_store import (
    DATABASE_NAME,
    PREFERENCES_SECTION,
    SettingsStore,
)
from src.utils.file_utils import get_app_root
from src.utils.logger import logger

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings

ZOOM_MODES = ("fit_page", "fit_width", "actual_size")
PAGE_COLOR_MODES = ("normal", "sepia", "night")
EXPORT_FORMATS = ("docx", "pdf", "txt", "md", "json", "xlsx")
PDF_COMPRESSION_LEVELS = ("fast", "balanced", "max")


@dataclass(frozen=True)
class Preferences:
    """Validated user preferences across 6 configuration categories."""

    weights_dir: str | None = None
    input_dir: str | None = None
    output_dir: str | None = None
    device: str = "auto"
    theme: str = "system"
    language: str = DEFAULT_LANGUAGE
    # 1. General & Appearance
    restore_session: bool = True
    confirm_page_delete: bool = True
    # 2. PDF Viewing
    default_zoom_mode: str = "fit_page"
    page_color_mode: str = "normal"
    show_thumbnails: bool = True
    cache_size_pages: int = 4
    # 3. Default OCR & Preprocessing
    default_engine: str = "vietocr"
    default_dpi: int = 300
    auto_ocr_on_open: bool = False
    default_deskew: bool = True
    default_denoise: bool = True
    default_binarize: bool = True
    # 4. Dictionary & Spellcheck
    auto_spell_correction: bool = True
    confidence_threshold: float = 0.80
    custom_dictionary: str = ""
    # 5. Export & PDF Output
    default_export_format: str = "docx"
    pdf_compression_level: str = "balanced"
    # 6. Performance & AI
    max_worker_threads: int = 4

    def __post_init__(self) -> None:
        _validate_preferences(self)


def _validate_preferences(prefs: Preferences) -> None:
    if prefs.device not in ("auto", "cpu", "cuda"):
        raise ValueError("Thiết bị phải là auto, cpu hoặc cuda.")
    if prefs.theme not in ("system", "light", "dark"):
        raise ValueError("Giao diện phải là system, light hoặc dark.")
    if prefs.language not in LANGUAGE_NAMES:
        raise ValueError("Ngôn ngữ giao diện không được hỗ trợ.")
    for path in (prefs.weights_dir, prefs.input_dir, prefs.output_dir):
        if path is not None and (
            not isinstance(path, str) or not path.strip() or "\x00" in path
        ):
            raise ValueError("Thư mục cấu hình phải là chuỗi đường dẫn hợp lệ.")
    if prefs.default_zoom_mode not in ZOOM_MODES:
        raise ValueError("Chế độ thu phóng mặc định không hợp lệ.")
    if prefs.page_color_mode not in PAGE_COLOR_MODES:
        raise ValueError("Chế độ màu trang PDF không hợp lệ.")
    if not (1 <= int(prefs.cache_size_pages) <= 32):
        raise ValueError("Bộ nhớ đệm trang phải nằm trong khoảng 1..32.")
    if not (72 <= int(prefs.default_dpi) <= 1200):
        raise ValueError("DPI mặc định phải nằm trong khoảng 72..1200.")
    if not (0.50 <= float(prefs.confidence_threshold) <= 0.99):
        raise ValueError("Ngưỡng độ tin cậy phải nằm trong khoảng 0.50..0.99.")
    if prefs.default_export_format not in EXPORT_FORMATS:
        raise ValueError("Định dạng xuất mặc định không hợp lệ.")
    if prefs.pdf_compression_level not in PDF_COMPRESSION_LEVELS:
        raise ValueError("Mức nén PDF không hợp lệ.")
    if not (1 <= int(prefs.max_worker_threads) <= 16):
        raise ValueError("Số luồng xử lý phải nằm trong khoảng 1..16.")


def _create_qsettings(path: Path) -> QSettings:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    return settings


_NULL_MARKER = ""


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("true", "1", "yes")


def _encode_fields(preferences: Preferences) -> dict[str, str]:
    """Store optional paths as an empty marker; SQLite rows are always text."""
    return {
        name: _NULL_MARKER if value is None else str(value)
        for name, value in asdict(preferences).items()
    }


def _build_preferences(values: Mapping[str, str]) -> Preferences:
    """Rebuild preferences from text rows, restoring the 'use default' marker."""
    fields = {
        name: None if value == _NULL_MARKER else value for name, value in values.items()
    }
    return Preferences(
        weights_dir=fields.get("weights_dir"),
        input_dir=fields.get("input_dir"),
        output_dir=fields.get("output_dir"),
        device=fields.get("device") or "auto",
        theme=fields.get("theme") or "system",
        language=fields.get("language") or DEFAULT_LANGUAGE,
        restore_session=_parse_bool(fields.get("restore_session"), True),
        confirm_page_delete=_parse_bool(fields.get("confirm_page_delete"), True),
        default_zoom_mode=fields.get("default_zoom_mode") or "fit_page",
        page_color_mode=fields.get("page_color_mode") or "normal",
        show_thumbnails=_parse_bool(fields.get("show_thumbnails"), True),
        cache_size_pages=int(fields.get("cache_size_pages") or 4),
        default_engine=fields.get("default_engine") or "vietocr",
        default_dpi=int(fields.get("default_dpi") or 300),
        auto_ocr_on_open=_parse_bool(fields.get("auto_ocr_on_open"), False),
        default_deskew=_parse_bool(fields.get("default_deskew"), True),
        default_denoise=_parse_bool(fields.get("default_denoise"), True),
        default_binarize=_parse_bool(fields.get("default_binarize"), True),
        auto_spell_correction=_parse_bool(fields.get("auto_spell_correction"), True),
        confidence_threshold=float(fields.get("confidence_threshold") or 0.80),
        custom_dictionary=values.get("custom_dictionary", ""),
        default_export_format=fields.get("default_export_format") or "docx",
        pdf_compression_level=fields.get("pdf_compression_level") or "balanced",
        max_worker_threads=int(fields.get("max_worker_threads") or 4),
    )


def _create_store(path: Path) -> SettingsStore:
    return SettingsStore(path)


def _decode_preferences(payload: str) -> Preferences:
    values: Any = json.loads(payload)
    if not isinstance(values, dict):
        raise ValueError("Preferences must be a JSON object.")
    return Preferences(**values)


class ConfigManager:
    """Stateful storage adapter; returned preferences are always immutable."""

    def __init__(
        self, config_dir: str | Path | None = None, *, use_qsettings: bool = True
    ) -> None:
        self.directory = (
            Path(config_dir) if config_dir is not None else get_app_root() / "config"
        )
        self.json_path = self.directory / "preferences.json"
        self.database_path = self.directory / DATABASE_NAME
        self._settings: QSettings | None = None
        self._store: SettingsStore | None = None
        try:
            self._store = _create_store(self.database_path)
        except ConfigError:
            logger.warning("Cơ sở dữ liệu cấu hình không khả dụng; dùng bản sao JSON.")
        if use_qsettings:
            try:
                self._settings = _create_qsettings(self.directory / "preferences.ini")
            except (ImportError, OSError, RuntimeError):
                logger.warning("QSettings không khả dụng; sử dụng cấu hình JSON.")

    def load(self) -> Preferences:
        """Prefer the database, then the JSON mirror, then QSettings."""
        stored = self._load_database()
        if stored is not None:
            return stored
        legacy = self._load_json()
        if legacy is not None:
            self._import_legacy(legacy)
            return legacy
        return self._load_qsettings()

    def _load_database(self) -> Preferences | None:
        if self._store is None:
            return None
        try:
            values = self._store.section(PREFERENCES_SECTION)
            return _build_preferences(values) if values else None
        except (ConfigError, ValueError, TypeError):
            logger.warning(
                "Cấu hình trong cơ sở dữ liệu không hợp lệ; thử bản sao JSON."
            )
            return None

    def _load_json(self) -> Preferences | None:
        try:
            return _decode_preferences(self.json_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.debug("Chưa có bản sao cấu hình JSON.")
        except (OSError, ValueError, TypeError):
            logger.warning("Không đọc được cấu hình JSON; thử bản sao QSettings.")
        return None

    def _import_legacy(self, preferences: Preferences) -> None:
        """Carry preferences written by an older version into the database."""
        if self._store is None:
            return
        try:
            self._store.set_many(PREFERENCES_SECTION, _encode_fields(preferences))
        except (ConfigError, ValueError):
            logger.warning("Không chuyển được cấu hình cũ vào cơ sở dữ liệu.")

    def _load_qsettings(self) -> Preferences:
        if self._settings is None:
            return Preferences()
        try:
            self._settings.sync()
            if self._settings.status() != self._settings.Status.NoError:
                raise OSError("QSettings read failed.")
            payload = self._settings.value("preferences")
            if payload is None:
                return Preferences()
            if not isinstance(payload, str):
                raise ValueError("QSettings preferences must contain JSON.")
            return _decode_preferences(payload)
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.warning("Không đọc được QSettings; sử dụng cấu hình mặc định.")
            return Preferences()

    def save(self, preferences: Preferences) -> None:
        """Commit atomically; keep the previous file intact if persistence fails."""
        if not isinstance(preferences, Preferences):
            raise TypeError("Cấu hình phải là đối tượng Preferences.")
        payload = json.dumps(asdict(preferences), ensure_ascii=False, indent=2)
        self._save_database(preferences, payload)
        if self._settings is not None:
            try:
                self._settings.setValue("preferences", payload)
                self._settings.sync()
                if self._settings.status() != self._settings.Status.NoError:
                    raise OSError("QSettings write failed.")
            except (OSError, RuntimeError):
                logger.warning("Không ghi được QSettings; cấu hình đã lưu bằng JSON.")

    def export_profile(
        self, path: str | Path, preferences: Preferences | None = None
    ) -> Path:
        """Export preferences to an external JSON profile file."""
        active = preferences if preferences is not None else self.load()
        target = Path(path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(active), ensure_ascii=False, indent=2)
        target.write_text(payload, encoding="utf-8")
        return target

    def import_profile(self, path: str | Path) -> Preferences:
        """Load and validate an external JSON profile file, then persist it."""
        source = Path(path).resolve()
        preferences = _decode_preferences(source.read_text(encoding="utf-8"))
        self.save(preferences)
        return preferences

    def _save_database(self, preferences: Preferences, payload: str) -> None:
        """Advance the database only once the JSON mirror is safely on disk."""
        if self._store is None:
            self._save_json(payload)
            return
        with self._store.transaction() as write:
            write(PREFERENCES_SECTION, _encode_fields(preferences))
            self._save_json(payload)

    def _save_json(self, payload: str) -> None:
        temporary: Path | None = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.json_path)
            temporary = None
        except OSError as error:
            raise ConfigError() from error
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Không thể dọn tệp cấu hình tạm sau lỗi ghi.")

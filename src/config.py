"""Portable QSettings preferences backed by an atomic, durable JSON copy."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.core.exceptions import ConfigError
from src.utils.file_utils import get_app_root
from src.utils.logger import logger

if TYPE_CHECKING:
    from PySide6.QtCore import QSettings


@dataclass(frozen=True)
class Preferences:
    """Validated user preferences; None selects the portable default location."""

    weights_dir: str | None = None
    input_dir: str | None = None
    output_dir: str | None = None
    device: str = "auto"
    theme: str = "system"

    def __post_init__(self) -> None:
        if self.device not in ("auto", "cpu", "cuda"):
            raise ValueError("Thiết bị phải là auto, cpu hoặc cuda.")
        if self.theme not in ("system", "light", "dark"):
            raise ValueError("Giao diện phải là system, light hoặc dark.")
        for path in (self.weights_dir, self.input_dir, self.output_dir):
            if path is not None and (
                not isinstance(path, str) or not path.strip() or "\x00" in path
            ):
                raise ValueError("Thư mục cấu hình phải là chuỗi đường dẫn hợp lệ.")


def _create_qsettings(path: Path) -> QSettings:
    from PySide6.QtCore import QSettings

    settings = QSettings(str(path), QSettings.Format.IniFormat)
    settings.setFallbacksEnabled(False)
    return settings


def _decode_preferences(payload: str) -> Preferences:
    values = json.loads(payload)
    if not isinstance(values, dict):
        raise ValueError("Preferences must be a JSON object.")
    return Preferences(**values)


class ConfigManager:
    """Stateful storage adapter; returned preferences are always immutable.

    JSON is committed first and wins when present, so a failed Qt sync never
    restores an older value. QSettings supplies native Qt integration and can
    recover preferences when the JSON copy is missing or damaged. Both files
    stay inside the application directory by default, including portable mode.
    """

    def __init__(
        self, config_dir: str | Path | None = None, *, use_qsettings: bool = True
    ) -> None:
        self.directory = (
            Path(config_dir) if config_dir is not None else get_app_root() / "config"
        )
        self.json_path = self.directory / "preferences.json"
        self._settings: QSettings | None = None
        if use_qsettings:
            try:
                self._settings = _create_qsettings(self.directory / "preferences.ini")
            except (ImportError, OSError, RuntimeError):
                logger.warning("QSettings không khả dụng; sử dụng cấu hình JSON.")

    def load(self) -> Preferences:
        """Load valid preferences; preserve damaged files for diagnosis."""
        try:
            return _decode_preferences(self.json_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.debug("Chưa có bản sao cấu hình JSON.")
        except (OSError, ValueError, TypeError):
            logger.warning("Không đọc được cấu hình JSON; thử bản sao QSettings.")
        return self._load_qsettings()

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
        self._save_json(payload)
        if self._settings is not None:
            try:
                self._settings.setValue("preferences", payload)
                self._settings.sync()
                if self._settings.status() != self._settings.Status.NoError:
                    raise OSError("QSettings write failed.")
            except (OSError, RuntimeError):
                logger.warning("Không ghi được QSettings; cấu hình đã lưu bằng JSON.")

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

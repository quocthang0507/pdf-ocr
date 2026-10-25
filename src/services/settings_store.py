"""Application-owned SQLite store for settings, history, and session values."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

from src.core.exceptions import ConfigError
from src.core.models import OCRDocument, OCRPage
from src.utils.file_utils import get_app_root
from src.utils.logger import logger

DATABASE_NAME = "settings.db"
PREFERENCES_SECTION = "preferences"
SESSION_SECTION = "session"
ENGINE_SECTION = "engine"
OCR_CACHE_SECTION = "ocr_cache"

_NAME_PATTERN = re.compile(r"[^\W_][\w .-]{0,63}", flags=re.UNICODE)
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS settings ("
    " section TEXT NOT NULL,"
    " key TEXT NOT NULL,"
    " value TEXT NOT NULL,"
    " PRIMARY KEY (section, key))"
)
_UPSERT = (
    "INSERT INTO settings (section, key, value) VALUES (?, ?, ?)"
    " ON CONFLICT (section, key) DO UPDATE SET value = excluded.value"
)

Writer = Callable[[str, Mapping[str, str]], None]


def _name(value: str, label: str) -> str:
    """Reject anything that is not a plain identifier before it reaches SQL."""
    if not isinstance(value, str) or _NAME_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} không hợp lệ.")
    return value


def _value(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Giá trị cấu hình phải là chuỗi văn bản.")
    return value


def document_cache_key(path: str | Path) -> str:
    """Compute a safe, deterministic SQLite key from a file's path, size, and mtime."""
    resolved = Path(path).resolve()
    try:
        stat = resolved.stat()
        fingerprint = f"{resolved}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        fingerprint = str(resolved)
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:40]
    return f"doc_{digest}"


class SettingsStore:
    """Stateful SQLite adapter; each public write commits one transaction.

    Every statement is parameterised and every section or key name is validated,
    so caller supplied text never reaches SQL as code. A lock serialises access
    because background workers and the GUI thread share one connection.
    """

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.path = (
            Path(database_path)
            if database_path is not None
            else get_app_root() / "config" / DATABASE_NAME
        )
        self._lock = threading.Lock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                self.path, isolation_level=None, check_same_thread=False
            )
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(_SCHEMA)
        except (sqlite3.Error, OSError) as error:
            logger.warning("Không mở được cơ sở dữ liệu cấu hình: {}", error)
            raise ConfigError(
                "Không thể mở cơ sở dữ liệu cấu hình của ứng dụng."
            ) from error

    # -- reads ------------------------------------------------------------

    def get(self, section: str, key: str, default: str | None = None) -> str | None:
        rows = self._query(
            "SELECT value FROM settings WHERE section = ? AND key = ?",
            (_name(section, "Tên nhóm cấu hình"), _name(key, "Khóa cấu hình")),
        )
        return str(rows[0][0]) if rows else default

    def section(self, section: str) -> dict[str, str]:
        rows = self._query(
            "SELECT key, value FROM settings WHERE section = ?",
            (_name(section, "Tên nhóm cấu hình"),),
        )
        return {str(key): str(value) for key, value in rows}

    # -- writes -----------------------------------------------------------

    def set(self, section: str, key: str, value: str) -> None:
        self.set_many(section, {key: value})

    def set_many(self, section: str, values: Mapping[str, str]) -> None:
        """Store a whole group of keys as one transaction."""
        with self.transaction() as write:
            write(section, values)

    def delete(self, section: str, key: str | None = None) -> None:
        """Remove one key, or the whole section when no key is given."""
        checked = _name(section, "Tên nhóm cấu hình")
        if key is None:
            self._execute("DELETE FROM settings WHERE section = ?", [(checked,)])
            return
        self._execute(
            "DELETE FROM settings WHERE section = ? AND key = ?",
            [(checked, _name(key, "Khóa cấu hình"))],
        )

    @contextmanager
    def transaction(self) -> Iterator[Writer]:
        """Group writes so a later failure in the caller rolls all of them back."""
        pending: list[tuple[str, str, str]] = []

        def write(section: str, values: Mapping[str, str]) -> None:
            checked = _name(section, "Tên nhóm cấu hình")
            pending.extend(
                (checked, _name(key, "Khóa cấu hình"), _value(value))
                for key, value in values.items()
            )

        yield write
        self._execute(_UPSERT, pending)

    # -- OCR page session cache -------------------------------------------

    def save_ocr_pages(self, path: str | Path, pages: Sequence[OCRPage]) -> None:
        """Persist recognised OCRPage items for a document keyed by file fingerprint."""
        resolved = Path(path).resolve()
        doc = OCRDocument(tuple(pages), source_path=str(resolved), title=resolved.stem)
        self.set(OCR_CACHE_SECTION, document_cache_key(resolved), doc.to_json())

    def load_ocr_pages(self, path: str | Path) -> dict[int, OCRPage]:
        """Load cached OCRPage items for path, or return an empty dict on miss."""
        raw = self.get(OCR_CACHE_SECTION, document_cache_key(path))
        if not raw:
            return {}
        try:
            doc = OCRDocument.from_json(raw)
            return {page.page_number: page for page in doc.pages}
        except (ValueError, TypeError):
            logger.warning("Bản lưu đệm OCR của '{}' không hợp lệ; bỏ qua.", path)
            return {}

    def clear_ocr_pages(self, path: str | Path) -> None:
        """Remove any cached OCRPage items for path."""
        self.delete(OCR_CACHE_SECTION, document_cache_key(path))

    # -- lifecycle --------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SettingsStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- sqlite plumbing --------------------------------------------------

    def _query(
        self, statement: str, parameters: tuple[str, ...]
    ) -> list[tuple[str, ...]]:
        with self._lock:
            try:
                cursor = self._connection.execute(statement, parameters)
                return [tuple(row) for row in cursor.fetchall()]
            except sqlite3.ProgrammingError:
                raise
            except sqlite3.Error as error:
                raise ConfigError("Không thể đọc cấu hình ứng dụng.") from error

    def _execute(self, statement: str, rows: Sequence[tuple[str, ...]]) -> None:
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.executemany(statement, rows)
                self._connection.execute("COMMIT")
            except sqlite3.ProgrammingError:
                raise
            except sqlite3.Error as error:
                self._connection.execute("ROLLBACK")
                raise ConfigError("Không thể lưu cấu hình ứng dụng.") from error

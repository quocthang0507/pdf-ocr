"""Open-closed registry for output document formats."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from src.core.exceptions import ExportError
from src.exporters.base_exporter import BaseExporter

ExporterT = TypeVar("ExporterT", bound=type[BaseExporter])


@dataclass(frozen=True)
class ExporterMetadata:
    format_id: str
    name: str
    extensions: tuple[str, ...]


class ExporterRegistry:
    """Process-wide exporter catalogue with lazy instance creation."""

    _exporters: dict[str, tuple[type[BaseExporter], ExporterMetadata]] = {}

    @classmethod
    def register(
        cls, format_id: str, name: str, *, extensions: Sequence[str]
    ) -> Callable[[ExporterT], ExporterT]:
        normalized = cls._validate_registration(format_id, name, extensions)

        def decorator(exporter: ExporterT) -> ExporterT:
            if not issubclass(exporter, BaseExporter):
                raise TypeError("Exporter phải kế thừa BaseExporter.")
            if format_id in cls._exporters:
                raise ValueError(f"Định dạng xuất '{format_id}' đã được đăng ký.")
            metadata = ExporterMetadata(format_id, name, normalized)
            exporter.FORMAT_ID = format_id
            exporter.EXTENSIONS = normalized
            cls._exporters[format_id] = (exporter, metadata)
            return exporter

        return decorator

    @staticmethod
    def _validate_registration(
        format_id: str, name: str, extensions: Sequence[str]
    ) -> tuple[str, ...]:
        if not format_id or not format_id.replace("_", "").isalnum():
            raise ValueError("Mã định dạng xuất không hợp lệ.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tên định dạng xuất không được để trống.")
        normalized = tuple(extension.lower() for extension in extensions)
        if not normalized or any(
            not extension.startswith(".") or len(extension) < 2
            for extension in normalized
        ):
            raise ValueError("Danh sách đuôi tệp xuất không hợp lệ.")
        return normalized

    @classmethod
    def get(cls, format_id: str) -> BaseExporter:
        try:
            exporter = cls._exporters[format_id][0]
        except KeyError as error:
            raise ExportError(
                f"Không tìm thấy định dạng xuất '{format_id}'."
            ) from error
        return exporter()

    @classmethod
    def describe(cls, format_id: str) -> ExporterMetadata:
        try:
            return cls._exporters[format_id][1]
        except KeyError as error:
            raise ExportError(
                f"Không tìm thấy định dạng xuất '{format_id}'."
            ) from error

    @classmethod
    def available(cls) -> tuple[ExporterMetadata, ...]:
        return tuple(item[1] for item in cls._exporters.values())

    @classmethod
    def snapshot(cls) -> dict[str, tuple[type[BaseExporter], ExporterMetadata]]:
        return dict(cls._exporters)

    @classmethod
    def restore(
        cls, snapshot: dict[str, tuple[type[BaseExporter], ExporterMetadata]]
    ) -> None:
        cls._exporters = dict(snapshot)


def register_exporter(
    format_id: str, name: str, *, extensions: Sequence[str]
) -> Callable[[ExporterT], ExporterT]:
    return ExporterRegistry.register(format_id, name, extensions=extensions)

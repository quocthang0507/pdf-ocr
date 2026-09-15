"""Validated, atomic base contract for document exporters."""

from __future__ import annotations

import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from src.core.exceptions import ExportError
from src.core.models import OCRDocument


class BaseExporter(ABC):
    """Export immutable OCR documents without exposing partial output files."""

    FORMAT_ID = "base"
    EXTENSIONS: tuple[str, ...] = ()
    MIN_FREE_BYTES = 1024 * 1024

    def export(self, document: OCRDocument, output_path: str | Path) -> Path:
        if not isinstance(document, OCRDocument):
            raise ExportError("Dữ liệu tài liệu xuất không hợp lệ.")
        destination = self._validate_destination(output_path)
        temporary = self._temporary_path(destination)
        try:
            self._export(document, temporary)
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise ExportError("Bộ xuất không tạo được tệp dữ liệu hợp lệ.")
            os.replace(temporary, destination)
        except ExportError:
            raise
        except Exception as error:
            raise ExportError(
                "Không thể xuất tài liệu sang định dạng yêu cầu."
            ) from error
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _validate_destination(self, output_path: str | Path) -> Path:
        try:
            destination = Path(output_path).expanduser().resolve()
        except (OSError, RuntimeError, TypeError) as error:
            raise ExportError("Đường dẫn xuất không hợp lệ.") from error
        if destination.exists() and destination.is_dir():
            raise ExportError("Đường dẫn xuất phải là tệp, không phải thư mục.")
        if destination.suffix.lower() not in self.EXTENSIONS:
            expected = ", ".join(self.EXTENSIONS)
            raise ExportError(f"Đường dẫn xuất phải có đuôi tệp: {expected}.")
        parent = destination.parent
        if not parent.is_dir():
            raise ExportError("Thư mục đích không tồn tại.")
        if not os.access(parent, os.W_OK):
            raise ExportError("Không có quyền ghi vào thư mục đích.")
        try:
            free_bytes = shutil.disk_usage(parent).free
        except OSError as error:
            raise ExportError("Không thể kiểm tra dung lượng thư mục đích.") from error
        if free_bytes < self.MIN_FREE_BYTES:
            raise ExportError("Không đủ dung lượng trống để xuất tài liệu.")
        return destination

    @staticmethod
    def _temporary_path(destination: Path) -> Path:
        try:
            temporary = tempfile.NamedTemporaryFile(
                prefix=f".{destination.stem}.",
                suffix=destination.suffix,
                dir=destination.parent,
                delete=False,
            )
            temporary.close()
            return Path(temporary.name)
        except OSError as error:
            raise ExportError("Không thể tạo tệp tạm trong thư mục đích.") from error

    @abstractmethod
    def _export(self, document: OCRDocument, output_path: Path) -> None:
        """Write a complete document to the provided temporary path."""

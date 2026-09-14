"""Central model storage and cache hooks, without importing any AI framework."""

import os
import re
import shutil
import sys
from pathlib import Path

from src.core.exceptions import WeightsError
from src.utils.file_utils import (
    contained_directory,
    ensure_writable_directory,
    get_app_root,
    normalize_directory,
)
from src.utils.logger import logger

_CACHE_DIRECTORIES = {
    "TORCH_HOME": "torch",
    "HF_HOME": "huggingface",
    "HF_HUB_CACHE": "huggingface/hub",
    "HUGGINGFACE_HUB_CACHE": "huggingface/hub",
    "TRANSFORMERS_CACHE": "huggingface/hub",
    "HF_XET_CACHE": "huggingface/xet",
    "HF_ASSETS_CACHE": "huggingface/assets",
    "HUGGINGFACE_ASSETS_CACHE": "huggingface/assets",
    "PADDLE_HOME": "paddle",
    "PADDLE_PDX_CACHE_HOME": "paddle/paddlex",
    "EASYOCR_MODULE_PATH": "easyocr",
}
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


class ModelWeightsManager:
    """Stateful storage service; initialize before importing provider libraries.

    Cache hooks change the current process environment. Already imported AI
    libraries may have cached their paths; changing directories while engines
    are loaded must be coordinated by the application service layer.
    No downloads, weight moves, or model imports occur here.
    """

    DEFAULT_SUBDIRS = (
        "vietocr",
        "paddle",
        "surya",
        "trocr",
        "easyocr",
        "torch",
        "huggingface",
    )

    def __init__(
        self, custom_path: str | Path | None = None, *, required_bytes: int = 0
    ) -> None:
        try:
            path = custom_path if custom_path is not None else self._default_path()
            self._base_path = normalize_directory(path)
            self._base_path.mkdir(parents=True, exist_ok=True)
            self.ensure_disk_space(required_bytes)
            ensure_writable_directory(self._base_path)
            self._ensure_directories()
            self.apply_environment_hooks()
        except (OSError, ValueError, RuntimeError) as error:
            raise WeightsError(
                "Không thể sử dụng thư mục weights. "
                "Vui lòng chọn đường dẫn hợp lệ có quyền ghi."
            ) from error

    @staticmethod
    def _default_path() -> Path:
        root = get_app_root()
        candidate = root / "src" / "models"
        if getattr(sys, "frozen", False) and not candidate.is_dir():
            return root / "models"
        return candidate

    @property
    def base_path(self) -> Path:
        return self._base_path

    def _ensure_directories(self) -> None:
        paths = set(self.DEFAULT_SUBDIRS) | set(_CACHE_DIRECTORIES.values())
        # Validate all destinations before writing into any subdirectory.
        resolved = [contained_directory(self.base_path, name) for name in sorted(paths)]
        for path in resolved:
            ensure_writable_directory(path)

    def apply_environment_hooks(self) -> None:
        """Redirect legacy and current cache variables as one validated update."""
        try:
            hooks = {
                variable: str(contained_directory(self.base_path, relative))
                for variable, relative in _CACHE_DIRECTORIES.items()
            }
        except (OSError, ValueError, RuntimeError) as error:
            raise WeightsError(
                "Thư mục cache phải nằm trong thư mục weights."
            ) from error
        os.environ.update(hooks)
        logger.info("Đã chuyển hướng cache mô hình sang thư mục weights đã chọn.")

    def get_engine_weights_dir(self, engine_id: str) -> Path:
        """Allow new provider IDs while rejecting traversal and Windows devices."""
        if (
            not isinstance(engine_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", engine_id) is None
            or engine_id.upper() in _RESERVED_NAMES
        ):
            raise WeightsError("Mã mô hình không hợp lệ.")
        try:
            path = contained_directory(self.base_path, engine_id)
            self.ensure_disk_space()
            ensure_writable_directory(path)
            return path
        except (OSError, ValueError, RuntimeError) as error:
            raise WeightsError("Không thể tạo thư mục cho mô hình đã chọn.") from error

    def get_free_disk_space_gb(self) -> float:
        """Return available space in GiB (1024**3 bytes)."""
        try:
            return shutil.disk_usage(self.base_path).free / (1024**3)
        except OSError as error:
            raise WeightsError("Không thể kiểm tra dung lượng ổ đĩa.") from error

    def ensure_disk_space(self, required_bytes: int = 0) -> None:
        """Check download capacity; a zero budget still rejects full disks."""
        if type(required_bytes) is not int or required_bytes < 0:
            raise ValueError("Dung lượng yêu cầu phải là số nguyên không âm.")
        try:
            available = shutil.disk_usage(self.base_path).free
        except OSError as error:
            raise WeightsError("Không thể kiểm tra dung lượng ổ đĩa.") from error
        if available < max(1, required_bytes):
            raise WeightsError(
                "Không đủ dung lượng trống. Vui lòng giải phóng ổ đĩa hoặc đổi thư mục."
            )

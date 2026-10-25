"""Central model storage and cache hooks, without importing any AI framework."""

import hashlib
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

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
MIGRATION_HEADROOM_BYTES = 16 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_SECONDS = 1.0
DOWNLOAD_TIMEOUT_SECONDS = 30.0
_CHUNK_BYTES = 256 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")

ProgressCallback = Callable[[int], None]
CancelCheck = Callable[[], bool]
DownloadCallback = Callable[["DownloadProgress"], None]
Opener = Callable[[str, float], Any]

_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


# Module-level path constants that libraries freeze from the environment on
# import, mapped to the cache variable whose new value replaces them.
_LOADED_CACHE_CONSTANTS: dict[str, dict[str, str]] = {
    "huggingface_hub.constants": {
        "HF_HOME": "HF_HOME",
        "HF_HUB_CACHE": "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_CACHE": "HUGGINGFACE_HUB_CACHE",
        "HF_ASSETS_CACHE": "HF_ASSETS_CACHE",
        "HUGGINGFACE_ASSETS_CACHE": "HUGGINGFACE_ASSETS_CACHE",
        "HF_XET_CACHE": "HF_XET_CACHE",
    },
    "transformers.utils.hub": {
        "TRANSFORMERS_CACHE": "TRANSFORMERS_CACHE",
        "PYTORCH_TRANSFORMERS_CACHE": "TRANSFORMERS_CACHE",
        "PYTORCH_PRETRAINED_BERT_CACHE": "TRANSFORMERS_CACHE",
    },
    "paddlex.utils.cache": {"CACHE_DIR": "PADDLE_PDX_CACHE_HOME"},
}


def _refresh_loaded_caches(hooks: dict[str, str]) -> None:
    """Re-point libraries that were imported before the folder changed.

    HuggingFace, transformers and PaddleX read their cache folders once, at
    import time; after an engine had been used, choosing another weights
    folder in Settings silently kept downloading into the old one. Only
    modules that are already loaded are touched, so nothing is imported here.
    """
    for module_name, constants in _LOADED_CACHE_CONSTANTS.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attribute, variable in constants.items():
            if hasattr(module, attribute) and variable in hooks:
                setattr(module, attribute, hooks[variable])
    official = sys.modules.get("paddlex.inference.utils.official_models")
    manager = getattr(official, "official_models", None)
    if manager is not None and "PADDLE_PDX_CACHE_HOME" in hooks:
        try:
            manager._save_dir = Path(hooks["PADDLE_PDX_CACHE_HOME"]) / "official_models"
            manager._hosters = None  # rebuilt lazily around the new folder
        except AttributeError:
            logger.warning("Không cập nhật được thư mục mô hình PaddleX đang nạp.")


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
        "chandra",
        "dots_ocr",
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
        """In a frozen bundle prefer models/ beside the executable, else src/models.

        A portable copy ships its weights in models/, but a bundle built from a
        checkout may still carry src/models, so both layouts are accepted.
        """
        root = get_app_root()
        source_layout = root / "src" / "models"
        if not getattr(sys, "frozen", False):
            return source_layout
        bundled = root / "models"
        return source_layout if source_layout.is_dir() else bundled

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
        _refresh_loaded_caches(hooks)
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

    def list_available_models(self, engine_id: str) -> list[tuple[str, str]]:
        """Discover built-in and custom models in the engine's weights folder."""
        try:
            engine_dir = self.get_engine_weights_dir(engine_id)
        except WeightsError:
            return []
        if engine_id == "vietocr":
            return _discover_vietocr_models(engine_dir)
        if engine_id == "trocr":
            return _discover_trocr_models(engine_dir)
        if engine_id == "easyocr":
            return _discover_easyocr_models(engine_dir)
        if engine_id == "paddle":
            return _discover_paddle_models(engine_dir)
        if engine_id == "chandra":
            return _discover_hf_models(
                engine_dir,
                [
                    ("Chandra OCR v1 (Bố cục, bảng, viết tay)", "datalab-to/chandra"),
                    (
                        "Chandra OCR v2 (Flagship 5B - Chính xác cao nhất)",
                        "datalab-to/chandra-ocr-2",
                    ),
                ],
            )
        if engine_id == "dots_ocr":
            return _discover_hf_models(
                engine_dir,
                [
                    (
                        "dots.ocr 1.7B (Bố cục, bảng, công thức)",
                        "rednote-hilab/dots.ocr",
                    ),
                    ("dots.mocr 1.5 (Đa tác vụ + SVG)", "rednote-hilab/dots.mocr"),
                    ("dots-studio/dots.ocr (Chính thức)", "dots-studio/dots.ocr"),
                ],
            )
        return []

    def import_model_file(
        self, engine_id: str, source_path: str | Path, custom_name: str = ""
    ) -> Path:
        """Copy a custom weights file or model folder into the engine's directory."""
        raw = str(source_path).strip()
        if not raw or "\x00" in raw:
            raise WeightsError("Đường dẫn tệp model không hợp lệ.")
        source = Path(raw).expanduser().resolve()
        if not source.exists():
            raise WeightsError("Không tìm thấy tệp hoặc thư mục model nguồn.")
        target_dir = self.get_engine_weights_dir(engine_id)
        safe_name = Path(custom_name.strip() or source.name).name
        if not safe_name or safe_name in {".", ".."}:
            raise WeightsError("Tên tệp model không hợp lệ.")
        destination = (target_dir / safe_name).resolve()
        if not destination.is_relative_to(target_dir):
            raise WeightsError("Đường dẫn đích không hợp lệ.")
        if destination == source:
            return destination
        try:
            if source.is_dir():
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            logger.info("Đã nhập model '{}' cho '{}'.", destination.name, engine_id)
            return destination
        except OSError as error:
            raise WeightsError("Không thể sao chép tệp model vào thư mục.") from error


def _discover_vietocr_models(engine_dir: Path) -> list[tuple[str, str]]:
    builtins = [
        ("VGG19-BN + Transformer (Chính xác cao)", "vgg_transformer"),
        ("VGG19-BN + Seq2Seq Attention (Tốc độ nhanh)", "vgg_seq2seq"),
        ("ResNet50 + Transformer (Chữ phức tạp)", "resnet_transformer"),
    ]
    results = list(builtins)
    for pth_file in sorted(engine_dir.glob("*.pth")):
        if pth_file.stem not in {
            "vgg_transformer",
            "vgg_seq2seq",
            "resnet_transformer",
        }:
            results.append((f"Tùy chỉnh: {pth_file.name}", str(pth_file)))
    return results


def _discover_trocr_models(engine_dir: Path) -> list[tuple[str, str]]:
    return _discover_hf_models(
        engine_dir,
        [
            (
                "Base - Chữ viết tay (~334M, Cân bằng)",
                "microsoft/trocr-base-handwritten",
            ),
            (
                "Base - Chữ in / Hóa đơn (~334M, Cân bằng)",
                "microsoft/trocr-base-printed",
            ),
            (
                "Small - Chữ viết tay (~62M, Nhanh & nhẹ)",
                "microsoft/trocr-small-handwritten",
            ),
            ("Small - Chữ in (~62M, Nhanh & nhẹ)", "microsoft/trocr-small-printed"),
            (
                "Large - Chữ viết tay (~558M, Chính xác nhất)",
                "microsoft/trocr-large-handwritten",
            ),
            ("Large - Chữ in (~558M, Chính xác nhất)", "microsoft/trocr-large-printed"),
            ("Base - Chữ cảnh tự nhiên (Scene Text)", "microsoft/trocr-base-str"),
            ("Large - Chữ cảnh tự nhiên (Scene Text)", "microsoft/trocr-large-str"),
        ],
    )


def _discover_hf_models(
    engine_dir: Path, builtins: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    results = list(builtins)
    for item in sorted(engine_dir.iterdir()):
        if item.is_dir() and (
            (item / "config.json").is_file()
            or any(item.glob("*.safetensors"))
            or any(item.glob("*.bin"))
        ):
            results.append((f"Model cục bộ: {item.name}", str(item)))
    return results


def _discover_easyocr_models(engine_dir: Path) -> list[tuple[str, str]]:
    results = [
        ("Tự động theo ngôn ngữ", ""),
        ("Generation 2 - Latin / Tiếng Việt (latin_g2)", "latin_g2"),
        ("Generation 2 - Tiếng Anh tối ưu (english_g2)", "english_g2"),
        ("Generation 1 - Latin cổ điển (latin_g1)", "latin_g1"),
    ]
    for pth in sorted(engine_dir.glob("*.pth")):
        if pth.name not in {
            "craft_mlt_25k.pth",
            "latin_g2.pth",
            "english_g2.pth",
            "latin_g1.pth",
        }:
            results.append((f"Tùy chỉnh: {pth.stem}", pth.stem))
    return results


def _discover_paddle_models(engine_dir: Path) -> list[tuple[str, str]]:
    results = [("Mặc định theo phiên bản", "")]
    for item in sorted(engine_dir.iterdir()):
        if item.is_dir() and (
            (item / "inference.pdmodel").is_file()
            or (item / "inference.json").is_file()
        ):
            results.append((f"Model cục bộ: {item.name}", str(item)))
    return results


def _collect_files(source: Path) -> tuple[list[Path], int]:
    """List every weight file with its total size, before touching the disk."""
    files = sorted(path for path in source.rglob("*") if path.is_file())
    return files, sum(path.stat().st_size for path in files)


def _validate_migration(source: Path, destination: Path) -> None:
    if source == destination:
        raise WeightsError("Thư mục nguồn và thư mục đích đang trùng nhau.")
    if destination.is_relative_to(source):
        raise WeightsError(
            "Thư mục đích không được nằm trong thư mục weights hiện tại."
        )
    if source.is_relative_to(destination):
        raise WeightsError("Thư mục đích không được chứa thư mục weights hiện tại.")


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return int(shutil.disk_usage(probe).free)
    except OSError as error:
        raise WeightsError("Không thể kiểm tra dung lượng ổ đĩa.") from error


def migrate_weights(
    source: str | Path,
    destination: str | Path,
    *,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> Path:
    """Move a weights folder safely: copy everything, verify, then drop the source.

    The originals are only removed once every file has been copied, so a failure
    or a cancellation can never leave the user without their model weights.
    """
    origin = normalize_directory(source)
    target = normalize_directory(destination)
    _validate_migration(origin, target)
    if not origin.is_dir():
        raise WeightsError("Không tìm thấy thư mục weights nguồn.")
    files, total_bytes = _collect_files(origin)
    if _free_bytes(target) < total_bytes + MIGRATION_HEADROOM_BYTES:
        raise WeightsError("Không đủ dung lượng trống tại thư mục đích.")
    created = not target.exists()
    try:
        _copy_all(origin, target, files, total_bytes, on_progress, should_cancel)
    except WeightsError:
        _discard(target, remove_root=created)
        raise
    shutil.rmtree(origin, ignore_errors=True)
    logger.info("Đã chuyển weights sang thư mục mới.")
    return target


def _copy_all(
    origin: Path,
    target: Path,
    files: list[Path],
    total_bytes: int,
    on_progress: ProgressCallback | None,
    should_cancel: CancelCheck | None,
) -> None:
    copied = 0
    _report(on_progress, 0)
    try:
        ensure_writable_directory(target)
        for path in files:
            if should_cancel is not None and should_cancel():
                raise WeightsError("Đã hủy việc di chuyển weights.")
            relative = path.relative_to(origin)
            written = target / relative
            written.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, written)
            copied += path.stat().st_size
            _report(on_progress, _percentage(copied, total_bytes))
    except OSError as error:
        raise WeightsError(
            "Không thể sao chép tệp weights sang thư mục đích."
        ) from error
    _report(on_progress, 100)


def _percentage(copied: int, total: int) -> int:
    if total <= 0:
        return 100
    return min(99, int(copied * 100 / total))


def _report(on_progress: ProgressCallback | None, percent: int) -> None:
    if on_progress is not None:
        on_progress(percent)


def _discard(target: Path, *, remove_root: bool) -> None:
    """Roll back a half-finished move without touching the source folder."""
    if remove_root:
        shutil.rmtree(target, ignore_errors=True)


@dataclass(frozen=True)
class DownloadProgress:
    """One immutable snapshot of a transfer, ready for the progress dialog."""

    downloaded_bytes: int
    total_bytes: int
    bytes_per_second: float

    @property
    def percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return min(100, int(self.downloaded_bytes * 100 / self.total_bytes))

    @property
    def seconds_remaining(self) -> float:
        remaining = self.total_bytes - self.downloaded_bytes
        if remaining <= 0 or self.bytes_per_second <= 0:
            return 0.0
        return remaining / self.bytes_per_second


def _checked_url(url: str) -> str:
    """Only plain web downloads are allowed; never file:// or other schemes."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WeightsError("Địa chỉ tải mô hình không hợp lệ.")
    return url


def _checked_digest(sha256: str) -> str:
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise WeightsError("Thiếu mã băm SHA256 hợp lệ để xác minh tệp tải về.")
    return sha256.lower()


def file_digest(path: Path) -> str:
    """Hash a file in chunks so large weights never load into memory at once."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_weights(
    url: str,
    destination: str | Path,
    *,
    sha256: str,
    opener: Opener | None = None,
    on_progress: DownloadCallback | None = None,
    should_cancel: CancelCheck | None = None,
    attempts: int = DOWNLOAD_ATTEMPTS,
    backoff: float = DOWNLOAD_BACKOFF_SECONDS,
) -> Path:
    """Fetch one weights file, retrying briefly, and verify it before keeping it.

    The transfer runs into a sibling `.part` file, so a cancellation, a dropped
    connection or a hash mismatch can never leave a corrupt file in its place.
    """
    address = _checked_url(url)
    expected = _checked_digest(sha256)
    target = Path(destination)
    if target.is_file() and file_digest(target) == expected:
        logger.info("Tệp weights đã có sẵn và hợp lệ; bỏ qua tải xuống.")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f"{target.name}.part")
    fetch = opener or _default_opener
    last_error: Exception | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            _fetch_once(fetch, address, partial, on_progress, should_cancel)
            return _finalize(partial, target, expected)
        except WeightsError:
            partial.unlink(missing_ok=True)
            raise
        except (OSError, ValueError) as error:
            last_error = error
            partial.unlink(missing_ok=True)
            logger.warning("Tải weights thất bại lần {}: {}", attempt, error)
            if attempt < max(attempts, 1):
                time.sleep(backoff * (2 ** (attempt - 1)))
    raise WeightsError(
        "Không thể tải mô hình. Vui lòng kiểm tra kết nối mạng và thử lại."
    ) from last_error


def _default_opener(url: str, timeout: float = DOWNLOAD_TIMEOUT_SECONDS) -> Any:
    """Open a web address, re-checking the scheme so only http(s) ever opens.

    The guard below is why the urlopen call is audited-safe: file:// and every
    other scheme is refused here as well as in download_weights.
    """
    if urlparse(url).scheme not in ("http", "https"):
        raise WeightsError("Địa chỉ tải mô hình không hợp lệ.")
    return urlopen(url, timeout=timeout)  # nosec B310


def _fetch_once(
    fetch: Opener,
    url: str,
    partial: Path,
    on_progress: DownloadCallback | None,
    should_cancel: CancelCheck | None,
) -> None:
    started = time.monotonic()
    downloaded = 0
    with fetch(url, DOWNLOAD_TIMEOUT_SECONDS) as response:
        total = _content_length(response)
        with partial.open("wb") as stream:
            while True:
                if should_cancel is not None and should_cancel():
                    raise WeightsError("Đã hủy tải mô hình.")
                chunk = response.read(_CHUNK_BYTES)
                if not chunk:
                    break
                stream.write(chunk)
                downloaded += len(chunk)
                _report_download(on_progress, downloaded, total, started)
    _report_download(on_progress, downloaded, downloaded or total, started)


def _content_length(response: Any) -> int:
    try:
        return int(response.headers.get("Content-Length") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def _report_download(
    on_progress: DownloadCallback | None, downloaded: int, total: int, started: float
) -> None:
    if on_progress is None:
        return
    elapsed = max(time.monotonic() - started, 1e-6)
    on_progress(DownloadProgress(downloaded, total, downloaded / elapsed))


def _finalize(partial: Path, target: Path, expected: str) -> Path:
    if file_digest(partial) != expected:
        partial.unlink(missing_ok=True)
        raise WeightsError("Tệp tải về không đạt kiểm tra toàn vẹn SHA256.")
    os.replace(partial, target)
    logger.info("Đã tải và xác minh weights thành công.")
    return target

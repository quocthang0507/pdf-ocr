"""Execution device discovery that never hard-fails on a broken accelerator."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from src.utils.logger import logger

AUTO = "auto"
CPU = "cpu"
CUDA = "cuda"
SUPPORTED_DEVICES = (AUTO, CPU, CUDA)
_BYTES_PER_GB = 1024**3


@dataclass(frozen=True)
class DeviceInfo:
    """One selectable execution target and what the machine can actually offer."""

    identifier: str
    name: str
    available: bool
    total_memory_gb: float = 0.0

    @property
    def description(self) -> str:
        if not self.available:
            return f"{self.name} (không khả dụng)"
        if self.total_memory_gb:
            return f"{self.name} ({self.total_memory_gb:.1f} GB VRAM)"
        return self.name


def _load_torch() -> Any | None:
    """Import torch lazily; the application must start without it installed."""
    try:
        return import_module("torch")
    except ImportError:
        logger.debug("Không tìm thấy torch; chỉ hỗ trợ CPU.")
        return None


def _probe_cuda() -> DeviceInfo:
    """Report the first CUDA device, treating any driver problem as unavailable."""
    torch = _load_torch()
    if torch is None:
        return DeviceInfo(CUDA, "GPU CUDA", available=False)
    try:
        if not torch.cuda.is_available():
            return DeviceInfo(CUDA, "GPU CUDA", available=False)
        properties = torch.cuda.get_device_properties(0)
        return DeviceInfo(
            CUDA,
            str(properties.name),
            available=True,
            total_memory_gb=float(properties.total_memory) / _BYTES_PER_GB,
        )
    except (AttributeError, RuntimeError, OSError, ValueError) as error:
        logger.warning("Không kiểm tra được GPU: {}", error)
        return DeviceInfo(CUDA, "GPU CUDA", available=False)


def detect_devices() -> tuple[DeviceInfo, ...]:
    """List every execution target the settings dialog may offer."""
    cuda = _probe_cuda()
    automatic = DeviceInfo(
        AUTO,
        "Tự động phát hiện" + (" — dùng GPU" if cuda.available else " — dùng CPU"),
        available=True,
    )
    return (automatic, DeviceInfo(CPU, "CPU", available=True), cuda)


def resolve_device(preference: str) -> str:
    """Turn a stored preference into the device the engines should actually use."""
    if preference not in SUPPORTED_DEVICES:
        raise ValueError("Thiết bị phải là auto, cpu hoặc cuda.")
    if preference != AUTO:
        return preference
    return CUDA if _probe_cuda().available else CPU

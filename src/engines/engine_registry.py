"""Open-closed OCR provider registry and accelerator-safe session lifecycle."""

from __future__ import annotations

import gc
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from typing import TypeVar

from src.core.exceptions import OCREngineError
from src.engines.base_engine import BaseOCREngine
from src.services.weights_manager import ModelWeightsManager

ProviderT = TypeVar("ProviderT", bound=type[BaseOCREngine])


@dataclass(frozen=True)
class EngineMetadata:
    engine_id: str
    name: str
    description: str
    supports_handwriting: bool = False
    supports_tables: bool = False


class EngineRegistry:
    """Process-wide provider catalogue; providers remain uninstantiated until get."""

    _providers: dict[str, tuple[type[BaseOCREngine], EngineMetadata]] = {}

    @classmethod
    def register(
        cls,
        engine_id: str,
        name: str,
        description: str,
        *,
        supports_handwriting: bool = False,
        supports_tables: bool = False,
    ) -> Callable[[ProviderT], ProviderT]:
        if not engine_id or not engine_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Mã OCR engine không hợp lệ.")

        def decorator(provider: ProviderT) -> ProviderT:
            if not issubclass(provider, BaseOCREngine):
                raise TypeError("Provider phải kế thừa BaseOCREngine.")
            if engine_id in cls._providers:
                raise ValueError(f"OCR engine '{engine_id}' đã được đăng ký.")
            metadata = EngineMetadata(
                engine_id,
                name,
                description,
                supports_handwriting,
                supports_tables,
            )
            provider.ENGINE_ID = engine_id
            provider.ENGINE_NAME = name
            cls._providers[engine_id] = (provider, metadata)
            return provider

        return decorator

    @classmethod
    def get_class(cls, engine_id: str) -> type[BaseOCREngine]:
        try:
            return cls._providers[engine_id][0]
        except KeyError as error:
            raise OCREngineError(f"Không tìm thấy OCR engine '{engine_id}'.") from error

    @classmethod
    def get(
        cls,
        engine_id: str,
        *,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> BaseOCREngine:
        return cls.get_class(engine_id)(weights_manager=weights_manager, config=config)

    @classmethod
    def describe(cls, engine_id: str) -> EngineMetadata:
        try:
            return cls._providers[engine_id][1]
        except KeyError as error:
            raise OCREngineError(f"Không tìm thấy OCR engine '{engine_id}'.") from error

    @classmethod
    def available(cls) -> tuple[EngineMetadata, ...]:
        return tuple(item[1] for item in cls._providers.values())

    @classmethod
    def unregister(cls, engine_id: str, *, missing_ok: bool = False) -> None:
        if engine_id not in cls._providers and not missing_ok:
            raise OCREngineError(f"Không tìm thấy OCR engine '{engine_id}'.")
        cls._providers.pop(engine_id, None)

    @classmethod
    def snapshot(cls) -> dict[str, tuple[type[BaseOCREngine], EngineMetadata]]:
        return dict(cls._providers)

    @classmethod
    def restore(
        cls, snapshot: dict[str, tuple[type[BaseOCREngine], EngineMetadata]]
    ) -> None:
        cls._providers = dict(snapshot)


def register_engine(
    engine_id: str,
    name: str,
    description: str,
    *,
    supports_handwriting: bool = False,
    supports_tables: bool = False,
) -> Callable[[ProviderT], ProviderT]:
    return EngineRegistry.register(
        engine_id,
        name,
        description,
        supports_handwriting=supports_handwriting,
        supports_tables=supports_tables,
    )


def release_accelerator_memory(device: str) -> None:
    try:
        if device.startswith("cuda"):
            torch = import_module("torch")
            cuda = getattr(torch, "cuda", None)
            if cuda is not None and cuda.is_available():
                cuda.empty_cache()
    except (ImportError, AttributeError, RuntimeError):
        return
    finally:
        gc.collect()


@contextmanager
def engine_session(
    engine_id: str,
    *,
    device: str = "cpu",
    weights_manager: ModelWeightsManager | None = None,
    config: Mapping[str, object] | None = None,
) -> Iterator[BaseOCREngine]:
    options = dict(config or {})
    options["device"] = device
    engine = EngineRegistry.get(
        engine_id, weights_manager=weights_manager, config=options
    )
    try:
        engine.load_model()
        yield engine
    finally:
        try:
            engine.unload_model()
        finally:
            release_accelerator_memory(device)

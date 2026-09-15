"""Framework-neutral OCR provider contract and configuration validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from src.core.exceptions import OCREngineError
from src.core.models import OCRPage
from src.services.weights_manager import ModelWeightsManager

ConfigValidator = Callable[[object], bool]


@dataclass(frozen=True)
class ConfigField:
    """One provider option with a default and a side-effect-free validator."""

    default: object
    validator: ConfigValidator


class BaseOCREngine(ABC):
    """Stateful lazy model adapter returning the shared immutable domain model."""

    ENGINE_ID = "base"
    ENGINE_NAME = "OCR engine"
    CONFIG_SCHEMA: Mapping[str, ConfigField] = {}

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._config = self._validate_config(config or {})
        self._weights_manager = weights_manager or ModelWeightsManager()
        self._weights_dir = self._weights_manager.get_engine_weights_dir(self.ENGINE_ID)
        self._is_loaded = False

    @property
    def config(self) -> dict[str, object]:
        return dict(self._config)

    @property
    def weights_dir(self) -> Path:
        return self._weights_dir

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    def _validate_config(self, supplied: Mapping[str, object]) -> dict[str, object]:
        unknown = set(supplied) - set(self.CONFIG_SCHEMA)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise OCREngineError(f"Tham số cấu hình không hỗ trợ: {names}.")
        validated: dict[str, object] = {}
        for name, field in self.CONFIG_SCHEMA.items():
            value = supplied.get(name, field.default)
            try:
                valid = field.validator(value)
            except (TypeError, ValueError):
                valid = False
            if not valid:
                raise OCREngineError(f"Tham số {name} không hợp lệ.")
            validated[name] = value
        return validated

    def load_model(self, *, device: str | None = None) -> None:
        """Load once and hide backend diagnostics behind a safe provider error."""
        if self._is_loaded:
            return
        if device is not None:
            candidate = dict(self._config)
            candidate["device"] = device
            self._config = self._validate_config(candidate)
        try:
            self._load_model()
            self._is_loaded = True
        except OCREngineError:
            raise
        except Exception as error:
            raise OCREngineError(f"Không thể nạp {self.ENGINE_NAME}.") from error

    def recognize(self, image: object, *, page_number: int = 1) -> OCRPage:
        if not self._is_loaded:
            raise OCREngineError(f"{self.ENGINE_NAME} chưa được nạp.")
        if type(page_number) is not int or page_number < 1:
            raise OCREngineError("Số trang OCR phải là số nguyên dương.")
        try:
            page = self._recognize(image, page_number)
        except OCREngineError:
            raise
        except Exception as error:
            raise OCREngineError(
                f"{self.ENGINE_NAME} không thể nhận diện ảnh."
            ) from error
        if not isinstance(page, OCRPage):
            raise OCREngineError(
                f"{self.ENGINE_NAME} trả về kết quả không đúng định dạng."
            )
        return page

    def unload_model(self) -> None:
        """Release provider references; repeated calls are safe."""
        try:
            self._unload_model()
        except Exception as error:
            raise OCREngineError(f"Không thể giải phóng {self.ENGINE_NAME}.") from error
        finally:
            self._is_loaded = False

    @abstractmethod
    def _load_model(self) -> None:
        """Create backend objects. Called at most once per loaded lifecycle."""

    @abstractmethod
    def _recognize(self, image: object, page_number: int) -> OCRPage:
        """Recognize one already-decoded image."""

    @abstractmethod
    def _unload_model(self) -> None:
        """Drop all strong references to backend models and tensors."""

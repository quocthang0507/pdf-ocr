"""Lazy EasyOCR fallback adapter."""

from collections.abc import Mapping, Sequence
from importlib import import_module
from typing import Any, cast

from src.core.models import OCRPage
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import register_engine
from src.engines.result_builder import LineResult, build_page
from src.services.weights_manager import ModelWeightsManager


def _languages(value: object) -> bool:
    return (
        isinstance(value, (tuple, list))
        and bool(value)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _device(value: object) -> bool:
    return isinstance(value, str) and (
        value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")
    )


@register_engine(
    "easyocr",
    "EasyOCR",
    "Provider OCR đa ngôn ngữ dự phòng.",
)
class EasyOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "langs": ConfigField(("vi", "en"), _languages),
        "device": ConfigField("cpu", _device),
        "beam_width": ConfigField(
            5, lambda value: type(value) is int and 1 <= value <= 100
        ),
        "allow_download": ConfigField(False, lambda value: type(value) is bool),
    }

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._reader: Any | None = None
        super().__init__(weights_manager, config)

    def _load_model(self) -> None:
        easyocr = import_module("easyocr")
        device = str(self._config["device"])
        gpu: bool | str = device not in {"cpu", "auto"}
        if device.startswith("cuda:"):
            gpu = device
        langs = cast(Sequence[str], self._config["langs"])
        self._reader = easyocr.Reader(
            list(langs),
            gpu=gpu,
            model_storage_directory=str(self.weights_dir),
            download_enabled=bool(self._config["allow_download"]),
            verbose=False,
        )

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        if self._reader is None:
            raise RuntimeError("EasyOCR reader is unavailable.")
        beam_width = cast(int, self._config["beam_width"])
        raw = self._reader.readtext(
            image,
            detail=1,
            paragraph=False,
            beamWidth=beam_width,
        )
        lines: list[LineResult] = []
        for item in raw:
            if not isinstance(item, (tuple, list)) or len(item) < 3:
                continue
            points, text, confidence = item[:3]
            lines.append((points, str(text), float(confidence)))
        return build_page(image, page_number, lines)

    def _unload_model(self) -> None:
        self._reader = None

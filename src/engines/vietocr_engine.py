"""Lazy VietOCR adapter for Vietnamese printed text lines."""

from collections.abc import Mapping
from importlib import import_module
from typing import Any

from src.core.models import OCRPage
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import register_engine
from src.engines.result_builder import (
    as_pil_image,
    build_page,
    image_size,
    rectangle_polygon,
)
from src.services.weights_manager import ModelWeightsManager


def _device(value: object) -> bool:
    return isinstance(value, str) and (
        value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")
    )


@register_engine(
    "vietocr",
    "VietOCR",
    "Nhận diện chuyên sâu văn bản in tiếng Việt.",
)
class VietOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "architecture": ConfigField(
            "vgg_transformer",
            lambda value: isinstance(value, str)
            and value in {"vgg_transformer", "vgg_seq2seq"},
        ),
        "device": ConfigField("cpu", _device),
    }

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._predictor: Any | None = None
        super().__init__(weights_manager, config)

    def _load_model(self) -> None:
        config_module = import_module("vietocr.tool.config")
        predictor_module = import_module("vietocr.tool.predictor")
        architecture = str(self._config["architecture"])
        model_config = config_module.Cfg.load_config_from_name(architecture)
        model_config["weights"] = str(self.weights_dir / f"{architecture}.pth")
        model_config["device"] = self._resolved_device()
        cnn_config = model_config.setdefault("cnn", {})
        cnn_config["pretrained"] = False
        self._predictor = predictor_module.Predictor(model_config)

    def _resolved_device(self) -> str:
        device = str(self._config["device"])
        if device == "auto":
            return "cpu"
        return "cuda:0" if device == "cuda" else device

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        if self._predictor is None:
            raise RuntimeError("VietOCR predictor is unavailable.")
        output = self._predictor.predict(as_pil_image(image), return_prob=True)
        if isinstance(output, tuple):
            text, confidence = output
        else:
            text, confidence = output, 1.0
        width, height = image_size(image)
        line = (rectangle_polygon(width, height), str(text), float(confidence))
        return build_page(image, page_number, (line,))

    def _unload_model(self) -> None:
        self._predictor = None

"""Lazy Hugging Face TrOCR adapter for printed and handwritten line images."""

from collections.abc import Mapping
from importlib import import_module
from typing import Any, cast

from src.core.models import OCRPage
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import register_engine
from src.engines.result_builder import (
    LineResult,
    as_pil_image,
    build_page,
    image_size,
    rectangle_polygon,
    segment_lines,
)
from src.services.weights_manager import ModelWeightsManager

_CHECKPOINTS = {
    "microsoft/trocr-base-handwritten",
    "microsoft/trocr-base-printed",
}


@register_engine(
    "trocr",
    "Transformer OCR (TrOCR)",
    "Nhận diện chữ viết tay hoặc chữ in bằng Transformer.",
    supports_handwriting=True,
)
class TransformerOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "checkpoint": ConfigField(
            "microsoft/trocr-base-handwritten",
            lambda value: isinstance(value, str) and value in _CHECKPOINTS,
        ),
        "device": ConfigField(
            "cpu",
            lambda value: isinstance(value, str)
            and (value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")),
        ),
        "timeout_seconds": ConfigField(
            30.0,
            lambda value: isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0 < value <= 300,
        ),
        "max_new_tokens": ConfigField(
            128, lambda value: type(value) is int and 1 <= value <= 512
        ),
        "allow_download": ConfigField(False, lambda value: type(value) is bool),
    }

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._processor: Any | None = None
        self._model: Any | None = None
        super().__init__(weights_manager, config)

    def _load_model(self) -> None:
        transformers = import_module("transformers")
        checkpoint = str(self._config["checkpoint"])
        options = {
            "cache_dir": str(self.weights_dir),
            "local_files_only": not bool(self._config["allow_download"]),
        }
        self._processor = transformers.TrOCRProcessor.from_pretrained(
            checkpoint, **options
        )
        self._model = transformers.VisionEncoderDecoderModel.from_pretrained(
            checkpoint, **options
        )
        self._model.to(self._resolved_device())
        self._model.eval()

    def _resolved_device(self) -> str:
        device = str(self._config["device"])
        if device != "auto":
            return device
        try:
            torch = import_module("torch")
            cuda = getattr(torch, "cuda", None)
            if cuda is not None and cuda.is_available():
                return "cuda"
        except (ImportError, AttributeError, RuntimeError):
            return "cpu"
        return "cpu"

    def _recognize_multi_line(
        self, image: object, width: int, height: int
    ) -> list[LineResult]:
        boxes = segment_lines(image)
        if not boxes:
            return []
        crops: list[Any] = []
        pad = 2
        pil_image = as_pil_image(image)
        for x, y, w, h in boxes:
            crop_box = (
                max(0, x - pad),
                max(0, y - pad),
                min(width, x + w + pad),
                min(height, y + h + pad),
            )
            crops.append(pil_image.crop(crop_box))

        if self._processor is None or self._model is None:
            return []
        pixels = self._processor(images=crops, return_tensors="pt").pixel_values
        pixels = pixels.to(self._resolved_device())
        max_new_tokens = cast(int, self._config["max_new_tokens"])
        timeout_seconds = cast(float, self._config["timeout_seconds"])
        generated = self._model.generate(
            pixels,
            max_new_tokens=max_new_tokens,
            max_time=float(timeout_seconds),
        )
        decoded = self._processor.batch_decode(generated, skip_special_tokens=True)
        lines: list[LineResult] = []
        for (x, y, w, h), text in zip(boxes, decoded, strict=False):
            stripped = text.strip()
            if stripped:
                poly = (
                    (float(x), float(y)),
                    (float(x + w), float(y)),
                    (float(x + w), float(y + h)),
                    (float(x), float(y + h)),
                )
                lines.append((poly, stripped, 1.0))
        return lines

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        if self._processor is None or self._model is None:
            raise RuntimeError("TrOCR model is unavailable.")
        width, height = image_size(image)
        if height > 80:
            lines = self._recognize_multi_line(image, width, height)
            if lines:
                return build_page(image, page_number, lines)
        pixels = self._processor(images=image, return_tensors="pt").pixel_values
        pixels = pixels.to(self._resolved_device())
        max_new_tokens = cast(int, self._config["max_new_tokens"])
        timeout_seconds = cast(float, self._config["timeout_seconds"])
        generated = self._model.generate(
            pixels,
            max_new_tokens=max_new_tokens,
            max_time=float(timeout_seconds),
        )
        decoded = self._processor.batch_decode(generated, skip_special_tokens=True)
        text = decoded[0] if decoded else ""
        return build_page(
            image,
            page_number,
            ((rectangle_polygon(width, height), text, 1.0),),
        )

    def _unload_model(self) -> None:
        self._model = None
        self._processor = None

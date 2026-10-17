"""Lazy VietOCR adapter for Vietnamese printed text lines."""

from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Any

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

_segment_lines = segment_lines


def _device(value: object) -> bool:
    return isinstance(value, str) and (
        value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")
    )


_BUILTIN_ARCHITECTURES = {"vgg_transformer", "vgg_seq2seq", "resnet_transformer"}


def _valid_architecture(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return (
        value in _BUILTIN_ARCHITECTURES
        or value.lower().endswith(".pth")
        or Path(value).is_file()
    )


@register_engine(
    "vietocr",
    "VietOCR",
    "Nhận diện chuyên sâu văn bản tiếng Việt (VGG/ResNet + Transformer/Seq2Seq).",
)
class VietOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "architecture": ConfigField("vgg_transformer", _valid_architecture),
        "custom_weights_path": ConfigField(
            "",
            lambda value: value is None or isinstance(value, (str, Path)),
        ),
        "base_architecture": ConfigField(
            "vgg_transformer",
            lambda value: isinstance(value, str) and value in _BUILTIN_ARCHITECTURES,
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
        custom_path = self._config.get("custom_weights_path")
        base_arch, weights_path = self._resolve_weights(architecture, custom_path)
        try:
            model_config = config_module.Cfg.load_config_from_name(base_arch)
        except Exception:
            model_config = config_module.Cfg.load_config_from_name("vgg_transformer")
            if base_arch == "resnet_transformer":
                model_config["backbone"] = "resnet50"
        model_config["weights"] = str(weights_path)
        model_config["device"] = self._resolved_device()
        cnn_config = model_config.setdefault("cnn", {})
        cnn_config["pretrained"] = False
        self._predictor = predictor_module.Predictor(model_config)

    def _resolve_weights(
        self, architecture: str, custom_path: object
    ) -> tuple[str, Path]:
        base_arch = str(self._config.get("base_architecture") or "vgg_transformer")
        if custom_path and str(custom_path).strip():
            path = Path(str(custom_path)).expanduser()
            if not path.is_absolute() and (self.weights_dir / path).is_file():
                path = self.weights_dir / path
            if "seq2seq" in path.name.lower():
                base_arch = "vgg_seq2seq"
            elif "resnet" in path.name.lower():
                base_arch = "resnet_transformer"
            return base_arch, path
        if architecture in _BUILTIN_ARCHITECTURES:
            return architecture, self.weights_dir / f"{architecture}.pth"
        path = Path(architecture).expanduser()
        if not path.is_absolute() and (self.weights_dir / path).is_file():
            path = self.weights_dir / path
        if "seq2seq" in path.name.lower():
            base_arch = "vgg_seq2seq"
        elif "resnet" in path.name.lower():
            base_arch = "resnet_transformer"
        return base_arch, path

    def _resolved_device(self) -> str:
        device = str(self._config["device"])
        if device == "auto":
            return "cpu"
        return "cuda:0" if device == "cuda" else device

    def _predict_crops(self, crops: list[Any]) -> tuple[list[str], list[float]]:
        if self._predictor is None:
            return [], []
        if hasattr(self._predictor, "predict_batch"):
            try:
                sents, probs = self._predictor.predict_batch(crops, return_prob=True)
                return [str(s) for s in sents], [float(p) for p in probs]
            except Exception:  # nosec B110
                pass
        fallback_sents: list[str] = []
        fallback_probs: list[float] = []
        for crop in crops:
            output = self._predictor.predict(crop, return_prob=True)
            text, prob = output if isinstance(output, tuple) else (output, 1.0)
            fallback_sents.append(str(text))
            fallback_probs.append(float(prob))
        return fallback_sents, fallback_probs

    def _recognize_multi_line(
        self, image: object, width: int, height: int
    ) -> list[LineResult]:
        boxes = _segment_lines(image)
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

        sents, probs = self._predict_crops(crops)
        lines: list[LineResult] = []
        for (x, y, w, h), text, prob in zip(boxes, sents, probs, strict=False):
            stripped = text.strip()
            if stripped:
                poly = (
                    (float(x), float(y)),
                    (float(x + w), float(y)),
                    (float(x + w), float(y + h)),
                    (float(x), float(y + h)),
                )
                lines.append((poly, stripped, float(prob)))
        return lines

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        if self._predictor is None:
            raise RuntimeError("VietOCR predictor is unavailable.")
        width, height = image_size(image)
        if height > 80:
            lines = self._recognize_multi_line(image, width, height)
            if lines:
                return build_page(image, page_number, lines)
        output = self._predictor.predict(as_pil_image(image), return_prob=True)
        text, confidence = output if isinstance(output, tuple) else (output, 1.0)
        line = (rectangle_polygon(width, height), str(text), float(confidence))
        return build_page(image, page_number, (line,))

    def _unload_model(self) -> None:
        self._predictor = None

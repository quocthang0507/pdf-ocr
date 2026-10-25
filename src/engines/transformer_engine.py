"""Lazy Hugging Face TrOCR adapter for printed and handwritten line images."""

from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Any, cast

import numpy as np

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
    "microsoft/trocr-small-handwritten",
    "microsoft/trocr-base-handwritten",
    "microsoft/trocr-large-handwritten",
    "microsoft/trocr-small-printed",
    "microsoft/trocr-base-printed",
    "microsoft/trocr-large-printed",
    "microsoft/trocr-base-str",
    "microsoft/trocr-large-str",
}


def _valid_checkpoint(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    return value in _CHECKPOINTS or "/" in value or Path(value).is_dir()


#: TrOCR squeezes every crop into a square; past this width-to-height ratio
#: a text line is so compressed that only its beginning gets read.
MAX_LINE_ASPECT = 8.0


def _widest_gap_centre(ink: np.ndarray) -> int:
    """Centre of the widest run of the emptiest columns: a word space, not
    the hairline gap between two letters."""
    blank = ink <= ink.min()
    best_start, best_length, start = 0, 0, None
    for column, is_blank in enumerate([*blank.tolist(), False]):
        if is_blank and start is None:
            start = column
        elif not is_blank and start is not None:
            if column - start > best_length:
                best_start, best_length = start, column - start
            start = None
    return best_start + best_length // 2


def split_wide_line(crop: Any) -> list[Any]:
    """Cut a long line image into readable pieces at the gaps between words."""
    width, height = crop.size
    if height <= 0 or width <= height * MAX_LINE_ASPECT:
        return [crop]
    gray = np.asarray(crop.convert("L"), dtype=np.float64)
    ink = (gray < gray.mean() - 0.5 * gray.std()).sum(axis=0)
    count = int(np.ceil(width / (height * MAX_LINE_ASPECT)))
    step = width / count
    reach = max(1, int(height * 1.5))
    cuts = [0]
    for index in range(1, count):
        target = int(index * step)
        low = max(cuts[-1] + 1, target - reach)
        high = min(width - 1, target + reach)
        if low >= high:
            continue
        cuts.append(low + _widest_gap_centre(ink[low:high]))
    cuts.append(width)
    return [
        crop.crop((left, 0, right, height))
        for left, right in zip(cuts, cuts[1:], strict=False)
        if right - left > 1
    ]


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
            _valid_checkpoint,
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
        candidate = Path(checkpoint).expanduser()
        is_local = candidate.is_dir()
        if not is_local and (self.weights_dir / checkpoint).is_dir():
            candidate = self.weights_dir / checkpoint
            checkpoint = str(candidate.resolve())
            is_local = True
        elif is_local:
            checkpoint = str(candidate.resolve())

        options = {
            "cache_dir": str(self.weights_dir),
            "local_files_only": is_local or not bool(self._config["allow_download"]),
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
        pieces: list[Any] = []
        owners: list[int] = []
        for index, crop in enumerate(crops):
            for piece in split_wide_line(crop):
                pieces.append(piece)
                owners.append(index)
        texts = self._generate(pieces)
        joined = ["" for _ in crops]
        for owner, text in zip(owners, texts, strict=False):
            joined[owner] = f"{joined[owner]} {text.strip()}".strip()
        lines: list[LineResult] = []
        for (x, y, w, h), text in zip(boxes, joined, strict=False):
            if text:
                poly = (
                    (float(x), float(y)),
                    (float(x + w), float(y)),
                    (float(x + w), float(y + h)),
                    (float(x), float(y + h)),
                )
                lines.append((poly, text, 1.0))
        return lines

    def _generate(self, images: list[Any]) -> list[str]:
        if self._processor is None or self._model is None:
            return []
        pixels = self._processor(images=images, return_tensors="pt").pixel_values
        pixels = pixels.to(self._resolved_device())
        max_new_tokens = cast(int, self._config["max_new_tokens"])
        timeout_seconds = cast(float, self._config["timeout_seconds"])
        generated = self._model.generate(
            pixels,
            max_new_tokens=max_new_tokens,
            max_time=float(timeout_seconds),
        )
        return [
            str(text)
            for text in self._processor.batch_decode(
                generated, skip_special_tokens=True
            )
        ]

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

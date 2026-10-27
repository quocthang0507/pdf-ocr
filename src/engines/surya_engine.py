"""Lazy Surya adapter for multilingual detection and recognition."""

import importlib.util
import inspect
import os
import shutil
from collections.abc import Iterable, Mapping, Sequence
from html.parser import HTMLParser
from importlib import import_module
from typing import Any, cast

from src.core.exceptions import OCREngineError
from src.core.models import OCRPage
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.easyocr_engine import _languages
from src.engines.engine_registry import register_engine
from src.engines.result_builder import LineResult, as_pil_image, build_page
from src.services.weights_manager import ModelWeightsManager


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    @property
    def text(self) -> str:
        return " ".join(self.parts)


def _require_inference_server() -> None:
    """Surya 0.2x runs its models through llama.cpp or vLLM, not PyTorch.

    Without either, every page failed later with a bare "cannot recognise"
    error; explain the fix up front instead.
    """
    if os.environ.get("LLAMA_CPP_BINARY") or shutil.which("llama-server"):
        return
    if importlib.util.find_spec("vllm") is not None:
        return
    raise OCREngineError(
        "Phiên bản Surya OCR đang cài cần máy chủ suy luận llama.cpp "
        "(macOS: brew install llama.cpp) hoặc vLLM. Hoặc cài bản chạy trực "
        'tiếp bằng PyTorch: pip install "surya-ocr<0.11".'
    )


@register_engine(
    "surya",
    "Surya OCR",
    "Nhận diện đa ngôn ngữ với tọa độ theo dòng.",
)
class SuryaOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "langs": ConfigField(("vi", "en"), _languages),
        "device": ConfigField(
            "cpu",
            lambda value: isinstance(value, str)
            and (value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")),
        ),
    }

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._recognition_predictor: Any | None = None
        self._detection_predictor: Any | None = None
        self._inference_manager: Any | None = None
        self._uses_current_api = False
        super().__init__(weights_manager, config)

    @staticmethod
    def _apply_transformers_compatibility() -> None:
        try:
            config_module = import_module("surya.recognition.model.config")
            config_cls = getattr(config_module, "SuryaOCRConfig", None)
            if config_cls is not None:
                config_cls.has_no_defaults_at_init = True
                config_cls.get_text_config = lambda self, *args, **kwargs: self.decoder
        except Exception:  # nosec B110
            pass

    def _load_model(self) -> None:
        os.environ["MODEL_CACHE_DIR"] = str(self.weights_dir)
        os.environ["TORCH_DEVICE"] = self._resolved_device()
        self._apply_transformers_compatibility()
        recognition = import_module("surya.recognition")
        parameters = inspect.signature(recognition.RecognitionPredictor).parameters
        self._uses_current_api = "manager" in parameters
        if self._uses_current_api:
            _require_inference_server()
            inference = import_module("surya.inference")
            self._inference_manager = inference.SuryaInferenceManager()
            self._recognition_predictor = recognition.RecognitionPredictor(
                self._inference_manager
            )
            return
        detection = import_module("surya.detection")
        self._recognition_predictor = recognition.RecognitionPredictor()
        self._detection_predictor = detection.DetectionPredictor()

    def _resolved_device(self) -> str:
        device = str(self._config["device"])
        return "cpu" if device == "auto" else device

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        if self._recognition_predictor is None or (
            not self._uses_current_api and self._detection_predictor is None
        ):
            raise RuntimeError("Surya predictors are unavailable.")
        langs = cast(Sequence[str], self._config["langs"])
        backend_image = as_pil_image(image)
        if self._uses_current_api:
            predictions = self._recognition_predictor([backend_image])
        else:
            predictions = self._recognition_predictor(
                [backend_image], [list(langs)], self._detection_predictor
            )
        if not predictions:
            return build_page(image, page_number, ())
        lines: list[LineResult] = []
        results = getattr(predictions[0], "text_lines", None)
        results = getattr(predictions[0], "blocks", ()) if results is None else results
        results = cast(Iterable[Any], results)
        for line in results:
            geometry = getattr(line, "polygon", None) or getattr(line, "bbox", None)
            if geometry is None:
                continue
            text = getattr(line, "text", None)
            if text is None:
                text = self._html_text(str(getattr(line, "html", "")))
            lines.append(
                (
                    geometry,
                    str(text),
                    float(getattr(line, "confidence", 0.0)),
                )
            )
        return build_page(image, page_number, lines)

    @staticmethod
    def _html_text(value: str) -> str:
        parser = _TextParser()
        parser.feed(value)
        return parser.text

    def _unload_model(self) -> None:
        if self._inference_manager is not None:
            self._inference_manager.stop()
        self._recognition_predictor = None
        self._detection_predictor = None
        self._inference_manager = None

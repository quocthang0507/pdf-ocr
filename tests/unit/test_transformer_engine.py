"""TrOCR uses a managed Hugging Face cache and bounded generation."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.core.exceptions import OCREngineError
from src.engines.transformer_engine import TransformerOCREngine
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


def test_transformer_recognizes_handwriting_with_local_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    class Tensor:
        def to(self, device: str) -> "Tensor":
            calls["tensor_device"] = device
            return self

    class Processor:
        @classmethod
        def from_pretrained(cls, checkpoint: str, **kwargs: object) -> "Processor":
            calls["processor"] = (checkpoint, kwargs)
            return cls()

        def __call__(self, images: object, return_tensors: str) -> object:
            return SimpleNamespace(pixel_values=Tensor())

        def batch_decode(self, ids: object, skip_special_tokens: bool) -> list[str]:
            return ["handwritten note"]

    class Model:
        @classmethod
        def from_pretrained(cls, checkpoint: str, **kwargs: object) -> "Model":
            calls["model"] = (checkpoint, kwargs)
            return cls()

        def to(self, device: str) -> "Model":
            calls["model_device"] = device
            return self

        def eval(self) -> None:
            calls["eval"] = True

        def generate(self, values: object, **kwargs: object) -> list[list[int]]:
            calls["generate"] = kwargs
            return [[1, 2]]

    module = SimpleNamespace(TrOCRProcessor=Processor, VisionEncoderDecoderModel=Model)
    monkeypatch.setattr(
        "src.engines.transformer_engine.import_module", lambda name: module
    )
    engine = TransformerOCREngine(
        weights_manager=ModelWeightsManager(tmp_path),
        config={
            "checkpoint": "microsoft/trocr-base-handwritten",
            "device": "auto",
            "timeout_seconds": 7.5,
            "allow_download": False,
        },
    )
    engine.load_model()
    page = engine.recognize(np.zeros((18, 70, 3), dtype=np.uint8))

    assert page.blocks[0].text == "handwritten note"
    checkpoint, load_options = calls["model"]
    assert checkpoint == "microsoft/trocr-base-handwritten"
    assert load_options == {
        "cache_dir": str(tmp_path / "trocr"),
        "local_files_only": True,
    }
    assert calls["model_device"] == "cpu"
    assert calls["tensor_device"] == "cpu"
    assert calls["generate"] == {"max_new_tokens": 128, "max_time": 7.5}


def test_transformer_wraps_inference_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class Processor:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> "Processor":
            return cls()

        def __call__(self, **kwargs: object) -> object:
            return SimpleNamespace(
                pixel_values=SimpleNamespace(to=lambda device: object())
            )

    class Model:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> "Model":
            return cls()

        def to(self, device: str) -> "Model":
            return self

        def eval(self) -> None:
            pass

        def generate(self, *args: object, **kwargs: object) -> object:
            raise TimeoutError("private timeout")

    monkeypatch.setattr(
        "src.engines.transformer_engine.import_module",
        lambda name: SimpleNamespace(
            TrOCRProcessor=Processor, VisionEncoderDecoderModel=Model
        ),
    )
    engine = TransformerOCREngine(config={"device": "cpu", "allow_download": True})
    engine.load_model()
    with pytest.raises(OCREngineError, match="TrOCR") as caught:
        engine.recognize(np.zeros((5, 5), dtype=np.uint8))
    assert "private timeout" not in str(caught.value)

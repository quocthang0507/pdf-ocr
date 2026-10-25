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


def test_long_lines_are_split_between_words_not_inside_them() -> None:
    """TrOCR squeezes crops into a square; long lines are read in pieces."""
    from PIL import Image

    from src.engines.transformer_engine import MAX_LINE_ASPECT, split_wide_line

    height, canvas = 20, np.full((20, 900), 255, dtype=np.uint8)
    word_gaps: list[range] = []
    x = 5
    while x < 860:
        for _letter in range(5):  # letters 8 px wide, 2 px apart
            canvas[4:16, x : x + 8] = 0
            x += 10
        word_gaps.append(range(x - 2, x + 14))
        x += 14
    crop = Image.fromarray(canvas).convert("RGB")

    pieces = split_wide_line(crop)

    assert len(pieces) >= 900 // int(height * MAX_LINE_ASPECT)
    assert sum(piece.size[0] for piece in pieces) == 900
    edge = 0
    for piece in pieces[:-1]:
        edge += piece.size[0]
        assert any(edge in gap for gap in word_gaps), edge


def test_short_lines_are_left_whole() -> None:
    from PIL import Image

    from src.engines.transformer_engine import split_wide_line

    crop = Image.new("RGB", (120, 20), "white")

    assert split_wide_line(crop) == [crop]


def test_pieces_of_a_long_line_are_joined_back_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cv2

    batches: list[int] = []

    class Processor:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> "Processor":
            return cls()

        def __call__(self, images: list[object], return_tensors: str) -> object:
            batches.append(len(images))
            return SimpleNamespace(pixel_values=SimpleNamespace(to=lambda _d: None))

        def batch_decode(self, ids: list[int], skip_special_tokens: bool) -> list[str]:
            return [f"p{index}" for index in ids]

    class Model:
        @classmethod
        def from_pretrained(cls, *args: object, **kwargs: object) -> "Model":
            return cls()

        def to(self, device: str) -> "Model":
            return self

        def eval(self) -> None:
            pass

        def generate(self, values: object, **kwargs: object) -> list[int]:
            return list(range(batches[-1]))

    monkeypatch.setattr(
        "src.engines.transformer_engine.import_module",
        lambda name: SimpleNamespace(
            TrOCRProcessor=Processor, VisionEncoderDecoderModel=Model
        ),
    )
    image = np.full((200, 1500, 3), 255, dtype=np.uint8)
    for baseline in (70, 150):
        cv2.putText(
            image,
            "word " * 22,
            (10, baseline),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 0, 0),
            2,
        )
    engine = TransformerOCREngine(
        weights_manager=ModelWeightsManager(tmp_path), config={"device": "cpu"}
    )
    engine.load_model()

    page = engine.recognize(image)

    texts = [block.text for block in page.blocks]
    assert len(texts) == 2
    assert batches[-1] > 2  # the two lines went in as several pieces
    first_line = texts[0].split()
    assert first_line == sorted(first_line, key=lambda token: int(token[1:]))

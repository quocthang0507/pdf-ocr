"""VietOCR stays lazy and preserves complex Vietnamese Unicode output."""

from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from src.engines.vietocr_engine import VietOCREngine, _segment_lines
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


def test_vietocr_recognizes_vietnamese_and_uses_managed_weights(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    class FakeConfig:
        @staticmethod
        def load_config_from_name(name: str) -> dict[str, object]:
            seen["architecture"] = name
            return {"cnn": {"pretrained": True}}

    class FakePredictor:
        def __init__(self, config: dict[str, object]) -> None:
            seen["config"] = config

        def predict(self, image: object, return_prob: bool = False) -> object:
            assert return_prob
            assert getattr(image, "size", None) == (80, 20)
            assert not isinstance(image, np.ndarray)
            return "Cộng hòa Xã hội chủ nghĩa Việt Nam", 0.99

    modules = {
        "vietocr.tool.config": SimpleNamespace(Cfg=FakeConfig),
        "vietocr.tool.predictor": SimpleNamespace(Predictor=FakePredictor),
    }
    monkeypatch.setattr(
        "src.engines.vietocr_engine.import_module", lambda name: modules[name]
    )
    manager = ModelWeightsManager(tmp_path)
    engine = VietOCREngine(
        weights_manager=manager,
        config={"architecture": "vgg_seq2seq", "device": "auto"},
    )

    assert not engine.is_loaded
    engine.load_model()
    page = engine.recognize(np.zeros((20, 80, 3), dtype=np.uint8), page_number=2)

    assert page.page_number == 2
    assert page.blocks[0].text == "Cộng hòa Xã hội chủ nghĩa Việt Nam"
    assert page.blocks[0].lines[0].words[0].confidence == 0.99
    config = seen["config"]
    assert isinstance(config, dict)
    assert config["weights"] == str(tmp_path / "vietocr" / "vgg_seq2seq.pth")
    assert config["cnn"] == {"pretrained": False}
    assert config["device"] == "cpu"
    engine.unload_model()
    assert not engine.is_loaded


def test_segment_lines_filters_grid_and_orders_text() -> None:
    img = np.full((120, 200, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Line One", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.line(img, (5, 55), (195, 55), (0, 0, 0), 2)
    cv2.putText(img, "Line Two", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    boxes = _segment_lines(img)
    assert len(boxes) == 2
    # Verify reading order top-to-bottom
    assert boxes[0][1] < boxes[1][1]


def test_vietocr_multi_line_page_recognition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeConfig:
        @staticmethod
        def load_config_from_name(name: str) -> dict[str, object]:
            return {"cnn": {}}

    class FakeBatchPredictor:
        def __init__(self, config: dict[str, object]) -> None:
            pass

        def predict_batch(
            self, images: list[object], return_prob: bool = False
        ) -> tuple[list[str], list[float]]:
            assert return_prob
            return [f"Dòng {i + 1}" for i in range(len(images))], [0.95] * len(images)

    modules = {
        "vietocr.tool.config": SimpleNamespace(Cfg=FakeConfig),
        "vietocr.tool.predictor": SimpleNamespace(Predictor=FakeBatchPredictor),
    }
    monkeypatch.setattr(
        "src.engines.vietocr_engine.import_module", lambda name: modules[name]
    )

    img = np.full((120, 200, 3), 255, dtype=np.uint8)
    cv2.putText(img, "Line One", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.line(img, (5, 55), (195, 55), (0, 0, 0), 2)
    cv2.putText(img, "Line Two", (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    manager = ModelWeightsManager(tmp_path)
    engine = VietOCREngine(weights_manager=manager)
    engine.load_model()
    page = engine.recognize(img, page_number=1)

    assert page.page_number == 1
    assert len(page.blocks) == 2
    assert page.blocks[0].text == "Dòng 1"
    assert page.blocks[1].text == "Dòng 2"


@pytest.mark.parametrize("architecture", ["unknown", "", 42])
def test_vietocr_rejects_unknown_architecture(architecture: object) -> None:
    with pytest.raises(Exception, match="architecture"):
        VietOCREngine(config={"architecture": architecture})

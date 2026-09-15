"""VietOCR stays lazy and preserves complex Vietnamese Unicode output."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.engines.vietocr_engine import VietOCREngine
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


@pytest.mark.parametrize("architecture", ["unknown", "", 42])
def test_vietocr_rejects_unknown_architecture(architecture: object) -> None:
    with pytest.raises(Exception, match="architecture"):
        VietOCREngine(config={"architecture": architecture})

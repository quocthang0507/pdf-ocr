"""Surya adapter handles multilingual line results without eager imports."""

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.core.exceptions import OCREngineError
from src.engines.surya_engine import SuryaOCREngine
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


def test_surya_returns_multilingual_lines_and_coordinates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    class FakeDetectionPredictor:
        pass

    class FakeRecognitionPredictor:
        def __call__(self, images: object, langs: object, detector: object) -> object:
            calls["langs"] = langs
            return [
                SimpleNamespace(
                    text_lines=[
                        SimpleNamespace(
                            text="Tiếng Việt", confidence=0.97, bbox=[2, 3, 42, 13]
                        ),
                        SimpleNamespace(
                            text="English", confidence=0.95, bbox=[2, 16, 38, 26]
                        ),
                    ]
                )
            ]

    modules = {
        "surya.detection": SimpleNamespace(DetectionPredictor=FakeDetectionPredictor),
        "surya.recognition": SimpleNamespace(
            RecognitionPredictor=FakeRecognitionPredictor
        ),
    }
    monkeypatch.setattr(
        "src.engines.surya_engine.import_module", lambda name: modules[name]
    )
    engine = SuryaOCREngine(
        weights_manager=ModelWeightsManager(tmp_path),
        config={"langs": ["vi", "en"]},
    )
    engine.load_model()
    page = engine.recognize(np.zeros((30, 60, 3), dtype=np.uint8))

    assert [block.text for block in page.blocks] == ["Tiếng Việt", "English"]
    assert page.blocks[1].bbox.x2 == 38
    assert calls["langs"] == [["vi", "en"]]
    assert engine.weights_dir == tmp_path / "surya"


def test_surya_supports_current_manager_api_and_releases_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setenv("LLAMA_CPP_BINARY", "/opt/llama.cpp/llama-server")

    class FakeManager:
        def stop(self) -> None:
            calls["stopped"] = True

    class CurrentRecognitionPredictor:
        def __init__(self, manager: object | None = None) -> None:
            calls["manager"] = manager

        def __call__(self, images: object) -> object:
            image = images[0]
            calls["image_size"] = image.size
            return [
                SimpleNamespace(
                    blocks=[
                        SimpleNamespace(
                            html="<p>Xin <strong>chào</strong></p>",
                            confidence=0.93,
                            polygon=[[4, 5], [44, 5], [44, 17], [4, 17]],
                        )
                    ]
                )
            ]

    modules = {
        "surya.inference": SimpleNamespace(SuryaInferenceManager=FakeManager),
        "surya.recognition": SimpleNamespace(
            RecognitionPredictor=CurrentRecognitionPredictor
        ),
    }
    monkeypatch.setattr(
        "src.engines.surya_engine.import_module", lambda name: modules[name]
    )
    engine = SuryaOCREngine(
        weights_manager=ModelWeightsManager(tmp_path),
        config={"device": "cpu", "langs": ["vi"]},
    )

    engine.load_model()
    page = engine.recognize(np.zeros((25, 50, 3), dtype=np.uint8))
    engine.unload_model()

    assert page.blocks[0].text == "Xin chào"
    assert page.blocks[0].bbox.polygon[0] == (4, 5)
    assert calls["image_size"] == (50, 25)
    assert calls["stopped"] is True
    assert os.environ["MODEL_CACHE_DIR"] == str(tmp_path / "surya")
    assert os.environ["TORCH_DEVICE"] == "cpu"


@pytest.mark.parametrize("langs", [[], [""], "vi", [1]])
def test_surya_validates_language_list(langs: object) -> None:
    with pytest.raises(Exception, match="langs"):
        SuryaOCREngine(config={"langs": langs})


def test_surya_explains_a_missing_inference_server_at_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recent Surya runs through llama.cpp/vLLM; say so instead of failing later."""
    from src.engines import surya_engine

    class CurrentRecognitionPredictor:
        def __init__(self, manager: object | None = None) -> None:
            pass

    monkeypatch.delenv("LLAMA_CPP_BINARY", raising=False)
    monkeypatch.setattr(surya_engine.shutil, "which", lambda _name: None)
    monkeypatch.setattr(surya_engine.importlib.util, "find_spec", lambda _name: None)
    monkeypatch.setattr(
        surya_engine,
        "import_module",
        lambda name: SimpleNamespace(RecognitionPredictor=CurrentRecognitionPredictor),
    )
    engine = SuryaOCREngine(weights_manager=ModelWeightsManager(tmp_path))

    with pytest.raises(OCREngineError, match="llama.cpp"):
        engine.load_model()

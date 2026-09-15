"""EasyOCR fallback emits the shared immutable OCRPage contract."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.engines.easyocr_engine import EasyOCREngine
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


def test_easyocr_returns_standard_page_and_managed_model_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    class Reader:
        def __init__(self, langs: list[str], **kwargs: object) -> None:
            calls["init"] = (langs, kwargs)

        def readtext(self, image: object, **kwargs: object) -> object:
            calls["read"] = kwargs
            return [([[1, 1], [41, 1], [41, 12], [1, 12]], "Dự phòng", 0.91)]

    monkeypatch.setattr(
        "src.engines.easyocr_engine.import_module",
        lambda name: SimpleNamespace(Reader=Reader),
    )
    engine = EasyOCREngine(
        weights_manager=ModelWeightsManager(tmp_path),
        config={"langs": ["vi", "en"], "device": "cpu", "beam_width": 3},
    )
    engine.load_model()
    page = engine.recognize(np.zeros((20, 50, 3), dtype=np.uint8), page_number=3)

    assert page.page_number == 3
    assert page.blocks[0].text == "Dự phòng"
    langs, options = calls["init"]
    assert langs == ["vi", "en"]
    assert options["gpu"] is False
    assert options["model_storage_directory"] == str(tmp_path / "easyocr")
    assert calls["read"] == {"detail": 1, "paragraph": False, "beamWidth": 3}

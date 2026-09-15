"""PaddleOCR results include line geometry, confidence, and table matrices."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.core.exceptions import OCREngineError
from src.engines.paddle_engine import PaddleOCREngine
from src.services.weights_manager import ModelWeightsManager

pytestmark = pytest.mark.unit


def test_paddle_converts_text_and_table_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, object] = {}

    class FakeOCR:
        def __init__(self, **kwargs: object) -> None:
            calls["ocr_kwargs"] = kwargs

        def ocr(self, image: object, cls: bool = True) -> object:
            assert cls
            return [[[[[1, 2], [31, 2], [31, 12], [1, 12]], ("Xin chào", 0.96)]]]

    class FakeStructure:
        def __init__(self, **kwargs: object) -> None:
            calls["table_kwargs"] = kwargs

        def __call__(self, image: object) -> object:
            return [
                {
                    "type": "table",
                    "bbox": [0, 14, 60, 40],
                    "res": {
                        "cells": [
                            {"row": 0, "col": 0, "text": "Tên"},
                            {"row": 0, "col": 1, "text": "Giá"},
                            {"row": 1, "col": 0, "text": "Sách"},
                            {"row": 1, "col": 1, "text": "50.000"},
                        ]
                    },
                }
            ]

    module = SimpleNamespace(PaddleOCR=FakeOCR, PPStructure=FakeStructure)
    monkeypatch.setattr("src.engines.paddle_engine.import_module", lambda name: module)
    engine = PaddleOCREngine(
        weights_manager=ModelWeightsManager(tmp_path),
        config={"device": "cpu", "use_tables": True, "det_db_thresh": 0.4},
    )
    engine.load_model()
    page = engine.recognize(np.zeros((50, 100, 3), dtype=np.uint8))

    word = page.blocks[0].lines[0].words[0]
    assert word.text == "Xin chào"
    assert word.confidence == 0.96
    assert word.bbox.polygon[0] == (1, 2)
    assert page.tables[0].rows == (("Tên", "Giá"), ("Sách", "50.000"))
    assert calls["ocr_kwargs"] == {
        "lang": "vi",
        "use_angle_cls": True,
        "det_db_thresh": 0.4,
        "use_gpu": False,
    }


def test_paddle_wraps_missing_weights_with_provider_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingWeights:
        def __init__(self, **kwargs: object) -> None:
            raise FileNotFoundError("private model path")

    monkeypatch.setattr(
        "src.engines.paddle_engine.import_module",
        lambda name: SimpleNamespace(PaddleOCR=MissingWeights),
    )
    with pytest.raises(OCREngineError, match="PaddleOCR") as caught:
        PaddleOCREngine().load_model()
    assert "private model path" not in str(caught.value)


def test_paddle_converts_current_api_numpy_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CurrentOCR:
        def __init__(
            self,
            lang: str,
            use_doc_orientation_classify: bool,
            use_textline_orientation: bool,
            text_det_thresh: float,
            **kwargs: object,
        ) -> None:
            assert kwargs == {"device": "cpu"}

        def predict(self, image: object) -> object:
            return [
                SimpleNamespace(
                    json={
                        "res": {
                            "rec_polys": np.array(
                                [[[2, 3], [32, 3], [32, 14], [2, 14]]]
                            ),
                            "rec_texts": ["Hiện đại"],
                            "rec_scores": np.array([0.94]),
                        }
                    }
                )
            ]

    class CurrentStructure:
        def __init__(self, device: str) -> None:
            assert device == "cpu"

        def predict(self, image: object) -> object:
            return [
                SimpleNamespace(
                    json={
                        "res": {
                            "table_res_list": [
                                {
                                    "bbox": [0, 16, 50, 35],
                                    "pred_html": (
                                        "<table><tr><th>A</th><th>B</th></tr>"
                                        "<tr><td>1</td><td>2</td></tr></table>"
                                    ),
                                }
                            ]
                        }
                    }
                )
            ]

    module = SimpleNamespace(PaddleOCR=CurrentOCR, PPStructureV3=CurrentStructure)
    monkeypatch.setattr("src.engines.paddle_engine.import_module", lambda name: module)
    engine = PaddleOCREngine(weights_manager=ModelWeightsManager(tmp_path))

    engine.load_model()
    page = engine.recognize(np.zeros((40, 60, 3), dtype=np.uint8))

    assert page.blocks[0].text == "Hiện đại"
    assert page.tables[0].rows == (("A", "B"), ("1", "2"))

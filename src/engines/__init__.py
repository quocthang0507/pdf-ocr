"""Built-in OCR providers, registered without importing heavy AI libraries."""

from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.chandra_engine import ChandraOCREngine
from src.engines.dots_ocr_engine import DotsOCREngine
from src.engines.easyocr_engine import EasyOCREngine
from src.engines.engine_registry import (
    EngineMetadata,
    EngineRegistry,
    engine_session,
    register_engine,
)
from src.engines.paddle_engine import PaddleOCREngine
from src.engines.surya_engine import SuryaOCREngine
from src.engines.transformer_engine import TransformerOCREngine
from src.engines.vietocr_engine import VietOCREngine

__all__ = [
    "BaseOCREngine",
    "ChandraOCREngine",
    "ConfigField",
    "DotsOCREngine",
    "EasyOCREngine",
    "EngineMetadata",
    "EngineRegistry",
    "PaddleOCREngine",
    "SuryaOCREngine",
    "TransformerOCREngine",
    "VietOCREngine",
    "engine_session",
    "register_engine",
]

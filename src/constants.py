"""Framework-independent vocabulary shared by OCR providers and exporters."""

from enum import Enum

LOW_CONFIDENCE_THRESHOLD = 0.8


class BlockType(str, Enum):
    TEXT = "text"
    TITLE = "title"
    TABLE = "table"
    IMAGE = "image"


class PageType(str, Enum):
    TEXT_BASED = "text_based"
    SCANNED = "scanned"
    HYBRID = "hybrid"

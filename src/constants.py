"""Framework-independent vocabulary shared by OCR providers and exporters."""

from enum import Enum

LOW_CONFIDENCE_THRESHOLD = 0.8


class BlockType(str, Enum):
    TEXT = "text"
    TITLE = "title"
    HEADING_1 = "heading_1"
    HEADING_2 = "heading_2"
    HEADING_3 = "heading_3"
    CAPTION = "caption"
    TABLE = "table"
    IMAGE = "image"


class PageType(str, Enum):
    TEXT_BASED = "text_based"
    SCANNED = "scanned"
    HYBRID = "hybrid"


#: Outline colour per layout block type, readable on light and dark pages.
BLOCK_TYPE_COLORS: dict[BlockType, str] = {
    BlockType.TEXT: "#2563eb",
    BlockType.TITLE: "#d946ef",
    BlockType.HEADING_1: "#c026d3",
    BlockType.HEADING_2: "#a21caf",
    BlockType.HEADING_3: "#86198f",
    BlockType.CAPTION: "#64748b",
    BlockType.TABLE: "#059669",
    BlockType.IMAGE: "#ea580c",
}

#: Background used to flag words the OCR engine was unsure about.
LOW_CONFIDENCE_COLOR = "#fde68a"

#: Outline colour of the block or region the user is currently working on.
SELECTION_COLOR = "#dc2626"

#: Tool bar icon tint per theme. The platform draws icons dark, which reads
#: well on a light bar, so only the dark theme needs recolouring.
ICON_COLORS: dict[str, str | None] = {"light": None, "dark": "#e6ebf2"}

#: Interface languages, keyed by code; Vietnamese is the source language.
DEFAULT_LANGUAGE = "vi"
LANGUAGE_NAMES: dict[str, str] = {
    "vi": "Tiếng Việt",
    "en": "English",
}

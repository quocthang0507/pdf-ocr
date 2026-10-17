"""Lazy dots.ocr VLM adapter supporting HuggingFace and vLLM backends."""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.request
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np

from src.constants import BlockType
from src.core.exceptions import OCREngineError
from src.core.models import BoundingBox, OCRBlock, OCRPage, OCRTable
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.chandra_engine import (
    _ChandraHTMLParser,
    _text_to_lines,
    parse_chandra_output,
)
from src.engines.engine_registry import register_engine
from src.services.weights_manager import ModelWeightsManager
from src.utils.image_utils import ndarray_to_pil

DEFAULT_DOTS_CHECKPOINT = "rednote-hilab/dots.ocr"
DEFAULT_VLLM_URL = "http://localhost:8000/v1"

DOTS_LAYOUT_PROMPT = (
    "Please output the layout information from the PDF image, including each "
    "layout element's bbox, its category, and the corresponding text content "
    "within the bbox.\n\n"
    "1. Bbox format: [x1, y1, x2, y2]\n\n"
    "2. Layout Categories: The possible categories are ['Caption', 'Footnote', "
    "'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', "
    "'Section-header', 'Table', 'Text', 'Title'].\n\n"
    "3. Text Extraction & Formatting Rules:\n"
    "    - Picture: For the 'Picture' category, the text field should be omitted.\n"
    "    - Formula: Format its text as LaTeX.\n"
    "    - Table: Format its text as HTML.\n"
    "    - All Others (Text, Title, etc.): Format their text as Markdown.\n\n"
    "4. Constraints:\n"
    "    - The output text must be the original text from the image, with no "
    "translation.\n"
    "    - All layout elements must be sorted according to human reading order.\n\n"
    "5. Final Output: The entire output must be a single JSON object."
)

DOTS_OCR_ONLY_PROMPT = (
    "Extract the text content from this image in reading order. "
    "Format tables as HTML and formulas as LaTeX."
)

_CATEGORY_TO_BLOCK_TYPE: dict[str, BlockType] = {
    "title": BlockType.TITLE,
    "section-header": BlockType.HEADING_1,
    "text": BlockType.TEXT,
    "table": BlockType.TABLE,
    "formula": BlockType.TEXT,
    "list-item": BlockType.TEXT,
    "caption": BlockType.CAPTION,
    "footnote": BlockType.CAPTION,
    "page-header": BlockType.CAPTION,
    "page-footer": BlockType.CAPTION,
    "picture": BlockType.IMAGE,
}


def _valid_device(value: object) -> bool:
    return isinstance(value, str) and (
        value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")
    )


def _valid_method(value: object) -> bool:
    return isinstance(value, str) and value in {"hf", "vllm"}


def _valid_prompt_mode(value: object) -> bool:
    return isinstance(value, str) and value in {"", "layout_all", "ocr"}


def _valid_checkpoint(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and ".." not in value


def parse_dots_output(
    raw_output: str, width: int, height: int, page_number: int
) -> OCRPage:
    """Parse dots.ocr JSON layout array (or Markdown/HTML fallback) into OCRPage."""
    cleaned = _strip_code_fence(raw_output.strip())
    if not cleaned:
        return OCRPage(page_number=page_number, width=width, height=height)
    items = _try_parse_json_items(cleaned)
    if items is None:
        return parse_chandra_output(cleaned, width, height, page_number)
    blocks: list[OCRBlock] = []
    tables: list[OCRTable] = []
    for order, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        category = str(item.get("category", "Text")).strip().lower()
        text = str(item.get("text", "") or "").strip()
        if category == "picture" or not text:
            continue
        bbox = _item_bbox(item.get("bbox"), width, height)
        btype = _CATEGORY_TO_BLOCK_TYPE.get(category, BlockType.TEXT)
        if btype == BlockType.TABLE and "<table" in text.lower():
            parsed_table, plain = _extract_html_table(text, bbox, width, height)
            if parsed_table is not None:
                tables.append(parsed_table)
                text = plain
        lines = _text_to_lines(text, bbox)
        if lines:
            blocks.append(
                OCRBlock(
                    lines=lines,
                    bbox=bbox,
                    block_type=btype,
                    reading_order=order,
                )
            )
    return OCRPage(
        page_number=page_number,
        width=width,
        height=height,
        blocks=tuple(blocks),
        tables=tuple(tables),
    )


def _strip_code_fence(text: str) -> str:
    match = re.match(r"^```(?:json|html|markdown)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1).strip() if match else text


def _try_parse_json_items(text: str) -> list[Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, Mapping):
        for key in ("layout", "elements", "items", "blocks"):
            if isinstance(parsed.get(key), list):
                return list(parsed[key])
        if "bbox" in parsed or "category" in parsed:
            return [parsed]
    return None


def _item_bbox(raw_bbox: object, width: int, height: int) -> BoundingBox:
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            x1, y1, x2, y2 = (float(v) for v in raw_bbox)
            x1, x2 = max(0.0, min(x1, float(width))), max(0.0, min(x2, float(width)))
            y1, y2 = max(0.0, min(y1, float(height))), max(0.0, min(y2, float(height)))
            if x2 > x1 and y2 > y1:
                return BoundingBox(x1, y1, x2, y2)
        except (TypeError, ValueError):
            pass
    return BoundingBox(0.0, 0.0, float(width), float(height))


def _extract_html_table(
    html_text: str, bbox: BoundingBox, width: int, height: int
) -> tuple[OCRTable | None, str]:
    parser = _ChandraHTMLParser(width, height)
    parser._div_bbox = bbox
    parser.feed(html_text)
    if not parser.tables:
        return None, re.sub(r"<[^>]+>", " ", html_text).strip()
    table = parser.tables[0]
    row_text = "\n".join(" | ".join(r) for r in table.rows)
    return table, row_text


@register_engine(
    "dots_ocr",
    "dots.ocr",
    "Mô hình VLM 1.7B đa ngôn ngữ phân tích bố cục, bảng biểu và công thức toán.",
    supports_handwriting=True,
    supports_tables=True,
)
class DotsOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "checkpoint": ConfigField(DEFAULT_DOTS_CHECKPOINT, _valid_checkpoint),
        "method": ConfigField("hf", _valid_method),
        "prompt_mode": ConfigField("layout_all", _valid_prompt_mode),
        "api_base": ConfigField(
            DEFAULT_VLLM_URL, lambda v: isinstance(v, str) and bool(v.strip())
        ),
        "max_new_tokens": ConfigField(
            4096, lambda v: type(v) is int and 64 <= v <= 24000
        ),
        "device": ConfigField("cpu", _valid_device),
        "use_tables": ConfigField(True, lambda v: type(v) is bool),
    }

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._processor: Any | None = None
        self._model: Any | None = None
        self._backend: str = ""
        super().__init__(weights_manager, config)

    def _resolve_checkpoint(self) -> tuple[str, bool]:
        checkpoint = str(self._config["checkpoint"])
        candidate = Path(checkpoint)
        if candidate.is_dir():
            return str(candidate.resolve()), True
        if self.weights_dir is not None:
            in_weights = self.weights_dir / checkpoint
            if in_weights.is_dir():
                return str(in_weights.resolve()), True
            if (self.weights_dir / "config.json").is_file():
                return str(self.weights_dir.resolve()), True
        return checkpoint, False

    def _load_model(self) -> None:
        method = str(self._config["method"])
        if method == "vllm":
            self._backend = "vllm"
            return
        transformers = import_module("transformers")
        torch = import_module("torch")
        checkpoint, is_local = self._resolve_checkpoint()
        kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            **({"local_files_only": True} if is_local else {}),
        }
        self._processor = transformers.AutoProcessor.from_pretrained(
            checkpoint, **kwargs
        )
        self._model = transformers.AutoModelForCausalLM.from_pretrained(
            checkpoint, **kwargs
        )
        target = str(self._config["device"])
        if target == "auto":
            target = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(target)
        self._model.eval()
        self._backend = "hf"

    def _unload_model(self) -> None:
        self._processor = None
        self._model = None
        self._backend = ""

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        arr = np.asarray(image)
        height, width = int(arr.shape[0]), int(arr.shape[1])
        pil_image = ndarray_to_pil(arr)
        if self._backend == "vllm":
            raw = self._infer_vllm(pil_image)
        else:
            raw = self._infer_hf(pil_image)
        page = parse_dots_output(raw, width, height, page_number)
        if not self._config.get("use_tables", True):
            return page.with_updates(tables=())
        return page

    def _active_prompt(self) -> str:
        mode = str(self._config.get("prompt_mode") or "layout_all")
        return DOTS_OCR_ONLY_PROMPT if mode == "ocr" else DOTS_LAYOUT_PROMPT

    def _infer_hf(self, pil_image: Any) -> str:
        if self._processor is None or self._model is None:
            raise OCREngineError("dots.ocr chưa được khởi tạo.")
        torch = import_module("torch")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_image},
                    {"type": "text", "text": self._active_prompt()},
                ],
            }
        ]
        inputs = self._processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )
        device = next(self._model.parameters()).device
        inputs = inputs.to(device)
        max_tokens = int(str(self._config["max_new_tokens"]))
        with torch.no_grad():
            outputs = self._model.generate(**inputs, max_new_tokens=max_tokens)
        prompt_len = inputs["input_ids"].shape[-1]
        return str(
            self._processor.decode(outputs[0][prompt_len:], skip_special_tokens=True)
        )

    def _infer_vllm(self, pil_image: Any) -> str:
        buf = io.BytesIO()
        pil_image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        url = str(self._config["api_base"]).rstrip("/") + "/chat/completions"
        payload = json.dumps(
            {
                "model": str(self._config["checkpoint"]),
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            },
                            {"type": "text", "text": self._active_prompt()},
                        ],
                    }
                ],
                "max_tokens": int(str(self._config["max_new_tokens"])),
                "temperature": 0.1,
            }
        ).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])

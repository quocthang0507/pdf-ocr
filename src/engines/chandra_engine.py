"""Lazy Chandra OCR adapter supporting local HuggingFace and vLLM servers."""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.request
from collections.abc import Mapping
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path
from typing import Any

import numpy as np

from src.constants import BlockType
from src.core.exceptions import OCREngineError
from src.core.models import BoundingBox, OCRBlock, OCRLine, OCRPage, OCRTable, OCRWord
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import register_engine
from src.services.weights_manager import ModelWeightsManager
from src.utils.image_utils import ndarray_to_pil

DEFAULT_CHANDRA_CHECKPOINT = "datalab-to/chandra"
DEFAULT_VLLM_URL = "http://localhost:8000/v1"
_BBOX_SCALE = 1000.0

_CHANDRA_PROMPT = (
    "Extract all text and layout from this document page into HTML blocks with "
    "data-label and data-bbox attributes. Preserve tables as <table> and math "
    "as <math>."
)
_CHANDRA_OCR_ONLY_PROMPT = (
    "Extract all text from this document page into clean Markdown in reading order. "
    "Preserve tables and math formulas."
)

_LABEL_TO_BLOCK_TYPE: dict[str, BlockType] = {
    "title": BlockType.TITLE,
    "section-header": BlockType.HEADING_1,
    "heading": BlockType.HEADING_1,
    "h1": BlockType.HEADING_1,
    "h2": BlockType.HEADING_2,
    "h3": BlockType.HEADING_3,
    "table": BlockType.TABLE,
    "formula": BlockType.TEXT,
    "math": BlockType.TEXT,
    "equation": BlockType.TEXT,
    "list-item": BlockType.TEXT,
    "list": BlockType.TEXT,
    "caption": BlockType.CAPTION,
    "footnote": BlockType.CAPTION,
    "page-header": BlockType.CAPTION,
    "header": BlockType.CAPTION,
    "page-footer": BlockType.CAPTION,
    "footer": BlockType.CAPTION,
    "image": BlockType.IMAGE,
    "figure": BlockType.IMAGE,
    "picture": BlockType.IMAGE,
}


def _valid_device(value: object) -> bool:
    return isinstance(value, str) and (
        value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")
    )


def _valid_method(value: object) -> bool:
    return isinstance(value, str) and value in {"hf", "vllm"}


def _valid_prompt_type(value: object) -> bool:
    return isinstance(value, str) and value in {"", "ocr_layout", "ocr"}


def _valid_checkpoint(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and ".." not in value


class _ChandraHTMLParser(HTMLParser):
    """Parse Chandra structured HTML divs and tables into blocks and tables."""

    def __init__(self, width: int, height: int) -> None:
        super().__init__()
        self.width = width
        self.height = height
        self.blocks: list[tuple[BlockType, BoundingBox, str]] = []
        self.tables: list[OCRTable] = []
        self._in_div = False
        self._div_label = "text"
        self._div_bbox: BoundingBox | None = None
        self._div_text: list[str] = []
        self._in_table = False
        self._rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag == "div" and not self._in_div:
            self._in_div = True
            self._div_label = attr_map.get("data-label", "text").strip().lower()
            self._div_bbox = _parse_bbox_attr(
                attr_map.get("data-bbox", ""), self.width, self.height
            )
            self._div_text = []
        elif tag in {"h1", "h2", "h3"} and not self._in_div:
            self._in_div = True
            self._div_label = tag
            self._div_bbox = None
            self._div_text = []
        elif tag == "table":
            self._in_table = True
            self._rows = []
        elif tag == "tr" and self._in_table:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
        elif tag == "br" and self._in_div:
            self._div_text.append("\n")

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)
        elif self._in_div:
            self._div_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if (
            tag in {"td", "th"}
            and self._current_row is not None
            and self._current_cell is not None
        ):
            self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._in_table and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self._rows.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._in_table:
            self._in_table = False
            bbox = self._div_bbox or BoundingBox(0, 0, self.width, self.height)
            if self._rows:
                table = _rows_to_table(self._rows, bbox)
                self.tables.append(table)
                row_text = "\n".join(" | ".join(r) for r in table.rows)
                self.blocks.append((BlockType.TABLE, bbox, row_text))
            self._div_text = []
        elif tag in {"div", "h1", "h2", "h3"} and self._in_div:
            self._in_div = False
            text = "".join(self._div_text).strip()
            if text and self._div_label != "blank-page":
                btype = _LABEL_TO_BLOCK_TYPE.get(self._div_label, BlockType.TEXT)
                bbox = self._div_bbox or BoundingBox(0, 0, self.width, self.height)
                self.blocks.append((btype, bbox, text))
            self._div_bbox = None
            self._div_text = []


def _parse_bbox_attr(raw: str, width: int, height: int) -> BoundingBox | None:
    numbers = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", raw)]
    if len(numbers) != 4:
        return None
    x1, y1, x2, y2 = numbers
    if max(x1, y1, x2, y2) <= _BBOX_SCALE and (
        width > _BBOX_SCALE or height > _BBOX_SCALE
    ):
        x1, x2 = x1 * width / _BBOX_SCALE, x2 * width / _BBOX_SCALE
        y1, y2 = y1 * height / _BBOX_SCALE, y2 * height / _BBOX_SCALE
    x1, x2 = max(0.0, min(x1, float(width))), max(0.0, min(x2, float(width)))
    y1, y2 = max(0.0, min(y1, float(height))), max(0.0, min(y2, float(height)))
    if x2 <= x1 or y2 <= y1:
        return None
    return BoundingBox(x1, y1, x2, y2)


def _rows_to_table(rows: list[list[str]], bbox: BoundingBox) -> OCRTable:
    cols = max(len(r) for r in rows)
    padded = tuple(tuple(r + [""] * (cols - len(r))) for r in rows)
    return OCRTable(rows=padded, bbox=bbox)


def _parse_markdown_fallback(
    plain: str, width: int, height: int, parser: _ChandraHTMLParser
) -> None:
    chunks = [p.strip() for p in plain.split("\n\n") if p.strip()]
    for idx, para in enumerate(chunks):
        y1 = idx * (height / max(1, len(chunks)))
        y2 = min(float(height), y1 + 32.0)
        bbox = BoundingBox(0.0, y1, float(width), max(y1 + 1.0, y2))
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        if len(lines) >= 2 and all(
            ln.startswith("|") and ln.endswith("|") for ln in lines
        ):
            rows = [
                [c.strip() for c in ln.strip("|").split("|")]
                for ln in lines
                if not re.match(r"^[\|\s\-:]+$", ln)
            ]
            if rows:
                table = _rows_to_table(rows, bbox)
                parser.tables.append(table)
                parser.blocks.append(
                    (
                        BlockType.TABLE,
                        bbox,
                        "\n".join(" | ".join(r) for r in table.rows),
                    )
                )
                continue
        if para.startswith("# "):
            parser.blocks.append((BlockType.HEADING_1, bbox, para[2:].strip()))
        elif para.startswith("## "):
            parser.blocks.append((BlockType.HEADING_2, bbox, para[3:].strip()))
        else:
            parser.blocks.append((BlockType.TEXT, bbox, para))


def parse_chandra_output(
    raw_output: str, width: int, height: int, page_number: int
) -> OCRPage:
    """Convert Chandra HTML or Markdown output into a structured OCRPage."""
    cleaned = raw_output.strip()
    if not cleaned:
        return OCRPage(page_number=page_number, width=width, height=height)
    parser = _ChandraHTMLParser(width, height)
    if "<div" in cleaned or "<table" in cleaned or "<h1" in cleaned or "<p" in cleaned:
        parser.feed(cleaned)
    if not parser.blocks:
        plain = re.sub(r"<[^>]+>", "", cleaned).strip()
        _parse_markdown_fallback(plain, width, height, parser)
    ocr_blocks: list[OCRBlock] = []
    for order, (btype, bbox, text) in enumerate(parser.blocks):
        lines = _text_to_lines(text, bbox)
        if lines:
            ocr_blocks.append(
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
        blocks=tuple(ocr_blocks),
        tables=tuple(parser.tables),
    )


def _text_to_lines(text: str, bbox: BoundingBox) -> tuple[OCRLine, ...]:
    raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw_lines:
        return ()
    step = bbox.height / max(1, len(raw_lines))
    lines: list[OCRLine] = []
    for idx, line_text in enumerate(raw_lines):
        ly1 = bbox.y1 + idx * step
        ly2 = min(bbox.y2, ly1 + max(1.0, step))
        lbox = BoundingBox(bbox.x1, ly1, bbox.x2, max(ly1 + 1.0, ly2))
        words = _line_to_words(line_text, lbox)
        if words:
            lines.append(OCRLine(words=words, bbox=lbox))
    return tuple(lines)


def _line_to_words(line_text: str, line_box: BoundingBox) -> tuple[OCRWord, ...]:
    tokens = line_text.split()
    if not tokens:
        return ()
    step = line_box.width / max(1, len(tokens))
    words: list[OCRWord] = []
    for idx, token in enumerate(tokens):
        wx1 = line_box.x1 + idx * step
        wx2 = min(line_box.x2, wx1 + max(1.0, step))
        wbox = BoundingBox(wx1, line_box.y1, max(wx1 + 1.0, wx2), line_box.y2)
        words.append(OCRWord(text=token, bbox=wbox, confidence=0.95))
    return tuple(words)


@register_engine(
    "chandra",
    "Chandra OCR",
    "Mô hình VLM nhận diện bố cục, bảng biểu, toán học và chữ viết tay 90+ ngôn ngữ.",
    supports_handwriting=True,
    supports_tables=True,
)
class ChandraOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "checkpoint": ConfigField(DEFAULT_CHANDRA_CHECKPOINT, _valid_checkpoint),
        "method": ConfigField("hf", _valid_method),
        "prompt_type": ConfigField("ocr_layout", _valid_prompt_type),
        "api_base": ConfigField(
            DEFAULT_VLLM_URL, lambda v: isinstance(v, str) and bool(v.strip())
        ),
        "max_new_tokens": ConfigField(
            2048, lambda v: type(v) is int and 64 <= v <= 16384
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
        self._manager: Any | None = None
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
            self._manager = "vllm"
            return
        try:
            chandra_mod = import_module("chandra.model")
            self._manager = chandra_mod.InferenceManager(method="hf")
            return
        except ImportError:
            pass
        transformers = import_module("transformers")
        torch = import_module("torch")
        checkpoint, is_local = self._resolve_checkpoint()
        kwargs: dict[str, Any] = {"local_files_only": True} if is_local else {}
        self._processor = transformers.AutoProcessor.from_pretrained(
            checkpoint, **kwargs
        )
        model_cls = getattr(
            transformers,
            "AutoModelForMultimodalLM",
            getattr(
                transformers,
                "AutoModelForVision2Seq",
                transformers.AutoModelForCausalLM,
            ),
        )
        self._model = model_cls.from_pretrained(checkpoint, **kwargs)
        target = str(self._config["device"])
        if target == "auto":
            target = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(target)
        self._model.eval()

    def _unload_model(self) -> None:
        self._processor = None
        self._model = None
        self._manager = None

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        arr = np.asarray(image)
        height, width = int(arr.shape[0]), int(arr.shape[1])
        pil_image = ndarray_to_pil(arr)
        if self._manager == "vllm":
            raw = self._infer_vllm(pil_image)
        elif self._manager is not None:
            raw = self._infer_chandra_pkg(pil_image)
        else:
            raw = self._infer_hf(pil_image)
        page = parse_chandra_output(raw, width, height, page_number)
        if not self._config.get("use_tables", True):
            return page.with_updates(tables=())
        return page

    def _active_prompt(self) -> str:
        ptype = str(self._config.get("prompt_type") or "ocr_layout")
        return _CHANDRA_OCR_ONLY_PROMPT if ptype == "ocr" else _CHANDRA_PROMPT

    def _infer_chandra_pkg(self, pil_image: Any) -> str:
        if self._manager is None:
            raise OCREngineError("Chandra InferenceManager chưa được khởi tạo.")
        schema = import_module("chandra.model.schema")
        ptype = str(self._config.get("prompt_type") or "ocr_layout")
        batch = [schema.BatchInputItem(image=pil_image, prompt_type=ptype)]
        result = self._manager.generate(batch)[0]
        return str(getattr(result, "html", None) or getattr(result, "markdown", ""))

    def _infer_hf(self, pil_image: Any) -> str:
        if self._processor is None or self._model is None:
            raise OCREngineError("Chandra OCR chưa được khởi tạo.")
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
                "temperature": 0.0,
            }
        ).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310  # nosec B310
            data = json.loads(resp.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"])

"""Lazy PaddleOCR adapter supporting legacy and current result shapes."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable, Mapping
from html.parser import HTMLParser
from importlib import import_module
from typing import Any

from src.core.models import BoundingBox, OCRPage, OCRTable
from src.engines.base_engine import BaseOCREngine, ConfigField
from src.engines.engine_registry import register_engine
from src.engines.result_builder import LineResult, build_page
from src.services.weights_manager import ModelWeightsManager

_MAX_TABLE_DIMENSION = 1000
_MAX_TABLE_CELLS = 10_000
_MAX_TABLE_HTML_CHARS = 2_000_000


def _supported_options(
    factory: Callable[..., object], options: dict[str, object]
) -> dict[str, object]:
    """Keep compatibility with both PaddleOCR 2.x and 3.x constructors."""
    try:
        parameters = inspect.signature(factory).parameters.values()
    except (TypeError, ValueError):
        return options
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters):
        return options
    names = {item.name for item in parameters}
    return {name: value for name, value in options.items() if name in names}


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


@register_engine(
    "paddle",
    "PaddleOCR",
    "Nhận diện nhanh PP-OCRv4/v5/v6, PP-StructureV3 và PaddleOCR-VL.",
    supports_handwriting=True,
    supports_tables=True,
)
class PaddleOCREngine(BaseOCREngine):
    CONFIG_SCHEMA = {
        "lang": ConfigField(
            "vi", lambda value: isinstance(value, str) and bool(value.strip())
        ),
        "ocr_version": ConfigField(
            "",
            lambda value: isinstance(value, str)
            and value in {"", "PP-OCRv3", "PP-OCRv4", "PP-OCRv5", "PP-OCRv6"},
        ),
        "model_tier": ConfigField(
            "",
            lambda value: isinstance(value, str)
            and value in {"", "mobile", "server", "tiny"},
        ),
        "pipeline_mode": ConfigField(
            "",
            lambda value: isinstance(value, str)
            and value in {"", "standard", "pp_structure_v3", "paddleocr_vl"},
        ),
        "device": ConfigField(
            "cpu",
            lambda value: isinstance(value, str)
            and (value in {"auto", "cpu", "cuda"} or value.startswith("cuda:")),
        ),
        "det_db_thresh": ConfigField(
            0.3,
            lambda value: isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0 <= value <= 1,
        ),
        "use_tables": ConfigField(True, lambda value: type(value) is bool),
        "rec_model_dir": ConfigField(
            "",
            lambda value: value is None or isinstance(value, str),
        ),
        "det_model_dir": ConfigField(
            "",
            lambda value: value is None or isinstance(value, str),
        ),
    }

    def __init__(
        self,
        weights_manager: ModelWeightsManager | None = None,
        config: Mapping[str, object] | None = None,
    ) -> None:
        self._ocr: Any | None = None
        self._table_model: Any | None = None
        self._vl_model: Any | None = None
        super().__init__(weights_manager, config)

    @staticmethod
    def _ensure_cpu_compatibility() -> None:
        try:
            inference: Any = import_module("paddle.inference")
            if getattr(inference, "_pdf_ocr_cpu_patched", False):
                return
            orig_create = getattr(inference, "create_predictor", None)
            if orig_create is None:
                return

            def _patched_create(config: Any) -> Any:
                if hasattr(config, "disable_onednn"):
                    config.disable_onednn()
                if hasattr(config, "disable_mkldnn"):
                    config.disable_mkldnn()
                return orig_create(config)

            inference.create_predictor = _patched_create
            inference._pdf_ocr_cpu_patched = True
        except Exception:  # nosec B110
            pass

    def _load_model(self) -> None:
        try:
            import_module("torch")
        except Exception:  # nosec B110
            pass
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        if not self._uses_gpu():
            self._ensure_cpu_compatibility()
        paddleocr = import_module("paddleocr")
        mode = str(self._config.get("pipeline_mode") or "").strip()
        if mode == "paddleocr_vl" and hasattr(paddleocr, "PaddleOCRVL"):
            vl_cls = paddleocr.PaddleOCRVL
            vl_opts: dict[str, object] = {"device": self._paddle_device()}
            self._vl_model = vl_cls(**_supported_options(vl_cls, vl_opts))
            return
        legacy_options, current_options = self._build_ocr_options()
        factory = paddleocr.PaddleOCR
        signature = inspect.signature(factory).parameters
        is_current = "use_doc_orientation_classify" in signature
        options = current_options if is_current else legacy_options
        self._ocr = factory(**_supported_options(factory, options))
        if bool(self._config["use_tables"]) or mode == "pp_structure_v3":
            self._load_table_model(paddleocr, mode == "pp_structure_v3")

    def _build_ocr_options(self) -> tuple[dict[str, object], dict[str, object]]:
        legacy: dict[str, object] = {
            "lang": self._config["lang"],
            "use_angle_cls": True,
            "det_db_thresh": self._config["det_db_thresh"],
            "use_gpu": self._uses_gpu(),
        }
        current: dict[str, object] = {
            "lang": self._config["lang"],
            "device": self._paddle_device(),
            "use_doc_orientation_classify": True,
            "use_textline_orientation": True,
            "text_det_thresh": self._config["det_db_thresh"],
        }
        ocr_ver = str(self._config.get("ocr_version") or "").strip()
        if ocr_ver:
            legacy["ocr_version"] = ocr_ver
            current["ocr_version"] = ocr_ver
        tier = str(self._config.get("model_tier") or "").strip()
        if tier:
            ver_prefix = ocr_ver if ocr_ver in {"PP-OCRv4", "PP-OCRv5"} else "PP-OCRv5"
            tier_tag = "server" if tier == "server" else "mobile"
            current["text_detection_model_name"] = f"{ver_prefix}_{tier_tag}_det"
            current["text_recognition_model_name"] = f"{ver_prefix}_{tier_tag}_rec"
        rec_dir = str(self._config.get("rec_model_dir") or "").strip()
        det_dir = str(self._config.get("det_model_dir") or "").strip()
        if rec_dir:
            legacy["rec_model_dir"] = rec_dir
            current["text_recognition_model_dir"] = rec_dir
        if det_dir:
            legacy["det_model_dir"] = det_dir
            current["text_detection_model_dir"] = det_dir
        return legacy, current

    def _load_table_model(self, paddleocr: Any, full_structure: bool) -> None:
        table_factory = getattr(paddleocr, "PPStructureV3", None)
        is_current_table = table_factory is not None
        table_factory = table_factory or getattr(paddleocr, "PPStructure", None)
        if table_factory is None:
            return
        table_options: dict[str, object] = (
            {
                "device": self._paddle_device(),
                "use_table_recognition": True,
                **({"use_formula_recognition": True} if full_structure else {}),
            }
            if is_current_table
            else {"use_gpu": self._uses_gpu()}
        )
        try:
            self._table_model = table_factory(
                **_supported_options(table_factory, table_options)
            )
        except Exception:
            self._table_model = None

    def _uses_gpu(self) -> bool:
        return str(self._config["device"]).startswith("cuda")

    def _paddle_device(self) -> str:
        device = str(self._config["device"])
        if device == "auto":
            return "cpu"
        return device.replace("cuda", "gpu", 1)

    def _recognize(self, image: object, page_number: int) -> OCRPage:
        if self._vl_model is not None:
            raw_vl = (
                self._vl_model.predict(image)
                if hasattr(self._vl_model, "predict")
                else self._vl_model(image)
            )
            lines = self._parse_text_results(raw_vl)
            tables = self._tables_from_raw(raw_vl)
            return build_page(image, page_number, lines, tables)
        if self._ocr is None:
            raise RuntimeError("PaddleOCR model is unavailable.")
        if hasattr(self._ocr, "predict"):
            raw_text = self._ocr.predict(image)
        else:
            raw_text = self._ocr.ocr(image, cls=True)
        lines = self._parse_text_results(raw_text)
        tables = self._recognize_tables(image)
        return build_page(image, page_number, lines, tables)

    def _recognize_tables(self, image: object) -> tuple[OCRTable, ...]:
        if self._table_model is None:
            return ()
        raw = (
            self._table_model.predict(image)
            if hasattr(self._table_model, "predict")
            else self._table_model(image)
        )
        return self._tables_from_raw(raw)

    def _tables_from_raw(self, raw: object) -> tuple[OCRTable, ...]:
        tables: list[OCRTable] = []
        items = raw if isinstance(raw, (tuple, list)) else ()
        for item in items:
            payload = self._as_dict(item)
            tables.extend(self._tables_from_payload(payload))
        return tuple(tables)

    def _parse_text_results(self, raw: object) -> list[LineResult]:
        lines: list[LineResult] = []
        items = raw if isinstance(raw, (tuple, list)) else (raw,)
        for item in items:
            payload = self._as_dict(item)
            if payload:
                lines.extend(self._lines_from_mapping(payload))
                continue
            page = item
            while (
                isinstance(page, list)
                and len(page) == 1
                and isinstance(page[0], list)
                and not self._is_legacy_entry(page)
            ):
                page = page[0]
            if not isinstance(page, (tuple, list)):
                continue
            entries = (page,) if self._is_legacy_entry(page) else page
            for entry in entries:
                if not isinstance(entry, (tuple, list)) or len(entry) < 2:
                    continue
                points, recognition = entry[:2]
                if not isinstance(recognition, (tuple, list)) or len(recognition) < 2:
                    continue
                lines.append((points, str(recognition[0]), float(recognition[1])))
        return lines

    @staticmethod
    def _is_legacy_entry(value: object) -> bool:
        return (
            isinstance(value, (tuple, list))
            and len(value) >= 2
            and isinstance(value[1], (tuple, list))
            and len(value[1]) >= 2
            and isinstance(value[1][0], str)
        )

    @staticmethod
    def _as_dict(item: object) -> dict[str, Any]:
        if isinstance(item, dict):
            return item
        payload = getattr(item, "json", None)
        if callable(payload):
            payload = payload()
        return payload if isinstance(payload, dict) else {}

    def _lines_from_mapping(self, payload: dict[str, Any]) -> list[LineResult]:
        result = payload.get("res", payload)
        if not isinstance(result, dict):
            return []
        polygons = result.get("rec_polys")
        if polygons is None:
            polygons = result.get("dt_polys", ())
        texts = result.get("rec_texts", ())
        scores = result.get("rec_scores", ())
        return [
            (points, str(text), float(score))
            for points, text, score in zip(polygons, texts, scores, strict=False)
        ]

    def _tables_from_payload(self, payload: dict[str, Any]) -> list[OCRTable]:
        result = payload.get("res", payload)
        if not isinstance(result, dict):
            return []
        candidates = result.get("table_res_list")
        if isinstance(candidates, list):
            return [table for item in candidates if (table := self._make_table(item))]
        table_type = str(result.get("type", payload.get("type", ""))).lower()
        if table_type == "table" or "rows" in result or "cells" in result:
            table = self._make_table(payload)
            return [table] if table is not None else []
        return []

    def _make_table(self, payload: object) -> OCRTable | None:
        if not isinstance(payload, dict):
            return None
        content = payload.get("res", payload)
        if not isinstance(content, dict):
            return None
        rows = self._table_rows(content)
        if not rows:
            return None
        bbox_value = payload.get("bbox") or content.get("bbox") or [0, 0, 1, 1]
        return OCRTable(rows=rows, bbox=self._table_bbox(bbox_value))

    @staticmethod
    def _table_rows(content: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
        rows = content.get("rows")
        if isinstance(rows, list):
            if len(rows) > _MAX_TABLE_DIMENSION or any(
                not isinstance(row, (tuple, list)) or len(row) > _MAX_TABLE_DIMENSION
                for row in rows
            ):
                return ()
            return tuple(tuple(str(cell) for cell in row) for row in rows)
        cells = content.get("cells")
        if isinstance(cells, list) and cells:
            return PaddleOCREngine._rows_from_cells(cells)
        html = content.get("pred_html") or content.get("html")
        if isinstance(html, str) and len(html) <= _MAX_TABLE_HTML_CHARS:
            parser = _TableHTMLParser()
            parser.feed(html)
            return tuple(tuple(row) for row in parser.rows)
        return ()

    @staticmethod
    def _rows_from_cells(cells: list[object]) -> tuple[tuple[str, ...], ...]:
        if len(cells) > _MAX_TABLE_CELLS:
            return ()
        mappings: list[dict[str, Any]] = []
        for cell in cells:
            if not isinstance(cell, dict):
                return ()
            mappings.append(cell)
        indexes: list[tuple[int, int]] = []
        for cell in mappings:
            row = cell.get("row")
            column = cell.get("col")
            if (
                type(row) is not int
                or type(column) is not int
                or not 0 <= row < _MAX_TABLE_DIMENSION
                or not 0 <= column < _MAX_TABLE_DIMENSION
            ):
                return ()
            indexes.append((row, column))
        row_count = max(row for row, _ in indexes) + 1
        col_count = max(column for _, column in indexes) + 1
        if row_count * col_count > _MAX_TABLE_CELLS:
            return ()
        matrix = [["" for _ in range(col_count)] for _ in range(row_count)]
        for cell, (row, column) in zip(mappings, indexes, strict=True):
            matrix[row][column] = str(cell.get("text", ""))
        return tuple(tuple(row) for row in matrix)

    @staticmethod
    def _table_bbox(value: object) -> BoundingBox:
        if isinstance(value, (tuple, list)) and len(value) == 4:
            coordinates = [max(0.0, float(item)) for item in value]
            return BoundingBox(
                coordinates[0], coordinates[1], coordinates[2], coordinates[3]
            )
        return BoundingBox(0, 0, 1, 1)

    def _unload_model(self) -> None:
        self._ocr = None
        self._table_model = None
        self._vl_model = None

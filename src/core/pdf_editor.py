"""PDF editing, annotation, security, metadata, and reading color-mode utilities."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pymupdf

PAGE_COLOR_MODES = ("normal", "sepia", "night")


@dataclass(frozen=True)
class PDFProperties:
    """Comprehensive document properties and metadata for an inspected PDF."""

    path: str
    pdf_version: str
    page_count: int
    page_width_pt: float
    page_height_pt: float
    file_size_bytes: int
    is_encrypted: bool
    metadata: dict[str, str]
    fonts: tuple[str, ...]
    bookmarks_count: int


def _save_pdf_atomic(
    doc: pymupdf.Document,
    source_path: Path,
    output_path: str | Path | None = None,
    **save_kwargs: object,
) -> Path:
    """Save a PyMuPDF document either to output_path or atomically over source_path."""
    target = Path(output_path).resolve() if output_path is not None else source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target == source_path:
        fd, temp_name = tempfile.mkstemp(suffix=".pdf", dir=str(source_path.parent))
        try:
            import os

            os.close(fd)
            temp_path = Path(temp_name)
            doc.save(str(temp_path), **save_kwargs)
            doc.close()
            shutil.move(str(temp_path), str(source_path))
        finally:
            if Path(temp_name).exists():
                Path(temp_name).unlink(missing_ok=True)
        return source_path

    doc.save(str(target), **save_kwargs)
    doc.close()
    return target


def _edit_pdf(
    pdf_path: str | Path,
    mutator: Callable[[pymupdf.Document], None],
    output_path: str | Path | None = None,
    **save_kwargs: object,
) -> Path:
    """Open a PDF, run a mutation callback, and save atomically."""
    source = Path(pdf_path).resolve()
    doc = pymupdf.open(str(source))
    try:
        mutator(doc)
    except Exception:
        doc.close()
        raise
    return _save_pdf_atomic(doc, source, output_path, **save_kwargs)


def _validate_page_indices(page_numbers: Sequence[int], total_pages: int) -> list[int]:
    """Validate 1-based page numbers and return 0-based indices."""
    if not page_numbers:
        raise ValueError("Danh sách trang không được để trống.")
    indices: list[int] = []
    for num in page_numbers:
        if num < 1 or num > total_pages:
            raise ValueError(
                f"Số trang {num} nằm ngoài phạm vi hợp lệ (1..{total_pages})."
            )
        indices.append(num - 1)
    return indices


def _denorm_rect(
    page: pymupdf.Page, rect_norm: tuple[float, float, float, float]
) -> pymupdf.Rect:
    """Convert normalized (x0, y0, x1, y1) in 0..1 to page point coordinates."""
    bounds = page.rect
    x0 = bounds.x0 + max(0.0, min(1.0, rect_norm[0])) * bounds.width
    y0 = bounds.y0 + max(0.0, min(1.0, rect_norm[1])) * bounds.height
    x1 = bounds.x0 + max(0.0, min(1.0, rect_norm[2])) * bounds.width
    y1 = bounds.y0 + max(0.0, min(1.0, rect_norm[3])) * bounds.height
    return pymupdf.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def inspect_pdf_properties(pdf_path: str | Path) -> PDFProperties:
    """Extract PDF version, dimensions, metadata, embedded fonts, and TOC count."""
    source = Path(pdf_path).resolve()
    size_bytes = int(source.stat().st_size) if source.exists() else 0
    with pymupdf.open(str(source)) as doc:
        raw_meta = doc.metadata or {}
        meta = {
            key: str(raw_meta.get(key) or "")
            for key in (
                "title",
                "author",
                "subject",
                "keywords",
                "creator",
                "producer",
                "creationDate",
                "modDate",
            )
        }
        version = str(raw_meta.get("format") or "PDF 1.7")
        count = len(doc)
        width_pt = float(doc[0].rect.width) if count > 0 else 0.0
        height_pt = float(doc[0].rect.height) if count > 0 else 0.0
        font_names: set[str] = set()
        for idx in range(min(count, 50)):
            for font in doc.get_page_fonts(idx):
                if len(font) >= 4 and font[3]:
                    font_names.add(str(font[3]))
        toc = doc.get_toc(simple=True)
        return PDFProperties(
            path=str(source),
            pdf_version=version,
            page_count=count,
            page_width_pt=width_pt,
            page_height_pt=height_pt,
            file_size_bytes=size_bytes,
            is_encrypted=bool(doc.is_encrypted),
            metadata=meta,
            fonts=tuple(sorted(font_names)),
            bookmarks_count=len(toc),
        )


def rotate_pages_in_pdf(
    pdf_path: str | Path,
    page_numbers: Sequence[int],
    delta_degrees: int,
    output_path: str | Path | None = None,
) -> Path:
    """Rotate selected 1-based pages by delta_degrees (multiple of 90) and save."""

    def _mutate(doc: pymupdf.Document) -> None:
        for idx in _validate_page_indices(page_numbers, len(doc)):
            page = doc[idx]
            page.set_rotation((page.rotation + delta_degrees) % 360)

    return _edit_pdf(pdf_path, _mutate, output_path)


def delete_pages_from_pdf(
    pdf_path: str | Path,
    page_numbers: Sequence[int],
    output_path: str | Path | None = None,
) -> Path:
    """Delete selected 1-based pages from a PDF without removing every page."""

    def _mutate(doc: pymupdf.Document) -> None:
        indices = sorted(
            set(_validate_page_indices(page_numbers, len(doc))), reverse=True
        )
        if len(indices) >= len(doc):
            raise ValueError("Tài liệu PDF không thể xóa toàn bộ các trang.")
        for idx in indices:
            doc.delete_page(idx)

    return _edit_pdf(pdf_path, _mutate, output_path)


def extract_pages_to_pdf(
    pdf_path: str | Path,
    page_numbers: Sequence[int],
    output_path: str | Path,
) -> Path:
    """Extract selected 1-based pages into a new PDF file."""
    source = Path(pdf_path).resolve()
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(str(source)) as doc:
        indices = _validate_page_indices(page_numbers, len(doc))
        doc.select(indices)
        doc.save(str(target), garbage=3, deflate=True)
    return target


def merge_pdfs(
    pdf_paths: Sequence[str | Path],
    output_path: str | Path,
) -> Path:
    """Merge multiple PDF documents sequentially into output_path."""
    if not pdf_paths:
        raise ValueError("Cần ít nhất một tệp PDF để ghép nối.")
    target = Path(output_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    merged = pymupdf.open()
    try:
        for item in pdf_paths:
            with pymupdf.open(str(Path(item).resolve())) as part:
                merged.insert_pdf(part)
        merged.save(str(target), garbage=3, deflate=True)
    finally:
        merged.close()
    return target


def reorder_pages_in_pdf(
    pdf_path: str | Path,
    new_order: Sequence[int],
    output_path: str | Path | None = None,
) -> Path:
    """Reorder pages according to a 1-based page sequence."""

    def _mutate(doc: pymupdf.Document) -> None:
        indices = _validate_page_indices(new_order, len(doc))
        doc.select(indices)

    return _edit_pdf(pdf_path, _mutate, output_path)


def add_highlight_annotation(
    pdf_path: str | Path,
    page_number: int,
    rect_norm: tuple[float, float, float, float],
    color: tuple[float, float, float] = (1.0, 0.92, 0.23),
    output_path: str | Path | None = None,
) -> Path:
    """Add a colored highlight markup annotation on a normalized page rectangle."""

    def _mutate(doc: pymupdf.Document) -> None:
        idx = _validate_page_indices([page_number], len(doc))[0]
        page = doc[idx]
        annot = page.add_highlight_annot(_denorm_rect(page, rect_norm))
        annot.set_colors(stroke=color)
        annot.update()

    return _edit_pdf(pdf_path, _mutate, output_path)


def add_text_note_annotation(
    pdf_path: str | Path,
    page_number: int,
    point_norm: tuple[float, float],
    text: str,
    output_path: str | Path | None = None,
) -> Path:
    """Add a sticky text note annotation at normalized (x, y) coordinates."""

    def _mutate(doc: pymupdf.Document) -> None:
        idx = _validate_page_indices([page_number], len(doc))[0]
        page = doc[idx]
        bounds = page.rect
        pt = pymupdf.Point(
            bounds.x0 + max(0.0, min(1.0, point_norm[0])) * bounds.width,
            bounds.y0 + max(0.0, min(1.0, point_norm[1])) * bounds.height,
        )
        annot = page.add_text_annot(pt, text.strip() or "Ghi chú")
        annot.update()

    return _edit_pdf(pdf_path, _mutate, output_path)


def add_stamp_image(
    pdf_path: str | Path,
    page_number: int,
    rect_norm: tuple[float, float, float, float],
    image_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Embed a signature or stamp image onto a normalized rectangle on page_number."""
    stamp_file = Path(image_path).resolve()
    if not stamp_file.is_file():
        raise FileNotFoundError(f"Không tìm thấy tệp ảnh chữ ký/con dấu: {stamp_file}")

    def _mutate(doc: pymupdf.Document) -> None:
        idx = _validate_page_indices([page_number], len(doc))[0]
        page = doc[idx]
        page.insert_image(_denorm_rect(page, rect_norm), filename=str(stamp_file))

    return _edit_pdf(pdf_path, _mutate, output_path)


def redact_region_in_pdf(
    pdf_path: str | Path,
    page_number: int,
    rect_norm: tuple[float, float, float, float],
    fill_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    output_path: str | Path | None = None,
) -> Path:
    """Permanently redact text and graphics inside a normalized page rectangle."""

    def _mutate(doc: pymupdf.Document) -> None:
        idx = _validate_page_indices([page_number], len(doc))[0]
        page = doc[idx]
        page.add_redact_annot(_denorm_rect(page, rect_norm), fill=fill_color)
        page.apply_redactions()

    return _edit_pdf(pdf_path, _mutate, output_path, garbage=3, deflate=True)


def update_pdf_metadata(
    pdf_path: str | Path,
    metadata: Mapping[str, str],
    output_path: str | Path | None = None,
) -> Path:
    """Update standard PDF metadata fields (title, author, subject, keywords)."""

    def _mutate(doc: pymupdf.Document) -> None:
        merged = dict(doc.metadata or {})
        for key in ("title", "author", "subject", "keywords", "creator", "producer"):
            if key in metadata:
                merged[key] = str(metadata[key]).strip()
        doc.set_metadata(merged)

    return _edit_pdf(pdf_path, _mutate, output_path)


def update_pdf_bookmarks(
    pdf_path: str | Path,
    bookmarks: Sequence[tuple[int, str, int]],
    output_path: str | Path | None = None,
) -> Path:
    """Replace the PDF outline/bookmarks table of contents."""

    def _mutate(doc: pymupdf.Document) -> None:
        total = max(1, len(doc))
        toc = [
            [max(1, int(level)), str(title).strip(), max(1, min(total, int(page_num)))]
            for level, title, page_num in bookmarks
            if str(title).strip()
        ]
        doc.set_toc(toc)

    return _edit_pdf(pdf_path, _mutate, output_path)


def protect_pdf_with_password(
    pdf_path: str | Path,
    user_password: str,
    owner_password: str | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Encrypt a PDF with AES-256 password protection (or remove if password empty)."""
    pw = user_password.strip()
    owner_pw = (owner_password or pw).strip()
    if not pw:
        return _edit_pdf(
            pdf_path,
            lambda _doc: None,
            output_path,
            encryption=int(getattr(pymupdf, "PDF_ENCRYPT_NONE", 0)),
        )
    return _edit_pdf(
        pdf_path,
        lambda _doc: None,
        output_path,
        encryption=int(getattr(pymupdf, "PDF_ENCRYPT_AES_256", 4)),
        user_pw=pw,
        owner_pw=owner_pw,
    )


def compress_pdf(
    pdf_path: str | Path,
    level: str = "balanced",
    output_path: str | Path | None = None,
) -> Path:
    """Optimize and compress a PDF using stream deflation and garbage collection."""
    garbage_level = 4 if level == "max" else (2 if level == "fast" else 3)
    return _edit_pdf(
        pdf_path,
        lambda _doc: None,
        output_path,
        garbage=garbage_level,
        deflate=True,
        clean=True,
    )


def apply_page_color_mode(image: np.ndarray, mode: str) -> np.ndarray:
    """Transform an RGB page image according to reading mode (normal, sepia, night)."""
    normalized = mode.strip().lower()
    if normalized == "night":
        # Smart dark reading mode: invert luminance into soft dark slate
        inv = 255 - image.astype(np.uint16)
        scaled = (inv * 225) // 255 + 18
        return np.clip(scaled, 0, 255).astype(np.uint8)
    if normalized == "sepia":
        # Eye-care warm paper tint (#F4ECD8 background while preserving crisp dark ink)
        arr = image.astype(np.float32)
        if arr.ndim == 3 and arr.shape[2] >= 3:
            tint = np.array(
                [244.0 / 255.0, 234.0 / 255.0, 210.0 / 255.0], dtype=np.float32
            )
            out = arr.copy()
            out[:, :, :3] = np.clip(arr[:, :, :3] * tint, 0.0, 255.0)
            return out.astype(np.uint8)
    return image

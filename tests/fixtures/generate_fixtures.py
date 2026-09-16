"""Regenerate the sample documents used by the end-to-end suite.

The committed fixtures are the contract; this script exists so they can be
rebuilt reproducibly. It needs a Unicode font with Vietnamese diacritics
(DejaVu Sans is used by default) and is not run as part of the test suite.

    python tests/fixtures/generate_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont

FIXTURES = Path(__file__).resolve().parent
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
)

VIETNAMESE_PARAGRAPH = (
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n\n"
    "Kính gửi: Phòng Kế toán\n"
    "Tôi tên là Nguyễn Văn An, sinh ngày 12 tháng 5 năm 1990.\n"
    "Đề nghị quý phòng xem xét và giải quyết cho tôi được nhận\n"
    "khoản trợ cấp theo quy định hiện hành của Nhà nước."
)

LEFT_COLUMN = (
    "Thị trường lao động quý III ghi nhận mức tăng\n"
    "trưởng ổn định ở nhiều ngành nghề. Số lao động\n"
    "có việc làm tăng thêm khoảng bốn trăm nghìn\n"
    "người so với cùng kỳ năm ngoái."
)
RIGHT_COLUMN = (
    "Ngành chế biến chế tạo tiếp tục dẫn đầu về số\n"
    "lượng tuyển dụng mới. Các doanh nghiệp vừa và\n"
    "nhỏ cũng mở rộng quy mô sau khi đơn hàng xuất\n"
    "khẩu phục hồi rõ rệt."
)

INVOICE_ROWS = (
    ("Mặt hàng", "Số lượng", "Đơn giá", "Thành tiền"),
    ("Sổ tay bìa cứng", "12", "45.000", "540.000"),
    ("Bút bi xanh", "50", "5.000", "250.000"),
    ("Giấy in A4", "8", "72.000", "576.000"),
    ("Tổng cộng", "", "", "1.366.000"),
)

HANDWRITING_LINES = (
    "Ghi chú cuộc họp ngày 14 tháng 9",
    "Chốt ngân sách quý tới",
    "Gửi báo cáo cho chị Lan",
)


def _font_path() -> str:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise SystemExit(
        "Không tìm thấy phông chữ Unicode. Hãy cài DejaVu Sans rồi chạy lại."
    )


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(), size)


def _canvas(width: int, height: int) -> Image.Image:
    return Image.new("RGB", (width, height), "white")


def write_text_pdf(path: Path, pages: list[str], *, columns: bool = False) -> None:
    """A PDF with a real text layer, so the text-based branch is exercised."""
    font_file = _font_path()
    with pymupdf.open() as pdf:
        for body in pages:
            page = pdf.new_page(width=595, height=842)
            page.insert_font(fontname="vi", fontfile=font_file)
            if columns:
                page.insert_textbox(
                    pymupdf.Rect(50, 60, 285, 500), body, fontname="vi", fontsize=11
                )
                page.insert_textbox(
                    pymupdf.Rect(310, 60, 545, 500),
                    RIGHT_COLUMN,
                    fontname="vi",
                    fontsize=11,
                )
            else:
                page.insert_textbox(
                    pymupdf.Rect(60, 70, 535, 700), body, fontname="vi", fontsize=12
                )
        # Embedding the whole Unicode font would make the fixture megabytes wide.
        pdf.subset_fonts()
        pdf.save(path, garbage=4, deflate=True)


def write_scanned_pdf(path: Path, source: Path) -> None:
    """An image-only PDF: no text layer at all, like a real scan."""
    page_image = Image.open(source).convert("L")
    jpeg = path.with_suffix(".tmp.jpg")
    page_image.save(jpeg, "JPEG", quality=70, optimize=True)
    try:
        with pymupdf.open() as pdf:
            width, height = page_image.size
            page = pdf.new_page(width=width, height=height)
            page.insert_image(pymupdf.Rect(0, 0, width, height), filename=str(jpeg))
            pdf.save(path, garbage=4, deflate=True)
    finally:
        jpeg.unlink(missing_ok=True)


def write_text_image(path: Path, body: str, *, size: tuple[int, int]) -> None:
    image = _canvas(*size)
    draw = ImageDraw.Draw(image)
    draw.multiline_text((40, 40), body, fill="black", font=_font(22), spacing=10)
    image.save(path)


def write_table_image(path: Path) -> None:
    image = _canvas(760, 320)
    draw = ImageDraw.Draw(image)
    font = _font(18)
    widths = (300, 110, 150, 170)
    top = 40
    for row_index, row in enumerate(INVOICE_ROWS):
        left = 30
        height = 52
        for column_index, cell in enumerate(row):
            box = (left, top, left + widths[column_index], top + height)
            draw.rectangle(box, outline="black", width=2)
            draw.text((left + 10, top + 15), cell, fill="black", font=font)
            left += widths[column_index]
        top += height
        if row_index == 0:
            draw.rectangle((30, 40, 30 + sum(widths), 92), outline="black", width=3)
    image.save(path)


def write_skewed_image(path: Path, body: str) -> None:
    """Rotated, with a soft shadow, the way a phone photo of a page looks."""
    flat = _canvas(760, 520)
    draw = ImageDraw.Draw(flat)
    draw.multiline_text((50, 60), body, fill="black", font=_font(24), spacing=12)
    array = np.array(flat)
    centre = (array.shape[1] / 2, array.shape[0] / 2)
    rotation = cv2.getRotationMatrix2D(centre, 7.0, 1.0)
    rotated = cv2.warpAffine(
        array,
        rotation,
        (array.shape[1], array.shape[0]),
        borderValue=(255, 255, 255),
    )
    gradient = np.linspace(0.55, 1.0, rotated.shape[1], dtype=np.float32)
    shadowed = np.clip(rotated * gradient[None, :, None], 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), cv2.cvtColor(shadowed, cv2.COLOR_RGB2BGR))


def write_handwriting_image(path: Path) -> None:
    """Slanted, uneven baselines: a stand-in for handwritten notes."""
    image = _canvas(700, 300)
    draw = ImageDraw.Draw(image)
    font = _font(26)
    for index, line in enumerate(HANDWRITING_LINES):
        offset = 6 if index % 2 else -4
        draw.text((45 + offset, 45 + index * 78), line, fill=(25, 25, 90), font=font)
    array = np.array(image)
    warped = cv2.warpAffine(
        array,
        np.float32([[1, 0.12, -20], [0, 1, 0]]),
        (array.shape[1], array.shape[0]),
        borderValue=(255, 255, 255),
    )
    cv2.imwrite(str(path), cv2.cvtColor(warped, cv2.COLOR_RGB2BGR))


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    write_text_pdf(
        FIXTURES / "sample_vi_text.pdf", [VIETNAMESE_PARAGRAPH, VIETNAMESE_PARAGRAPH]
    )
    write_text_pdf(FIXTURES / "sample_two_column.pdf", [LEFT_COLUMN], columns=True)
    write_text_image(FIXTURES / "sample_vi.png", VIETNAMESE_PARAGRAPH, size=(760, 520))
    write_table_image(FIXTURES / "sample_table.png")
    write_skewed_image(FIXTURES / "sample_skewed.png", VIETNAMESE_PARAGRAPH)
    write_handwriting_image(FIXTURES / "sample_handwriting.png")
    write_scanned_pdf(FIXTURES / "sample_scanned.pdf", FIXTURES / "sample_vi.png")
    for path in sorted(FIXTURES.glob("sample_*")):
        print(f"{path.name}: {path.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

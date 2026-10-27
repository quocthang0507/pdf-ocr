"""Declarative OCR engine parameter specifications and preprocessing options."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_ENGINE_ID = "vietocr"
MIN_DPI = 72
MAX_DPI = 600
DEFAULT_DPI = 300
BROWSE_FILE_SENTINEL = "__browse_file__"
BROWSE_DIR_SENTINEL = "__browse_dir__"
MODEL_PARAM_KEYS: dict[str, tuple[str, str]] = {
    "vietocr": ("architecture", BROWSE_FILE_SENTINEL),
    "trocr": ("checkpoint", BROWSE_DIR_SENTINEL),
    "easyocr": ("recog_network", BROWSE_FILE_SENTINEL),
    "paddle": ("rec_model_dir", BROWSE_DIR_SENTINEL),
    "chandra": ("checkpoint", BROWSE_DIR_SENTINEL),
    "dots_ocr": ("checkpoint", BROWSE_DIR_SENTINEL),
}

PREPROCESSING_STAGES: tuple[tuple[str, str], ...] = (
    ("orientation", "Tự xoay đúng hướng"),
    ("deskew", "Làm thẳng ảnh nghiêng"),
    ("borders", "Cắt viền thừa"),
    ("enhance", "Tăng cường chất lượng ảnh"),
)

#: Layout choices: key, label, tooltip. All are on by default.
STRUCTURE_OPTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "detect_tables",
        "Nhận diện bảng biểu",
        "Tách bảng thành lưới hàng/cột để chỉnh sửa và xuất Excel/Word. "
        "PaddleOCR, Chandra, dots.ocr tự nhận diện bảng; với các mô hình khác, "
        "ứng dụng dò bảng có kẻ khung (kể cả ô gộp).",
    ),
    (
        "reading_order",
        "Sắp xếp thứ tự đọc nhiều cột",
        "Đọc hết cột này rồi mới sang cột khác, không đọc xuyên cột.",
    ),
    (
        "merge_paragraphs",
        "Gộp các dòng thành đoạn văn",
        "Nối các dòng liên tiếp thuộc cùng một đoạn thành một khối.",
    ),
    (
        "spell_check",
        "Sửa lỗi chính tả và dấu tiếng Việt (N-gram)",
        "Tự động sửa lỗi dấu thanh, nguyên âm mũ/móc và từ ghép tiếng Việt "
        "theo ngữ cảnh N-gram (1/2/3-gram) sau khi OCR.",
    ),
)


@dataclass(frozen=True)
class EngineParameter:
    """One tunable engine setting; `choices` makes it a drop-down, else a number."""

    key: str
    label: str
    default: Any
    tip: str
    choices: tuple[tuple[str, Any], ...] = ()
    minimum: float = 0
    maximum: float = 1
    step: float = 1


_LANGUAGE_CHOICES: tuple[tuple[str, Any], ...] = (
    ("Tiếng Việt + Anh", ("vi", "en")),
    ("Chỉ tiếng Việt", ("vi",)),
    ("Chỉ tiếng Anh", ("en",)),
    (
        "Đa ngôn ngữ (Việt, Anh, Pháp, Trung, Nhật, Hàn)",
        ("vi", "en", "fr", "zh", "ja", "ko"),
    ),
)

#: Settings each engine accepts beyond device; mirrors its CONFIG_SCHEMA.
ENGINE_PARAMETERS: dict[str, tuple[EngineParameter, ...]] = {
    "vietocr": (
        EngineParameter(
            "architecture",
            "Kiến trúc / Biến thể",
            "vgg_transformer",
            (
                "Chọn biến thể kiến trúc VietOCR theo mục đích (chính xác cao, "
                "tốc độ nhanh, đặc trưng sâu) hoặc tệp .pth tùy chỉnh."
            ),
            choices=(
                ("VGG19-BN + Transformer (Chính xác cao)", "vgg_transformer"),
                ("VGG19-BN + Seq2Seq Attention (Tốc độ nhanh)", "vgg_seq2seq"),
                ("ResNet50 + Transformer (Chữ phức tạp)", "resnet_transformer"),
            ),
        ),
    ),
    "surya": (
        EngineParameter(
            "langs",
            "Ngôn ngữ",
            ("vi", "en"),
            "Ngôn ngữ có trong tài liệu.",
            choices=_LANGUAGE_CHOICES,
        ),
    ),
    "easyocr": (
        EngineParameter(
            "langs",
            "Ngôn ngữ",
            ("vi", "en"),
            "Ngôn ngữ có trong tài liệu.",
            choices=_LANGUAGE_CHOICES,
        ),
        EngineParameter(
            "recog_network",
            "Mạng nhận diện",
            "",
            (
                "Chọn thế hệ mạng nhận diện chữ (Gen 2 nhanh nhẹ, Gen 1 cổ điển) "
                "hoặc tệp .pth tùy chỉnh."
            ),
            choices=(
                ("Tự động theo ngôn ngữ", ""),
                ("Generation 2 - Latin / Tiếng Việt (latin_g2)", "latin_g2"),
                ("Generation 2 - Tiếng Anh tối ưu (english_g2)", "english_g2"),
                ("Generation 1 - Latin cổ điển (latin_g1)", "latin_g1"),
            ),
        ),
        EngineParameter(
            "detect_network",
            "Mạng phát hiện chữ",
            "",
            "CRAFT chính xác cho chữ nghiêng/cong; DBNet18 nhanh và nhẹ RAM.",
            choices=(
                ("CRAFT (Mặc định - Chính xác cao)", ""),
                ("DBNet18 (Tốc độ cao, nhẹ RAM)", "dbnet18"),
            ),
        ),
        EngineParameter(
            "beam_width",
            "Beam width",
            5,
            "Càng lớn càng chính xác nhưng chậm hơn.",
            minimum=1,
            maximum=100,
        ),
    ),
    "paddle": (
        EngineParameter(
            "lang",
            "Ngôn ngữ",
            "vi",
            (
                "Ngôn ngữ chính của tài liệu. Lưu ý: các model PaddleOCR chính "
                "thức (PP-OCRv5/v6) không có chữ tiếng Việt mang dấu nặng, hỏi, "
                "ngã và chữ hai dấu (ộ, ậ, ễ, ử, ọ...) nên sẽ bỏ sót các chữ này. "
                "Với tài liệu tiếng Việt hãy dùng VietOCR hoặc Surya, hoặc chọn "
                "một model nhận diện tiếng Việt tùy chỉnh bên dưới."
            ),
            choices=(
                ("Tiếng Việt", "vi"),
                ("Tiếng Anh", "en"),
                ("Hệ chữ Latin (Đa ngôn ngữ)", "latin"),
                ("Tiếng Trung / Đa ngôn ngữ (ch)", "ch"),
                ("Tiếng Nhật", "japan"),
                ("Tiếng Hàn", "korean"),
                ("Tiếng Pháp", "fr"),
                ("Tiếng Đức", "german"),
            ),
        ),
        EngineParameter(
            "pipeline_mode",
            "Nhánh mô hình (Pipeline)",
            "",
            (
                "Chọn nhánh xử lý: PP-OCR tiêu chuẩn, PP-StructureV3 "
                "(bố cục/bảng/công thức) hoặc PaddleOCR-VL (VLM 0.9B đa tác vụ)."
            ),
            choices=(
                ("Tiêu chuẩn (PP-OCR + PP-Structure)", ""),
                (
                    "PP-StructureV3 (Phân tích bố cục, bảng, công thức)",
                    "pp_structure_v3",
                ),
                (
                    "PaddleOCR-VL 1.6 (VLM 0.9B: Bảng, công thức, chữ cổ, con dấu)",
                    "paddleocr_vl",
                ),
            ),
        ),
        EngineParameter(
            "ocr_version",
            "Phiên bản PP-OCR",
            "",
            (
                "Chọn thế hệ PP-OCR: v6 (50 ngôn ngữ, chính xác cao), "
                "v5 (chữ viết tay/dọc), v4 (ổn định), v3."
            ),
            choices=(
                ("Tự động (Mặc định)", ""),
                ("PP-OCRv6 (Mới nhất - 50 ngôn ngữ, tốc độ cao)", "PP-OCRv6"),
                ("PP-OCRv5 (Đa kịch bản, chữ viết tay, chữ dọc)", "PP-OCRv5"),
                ("PP-OCRv4 (Ổn định, phổ biến)", "PP-OCRv4"),
                ("PP-OCRv3 (Tương thích rộng)", "PP-OCRv3"),
            ),
        ),
        EngineParameter(
            "model_tier",
            "Cấp độ mô hình",
            "",
            (
                "Mobile/Small ưu tiên tốc độ & nhẹ RAM; "
                "Server/Medium ưu tiên độ chính xác tối đa."
            ),
            choices=(
                ("Tự động theo phiên bản", ""),
                ("Mobile / Small (Nhanh, nhẹ RAM/CPU)", "mobile"),
                ("Server / Medium (Độ chính xác tối đa)", "server"),
                ("Tiny (Siêu nhẹ 1.5M cho máy yếu)", "tiny"),
            ),
        ),
        EngineParameter(
            "det_db_thresh",
            "Ngưỡng phát hiện chữ",
            0.3,
            "Thấp hơn: bắt được chữ mờ nhưng dễ nhiễu; cao hơn: chặt chẽ hơn.",
            minimum=0.05,
            maximum=0.95,
            step=0.05,
        ),
        EngineParameter(
            "rec_model_dir",
            "Model nhận diện tùy chỉnh",
            "",
            "Thư mục model nhận diện PaddleOCR tùy chỉnh (để trống nếu dùng mặc định).",
            choices=(("Mặc định theo phiên bản", ""),),
        ),
    ),
    "trocr": (
        EngineParameter(
            "checkpoint",
            "Biến thể Checkpoint",
            "microsoft/trocr-base-handwritten",
            (
                "Chọn biến thể TrOCR theo kích thước (Small/Base/Large) và loại chữ "
                "(viết tay/chữ in/chữ cảnh) hoặc thư mục cục bộ."
            ),
            choices=(
                (
                    "Base - Chữ viết tay (~334M, Cân bằng)",
                    "microsoft/trocr-base-handwritten",
                ),
                (
                    "Base - Chữ in / Hóa đơn (~334M, Cân bằng)",
                    "microsoft/trocr-base-printed",
                ),
                (
                    "Small - Chữ viết tay (~62M, Nhanh & nhẹ)",
                    "microsoft/trocr-small-handwritten",
                ),
                ("Small - Chữ in (~62M, Nhanh & nhẹ)", "microsoft/trocr-small-printed"),
                (
                    "Large - Chữ viết tay (~558M, Chính xác nhất)",
                    "microsoft/trocr-large-handwritten",
                ),
                (
                    "Large - Chữ in (~558M, Chính xác nhất)",
                    "microsoft/trocr-large-printed",
                ),
                ("Base - Chữ cảnh tự nhiên (Scene Text)", "microsoft/trocr-base-str"),
                ("Large - Chữ cảnh tự nhiên (Scene Text)", "microsoft/trocr-large-str"),
            ),
        ),
        EngineParameter(
            "max_new_tokens",
            "Số token tối đa",
            128,
            "Giới hạn độ dài mỗi dòng nhận diện.",
            minimum=1,
            maximum=512,
            step=16,
        ),
        EngineParameter(
            "timeout_seconds",
            "Thời gian tối đa (giây)",
            30.0,
            "Dừng nếu một dòng xử lý quá lâu.",
            minimum=1,
            maximum=300,
            step=5,
        ),
    ),
    "chandra": (
        EngineParameter(
            "checkpoint",
            "Biến thể Model",
            "datalab-to/chandra",
            (
                "Chọn phiên bản Chandra OCR (v1 hoặc v2 Flagship 5B) "
                "hoặc thư mục model cục bộ."
            ),
            choices=(
                ("Chandra OCR v1 (Bố cục, bảng, viết tay)", "datalab-to/chandra"),
                (
                    "Chandra OCR v2 (Flagship 5B - Chính xác cao nhất)",
                    "datalab-to/chandra-ocr-2",
                ),
            ),
        ),
        EngineParameter(
            "prompt_type",
            "Chế độ trích xuất",
            "ocr_layout",
            (
                "ocr_layout giữ nguyên tọa độ khối, bảng HTML và công thức; "
                "ocr trích xuất nhanh thuần văn bản."
            ),
            choices=(
                ("Bố cục đầy đủ + Bảng + Toán (ocr_layout)", "ocr_layout"),
                ("Thuần văn bản Markdown nhanh (ocr)", "ocr"),
            ),
        ),
        EngineParameter(
            "method",
            "Phương thức chạy",
            "hf",
            "Chạy trực tiếp qua HuggingFace (hf) hoặc máy chủ vLLM cục bộ (vllm).",
            choices=(
                ("HuggingFace (Cục bộ)", "hf"),
                ("vLLM Server (Tốc độ cao)", "vllm"),
            ),
        ),
        EngineParameter(
            "max_new_tokens",
            "Số token tối đa",
            2048,
            "Số lượng token đầu ra tối đa cho mỗi trang.",
            minimum=64,
            maximum=16384,
            step=256,
        ),
    ),
    "dots_ocr": (
        EngineParameter(
            "checkpoint",
            "Biến thể Model",
            "rednote-hilab/dots.ocr",
            (
                "Chọn biến thể dots.ocr (1.7B chuẩn hoặc dots.mocr 1.5 đa tác vụ) "
                "hoặc thư mục cục bộ."
            ),
            choices=(
                ("dots.ocr 1.7B (Bố cục, bảng, công thức)", "rednote-hilab/dots.ocr"),
                ("dots.mocr 1.5 (Đa tác vụ + SVG)", "rednote-hilab/dots.mocr"),
                ("dots-studio/dots.ocr (Chính thức)", "dots-studio/dots.ocr"),
            ),
        ),
        EngineParameter(
            "prompt_mode",
            "Chế độ Prompt",
            "layout_all",
            (
                "layout_all xuất JSON tọa độ + bảng HTML + LaTeX; "
                "ocr xuất văn bản thuần tránh lặp."
            ),
            choices=(
                ("Đầy đủ bố cục + Bảng HTML + LaTeX (layout_all)", "layout_all"),
                ("Thuần văn bản nhanh, chống lặp (ocr)", "ocr"),
            ),
        ),
        EngineParameter(
            "method",
            "Phương thức chạy",
            "hf",
            "Chạy trực tiếp qua HuggingFace (hf) hoặc máy chủ vLLM cục bộ (vllm).",
            choices=(
                ("HuggingFace (Cục bộ)", "hf"),
                ("vLLM Server (Tốc độ cao)", "vllm"),
            ),
        ),
        EngineParameter(
            "max_new_tokens",
            "Số token tối đa",
            4096,
            "Số lượng token đầu ra tối đa cho mỗi trang.",
            minimum=64,
            maximum=24000,
            step=512,
        ),
    ),
}

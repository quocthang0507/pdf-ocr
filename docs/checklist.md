# Bảng Kiểm Tiến Độ Triển Khai (Implementation Checklist)
## Dự Án: Ứng Dụng Desktop OCR Đa Mô Hình & Chuyển Đổi Tài Liệu (PySide6)

> **Phương pháp quản lý:** Tuân thủ chuẩn **Spec-Driven Development**, **Test-Driven Development (TDD: Red-Green-Refactor)**, **Code Review Gates (5 trục đánh giá: Correctness, Readability, Architecture, Security, Performance)**, **Kiến trúc Mở rộng (Provider Pattern)** và **Quản lý Thư mục Model/Weights Tùy Chỉnh**.  
> 
> **Tiêu chuẩn chất lượng dự án (Quality Gates):**
> - **Test Coverage:** Toàn bộ dự án đạt tối thiểu **$\ge 80\%$** (`pytest tests/ --cov=src --cov-report=term-missing`).
> - **Test Markers:** Phân loại rõ ràng qua `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.gui`.
> - **Nguyên tắc Immutability (CRITICAL):** Domain Models bắt buộc dùng `@dataclass(frozen=True)`, không mutate in-place.
> - **Giới hạn mã nguồn:** File tối đa 800 dòng (tiêu chuẩn 200–400 dòng), hàm tối đa 50 dòng, độ lồng nhau tối đa 4 cấp.
> - **Công cụ kiểm định tĩnh:** `ruff check` (linting), `black` & `isort` (format), `mypy` (strict type hints), `bandit` (bảo mật) đạt 0 cảnh báo.
> - **Không dùng `print()`:** 100% sử dụng `logger` (Loguru) với phân cấp ngữ cảnh.
> - **Git Convention:** Quy chuẩn commit `<type>: <description>` (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`).
> - **Quy tắc đánh dấu Checklist (BẮT BUỘC):** Hoàn thành xong task nào thì lập tức đánh dấu `- [x]` cho task đó ngay sau khi vượt qua lệnh kiểm thử tại mục `Verify`. Tuyệt đối không đánh dấu trước và không tích dồn nhiều task.
> - Mỗi task được giới hạn phạm vi tác động $\le 5$ tệp tin, có tiêu chí nghiệm thu rõ ràng và lệnh kiểm thử tự động tương ứng.

---

### Giai Đoạn 1: Thiết Lập Nền Tảng, Quản Lý Weights Tùy Chỉnh & Cấu Trúc Dự Án (Foundation & Weights Manager)

- [x] **Task 1.1: Khởi tạo cấu trúc thư mục & quản lý dependencies**
  - **Mục tiêu:** Tạo toàn bộ cây thư mục chuẩn modularity, thư mục `src/models/` mặc định trong cấu trúc mã nguồn, thư mục `packaging/`, file `requirements.txt` (ghim rõ phiên bản tối thiểu theo Tech Stack), `requirements-dev.txt` (pytest, pytest-cov, pytest-qt, ruff, black, isort, mypy, bandit, pyinstaller), cấu hình `pyproject.toml` (đăng ký test markers `unit`, `integration`, `gui`; threshold coverage 80%; cấu hình ruff, black, mypy, bandit).
  - **Acceptance:** Cài đặt môi trường ảo thành công, thư mục `src/models/` sẵn sàng, `pytest`, `ruff`, `mypy`, `bandit`, `pyinstaller` thực thi chuẩn xác không lỗi cú pháp cấu hình.
  - **Verify:** `python -m pip install -e . && python -m pip install -r requirements-dev.txt; pytest --version; ruff --version; mypy --version; bandit --version; pyinstaller --version`
  - **Files:** `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `.gitignore`, `README.md`

- [x] **Task 1.2: Xây dựng hệ thống cấu hình, ngoại lệ phân cấp & ghi nhật ký (Config, Exceptions & Logger)**
  - **Mục tiêu:** Cài đặt `src/config.py` (`QSettings` + JSON fallback), `src/utils/logger.py` (Loguru ghi xoay vòng, cấm `print()`) và hệ thống ngoại lệ phân cấp chuẩn `src/core/exceptions.py` (`PDFOCRError` làm base class cho `WeightsError`, `OCREngineError`, `ExportError`, `PreprocessingError`, `DocumentLoadError`).
  - **Acceptance:** Lưu và tải Preferences an toàn; ghi log chuẩn ra console và file `logs/app.log`; ngoại lệ bắt đúng loại và mang message thân thiện người dùng.
  - **Verify:** `pytest -m unit tests/unit/test_config.py tests/unit/test_logger.py tests/unit/test_exceptions.py -v`
  - **Files:** `src/config.py`, `src/utils/logger.py`, `src/core/exceptions.py`, `tests/unit/test_config.py`, `tests/unit/test_exceptions.py`

- [x] **Task 1.3: Quản lý thư mục Model & Weights tùy chỉnh (ModelWeightsManager)**
  - **Mục tiêu:** Cài đặt `src/services/weights_manager.py` quản lý đường dẫn lưu trữ weights (mặc định `<app_root>/src/models/`, hỗ trợ tùy chỉnh qua UI), chuyển hướng các biến môi trường cache (`TORCH_HOME`, `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `PADDLE_HOME`, `EASYOCR_MODULE_PATH`), kiểm tra dung lượng ổ đĩa trống, xác thực chống Path Traversal và xử lý ngoại lệ `WeightsError`.
  - **Acceptance:** Biến môi trường được trỏ chuẩn xác về thư mục cấu hình; tính toán dung lượng đĩa trống chuẩn xác; ném `WeightsError` khi thiếu quyền ghi hoặc không đủ dung lượng; không ghi weights vào `~/.cache` ổ C.
  - **Verify:** `pytest -m unit tests/unit/test_weights_manager.py -v`
  - **Files:** `src/services/weights_manager.py`, `src/utils/file_utils.py`, `tests/unit/test_weights_manager.py`

- [x] **Task 1.4: Định nghĩa cấu trúc dữ liệu trung gian bất biến (Immutable Core Data Models)**
  - **Mục tiêu:** Cài đặt các data models cốt lõi tuân thủ triệt để nguyên tắc **Immutability**: `@dataclass(frozen=True)` cho `OCRDocument`, `OCRPage`, `OCRBlock`, `OCRLine`, `OCRWord`, `OCRTable`, `BoundingBox`.
  - **Acceptance:** Không thể gán sửa thuộc tính in-place sau khi khởi tạo; hỗ trợ đầy đủ tọa độ polygon/box, điểm tin cậy (confidence), loại khối (text, title, table, image); hỗ trợ hàm tạo bản sao có cập nhật (functional copy) và chuyển đổi 2 chiều sang `dict` / `json`.
  - **Verify:** `pytest -m unit tests/unit/test_models.py -v`
  - **Files:** `src/core/models.py`, `src/constants.py`, `tests/unit/test_models.py`

**Kết quả nghiệm thu giai đoạn 1 (14/09/2026):**
- Môi trường `.venv` Python 3.12.10 đã cài editable package và toàn bộ `requirements-dev.txt`; `pip check` không có dependency lỗi.
- `python -m pytest tests/ --cov=src --cov-report=term-missing`: **87 passed**, coverage **93,15%** (bao gồm branch coverage), không có test bị bỏ qua.
- `ruff check src/ tests/`, `black --check src/ tests/`, `python -X utf8 -m isort --check-only src/ tests/`, `mypy src/`, `bandit -c pyproject.toml -r src/`: đạt; Bandit không phát hiện vấn đề.
- Build wheel thành công bằng `python -m pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir dist .`.
- Smoke check thực tế xác nhận `logs/app.log`, thư mục mặc định `src/models/` và khởi tạo nền tảng không import các thư viện AI hoặc tải weights.
- Các thư viện OCR nặng được khai báo trong extra `ocr` và `requirements.txt`; tích hợp provider, GUI và đóng gói executable tiếp tục theo các giai đoạn sau.

---

### Giai Đoạn 2: Tiền Xử Lý Ảnh Chuyên Sâu & Tải Tài Liệu (Image Preprocessing & Ingestion)

- [x] **Task 2.1: Bộ nạp tài liệu & chuyển đổi trang (Document Loader)**
  - **Mục tiêu:** Cài đặt `src/core/document_loader.py` sử dụng PyMuPDF để nạp PDF (scanned/vector/text-based), hỗ trợ xuất ảnh trang theo DPI tùy chọn (150/300/600), nạp ảnh định dạng PNG, JPG, TIFF đa trang, BMP. Tích hợp **Input Validation** (kiểm tra PDF mã hóa, kích thước file bounds, page count limits) và ném `DocumentLoadError`. Tích hợp logic phát hiện sơ bộ loại trang PDF (có text layer hay chỉ có ảnh).
  - **Acceptance:** Nạp thành công file PDF nhiều trang và ảnh đơn lẻ; từ chối và báo lỗi rõ ràng khi file bị mã hóa hoặc ảnh hỏng; trả về danh sách đối tượng ảnh NumPy ndarray (RGB) và metadata trang, đánh dấu được trang nào có text layer.
  - **Verify:** `pytest -m unit tests/unit/test_document_loader.py -v`
  - **Files:** `src/core/document_loader.py`, `src/utils/image_utils.py`, `tests/unit/test_document_loader.py`

- [x] **Task 2.2: Tự động phát hiện hướng trang & xoay thẳng (Auto Orientation & Deskew)**
  - **Mục tiêu:** Cài đặt thuật toán nhận diện hướng (0°, 90°, 180°, 270°) và tự động làm thẳng góc nghiêng (-45° đến +45°) bằng Hough Line Transform / MinAreaRect trong `src/core/preprocessor.py`. Validate tính hợp lệ của ảnh đầu vào và ném `PreprocessingError` nếu ảnh corrupt.
  - **Acceptance:** Ảnh nghiêng lệch tự động xoay về thẳng đứng với sai số góc $< 0.5^\circ$; ảnh nằm ngang/lộn ngược tự động xoay về 0°; xử lý an toàn ảnh kích thước bất thường.
  - **Verify:** `pytest -m unit tests/unit/test_deskew.py -v`
  - **Files:** `src/core/preprocessor.py`, `tests/unit/test_deskew.py`

- [x] **Task 2.3: Bộ lọc khử nhiễu, xóa bóng gáy sách & tăng tương phản (Denoise, Shadow Removal & CLAHE)**
  - **Mục tiêu:** Cài đặt xử lý khử nhiễu (`fastNlMeansDenoising`), cân bằng ánh sáng nền bằng toán tử hình thái học (Morphological Closing) và tăng tương phản chữ bằng CLAHE. Ném `PreprocessingError` khi gặp sự cố tính toán kênh màu.
  - **Acceptance:** Ảnh chụp có bóng đổ ở góc/gáy sách được làm sáng đều; chữ mờ nhòe được tăng cường độ sắc nét cạnh viền; không gây méo dạng ký tự.
  - **Verify:** `pytest -m unit tests/unit/test_enhancement.py -v`
  - **Files:** `src/core/preprocessor.py`, `tests/unit/test_enhancement.py`

- [x] **Task 2.4: Nhận diện & cắt bỏ viền đen máy scan (Border Removal)**
  - **Mục tiêu:** Phát hiện các vệt đen, khung đen xung quanh mép giấy do máy quét và tự động cắt sát lề tài liệu.
  - **Acceptance:** Cắt bỏ viền đen không làm mất chữ sát biên trang.
  - **Verify:** `pytest -m unit tests/unit/test_border_removal.py -v`
  - **Files:** `src/core/preprocessor.py`, `tests/unit/test_border_removal.py`

- [x] **Task 2.5: Tự động phân loại PDF & trích xuất text-based (PDF Classifier)**
  - **Mục tiêu:** Cài đặt `src/core/pdf_classifier.py` tự động phân loại từng trang PDF thành 3 loại: `TEXT_BASED` (có text layer đầy đủ), `SCANNED` (chỉ có ảnh), `HYBRID` (hỗn hợp). Với trang text-based, trích xuất text, tọa độ bounding box, font trực tiếp từ PDF text layer bằng PyMuPDF (`page.get_text("dict")`) mà không cần rasterize và OCR.
  - **Acceptance:** Phân loại chính xác 100% trang scanned vs text-based trên bộ mẫu fixture; text trích xuất từ trang text-based khớp 100% bản gốc; tốc độ < 1 giây/trang.
  - **Verify:** `pytest -m unit tests/unit/test_pdf_classifier.py -v`
  - **Files:** `src/core/pdf_classifier.py`, `tests/unit/test_pdf_classifier.py`

**Kết quả nghiệm thu giai đoạn 2 (14/09/2026):**
- Hoàn thành toàn bộ 5/5 tasks của Giai đoạn 2 (`Task 2.1` -> `Task 2.5`).
- `python -m pytest tests/ --cov=src --cov-report=term-missing`: **133 passed**, test coverage đạt **89.68%** (vượt yêu cầu $\ge 80\%$), trong đó:
  - `src/utils/image_utils.py`: **100%**
  - `src/core/document_loader.py`: **85%**
  - `src/core/preprocessor.py`: **85%**
  - `src/core/pdf_classifier.py`: **82%**
- Quality gates nghiêm ngặt:
  - `python -m black --check src/ tests/`: đạt (100% formatted).
  - `python -X utf8 -m isort --check-only src/ tests/`: đạt (100% sorted).
  - `python -m ruff check src/ tests/`: đạt (0 lỗi / 0 cảnh báo).
  - `python -m mypy src/`: đạt (`Success: no issues found in 22 source files`).
  - `python -m bandit -c pyproject.toml -r src/`: đạt (0 security issues identified).
- Thuật toán Deskew xử lý độ nghiêng $\pm 45^\circ$, loại bỏ viền đen scanner, khử nhiễu Non-Local Means, xóa bóng gáy sách bằng Morphological Closing và tăng tương phản bằng CLAHE trên kênh Luminance.
- PDF Classifier phân loại chính xác `TEXT_BASED`, `SCANNED`, `HYBRID` và trích xuất trực tiếp text layer mà không cần rasterize/OCR tốn tài nguyên.

---

### Giai Đoạn 3: Hệ Thống Module OCR Đa Mô Hình & Kiến Trúc Provider Mở Rộng (Extensible Multi-Engine System)

- [x] **Task 3.1: Thiết kế giao diện cơ sở BaseOCREngine, EngineRegistry & Context Manager VRAM**
  - **Mục tiêu:** Cài đặt Abstract Base Class `BaseOCREngine` và `EngineRegistry` với cơ chế đăng ký decorator `@register_engine`. Tích hợp **Context Manager `engine_session`** quản lý vòng đời nạp/giải phóng model, tự động thu hồi VRAM (`torch.cuda.empty_cache()`, `gc.collect()`). Tích hợp schema validation cho tham số cấu hình engine (kiểm tra miền giá trị hợp lệ) và xử lý ngoại lệ `OCREngineError`.
  - **Acceptance:** Cho phép thêm engine mới mà không cần sửa core logic; context manager tự động dọn sạch GPU VRAM sau khi thoát khối `with`; ném `OCREngineError` khi khởi tạo model thất bại; nạp lười (Lazy Loading) thành công.
  - **Verify:** `pytest -m unit tests/unit/test_engine_registry.py -v`
  - **Files:** `src/engines/base_engine.py`, `src/engines/engine_registry.py`, `tests/unit/test_engine_registry.py`

- [x] **Task 3.2: Tích hợp VietOCR Provider (Chuyên sâu tiếng Việt)**
  - **Mục tiêu:** Cài đặt `src/engines/vietocr_engine.py` lưu weights vào `src/models/vietocr/`, hỗ trợ các kiến trúc `vgg_transformer`, `vgg_seq2seq`, cấu hình `device`, nạp model weights an toàn với `OCREngineError` handling.
  - **Acceptance:** Nhận diện chính xác 100% dòng chữ tiếng Việt có dấu phức tạp trong ảnh mẫu fixture; giải phóng VRAM khi hoàn tất.
  - **Verify:** `pytest -m unit tests/unit/test_vietocr_engine.py -v`
  - **Files:** `src/engines/vietocr_engine.py`, `tests/unit/test_vietocr_engine.py`

- [x] **Task 3.3: Tích hợp PaddleOCR Provider (Tốc độ cao & Bảng biểu)**
  - **Mục tiêu:** Cài đặt `src/engines/paddle_engine.py` lưu weights vào `src/models/paddle/`, hỗ trợ Text Detection (DBNet) + Text Recognition (SVTR) và tích hợp PP-Structure phát hiện bảng.
  - **Acceptance:** Trả về bounding box, text và độ tin cậy; nhận diện được các ô trong bảng biểu; ném `OCREngineError` rõ ngữ cảnh khi weights thiếu.
  - **Verify:** `pytest -m unit tests/unit/test_paddle_engine.py -v`
  - **Files:** `src/engines/paddle_engine.py`, `tests/unit/test_paddle_engine.py`

- [x] **Task 3.4: Tích hợp Surya OCR Provider (Đa ngôn ngữ & Thứ tự đọc)**
  - **Mục tiêu:** Cài đặt `src/engines/surya_engine.py` lưu weights vào `src/models/surya/`, hỗ trợ phát hiện văn bản và nhận diện đa ngôn ngữ, hỗ trợ cấu hình danh sách ngôn ngữ (`langs`).
  - **Acceptance:** Nhận diện văn bản đa ngôn ngữ và trả về tọa độ chính xác cho từng dòng.
  - **Verify:** `pytest -m unit tests/unit/test_surya_engine.py -v`
  - **Files:** `src/engines/surya_engine.py`, `tests/unit/test_surya_engine.py`

- [x] **Task 3.5: Tích hợp Transformer OCR / TrOCR Provider (Chữ viết tay & chữ in)**
  - **Mục tiêu:** Cài đặt `src/engines/transformer_engine.py` lưu weights vào `src/models/trocr/`, sử dụng HuggingFace TrOCR (hỗ trợ checkpoint `microsoft/trocr-base-handwritten` và `microsoft/trocr-base-printed`).
  - **Acceptance:** Nhận diện chuẩn xác ảnh mẫu dòng chữ viết tay (Handwriting); xử lý timeout/error an toàn.
  - **Verify:** `pytest -m unit tests/unit/test_transformer_engine.py -v`
  - **Files:** `src/engines/transformer_engine.py`, `tests/unit/test_transformer_engine.py`

- [x] **Task 3.6: Tích hợp EasyOCR Provider (Dự phòng gọn nhẹ)**
  - **Mục tiêu:** Cài đặt `src/engines/easyocr_engine.py` lưu weights vào `src/models/easyocr/`, hỗ trợ đa ngôn ngữ nhanh chóng, độc lập.
  - **Acceptance:** Nhận diện trả về kết quả chuẩn theo chuẩn `OCRPage`.
  - **Verify:** `pytest -m unit tests/unit/test_easyocr_engine.py -v`
  - **Files:** `src/engines/easyocr_engine.py`, `tests/unit/test_easyocr_engine.py`

**Kết quả nghiệm thu giai đoạn 3 (15/09/2026):**
- Hoàn thành toàn bộ 6/6 tasks của Giai đoạn 3 (`Task 3.1` -> `Task 3.6`), với 5 provider được đăng ký tự động nhưng chỉ import framework AI khi `load_model()` được gọi.
- `python -m pytest tests/ --cov=src --cov-report=term-missing`: **154 passed**, coverage **86,39%** (bao gồm branch coverage), không có test bị bỏ qua; riêng Giai đoạn 3 bổ sung **21 unit tests** xác định hành vi.
- Từng lệnh `Verify` của `Task 3.1` -> `Task 3.6` đều đạt; backend nặng được thay bằng test doubles xác định để kiểm tra adapter hoàn toàn offline, không tải model/weights trong unit test. Kiểm định chất lượng OCR bằng weights thật thuộc E2E Giai đoạn 8.
- Quality gates: `black --check src/ tests/`, `isort --check-only src/ tests/`, `ruff check src/ tests/`, `mypy src/`, `bandit -c pyproject.toml -r src/` và `git diff --check` đều đạt; không có lỗi type, lint hay security.
- Registry smoke test xác nhận đủ `vietocr`, `paddle`, `surya`, `trocr`, `easyocr` và không import `torch`/framework OCR khi chỉ nạp package. PaddleOCR tương thích định dạng API 2.x/3.x; Surya tương thích API predictor cũ và `SuryaInferenceManager` mới.
- Tất cả file mới dưới 800 dòng và không có hàm mới vượt 50 dòng; dữ liệu OCR được chuẩn hóa về domain models bất biến, cấu hình được kiểm tra miền giá trị và lỗi backend được bọc bằng `OCREngineError` an toàn.

---

### Giai Đoạn 4: Phân Tích Bố Cục, Bảng Biểu & Hậu Xử Lý Tiếng Việt (Layout, Tables & Post-processing)

- [x] **Task 4.1: Phân tích bố cục đa cột & sắp xếp thứ tự đọc (Reading Order Sorter)**
  - **Mục tiêu:** Cài đặt thuật toán XY-Cut / Topological Sorting phân tích luồng đọc tài liệu nhiều cột (2-3 cột báo/tạp chí) trong `src/core/layout_analyzer.py`.
  - **Acceptance:** Thứ tự các đoạn văn được sắp xếp tự nhiên theo từng cột từ trên xuống dưới, không bị đọc nối ngang giữa 2 cột.
  - **Verify:** `pytest -m unit tests/unit/test_layout_analyzer.py -v`
  - **Files:** `src/core/layout_analyzer.py`, `tests/unit/test_layout_analyzer.py`

- [x] **Task 4.2: Trích xuất ma trận cấu trúc bảng biểu (Table Extractor)**
  - **Mục tiêu:** Cài đặt `src/core/table_extractor.py` kết hợp tọa độ ô phát hiện được từ OCR với văn bản để dựng lưới dữ liệu 2D (hàng, cột, ô gộp).
  - **Acceptance:** Chuyển đổi vùng bảng biểu thành ma trận dữ liệu 2D chính xác, bảo toàn thứ tự dòng và cột.
  - **Verify:** `pytest -m unit tests/unit/test_table_extractor.py -v`
  - **Files:** `src/core/table_extractor.py`, `tests/unit/test_table_extractor.py`

- [x] **Task 4.3: Chuẩn hóa tiếng Việt NFC, Chấm điểm tin cậy & Sửa lỗi chính tả OCR (Postprocessor)**
  - **Mục tiêu:** Cài đặt `src/core/postprocessor.py` chuẩn hóa Unicode NFC, xử lý dấu thanh tiếng Việt kiểu mới/cũ, áp dụng regex sửa lỗi nhầm lẫn OCR phổ biến (`l/1/I`, `0/O`); đánh giá điểm tin cậy (Confidence score 0.0 - 1.0) cho từng từ và gắn cờ các từ $< 80\%$ để phục vụ highlight trên UI.
  - **Acceptance:** Toàn bộ text xuất ra ở chuẩn Unicode NFC; các lỗi nhầm lẫn ký tự cơ bản được tự động khắc phục; cờ cảnh báo tin cậy thấp được thiết lập chính xác trên đối tượng `OCRWord`.
  - **Verify:** `pytest -m unit tests/unit/test_postprocessor.py -v`
  - **Files:** `src/core/postprocessor.py`, `tests/unit/test_postprocessor.py`

- [x] **Task 4.4: Xây dựng Pipeline tích hợp toàn trình & Phục hồi lỗi (Core Pipeline Orchestrator)**
  - **Mục tiêu:** Cài đặt `src/services/pipeline_service.py` kết nối xuyên suốt: DocumentLoader -> **PDFClassifier (phân nhánh tự động)** -> [Trang text-based: trích xuất trực tiếp | Trang scanned: Preprocessor -> LayoutAnalyzer -> OCREngine] -> Postprocessor. Tích hợp Error Boundaries và cơ chế gợi ý engine dự phòng (graceful fallback) khi có lỗi.
  - **Acceptance:** Chạy pipeline với 1 file PDF hỗn hợp (có trang text-based lẫn trang scanned), nhận được đối tượng `OCRDocument` hoàn chỉnh; trang text-based được xử lý nhanh gấp 10 lần so với trang scanned; bắt và bọc lỗi sạch sẽ vào `PDFOCRError`.
  - **Verify:** `pytest -m integration tests/integration/test_pipeline.py -v`
  - **Files:** `src/services/pipeline_service.py`, `tests/integration/test_pipeline.py`

**Kết quả nghiệm thu giai đoạn 4 (15/09/2026):**
- Hoàn thành toàn bộ 4/4 tasks của Giai đoạn 4 (`Task 4.1` -> `Task 4.4`), bổ sung **19 tests** cho layout đa cột, bảng/ô gộp, hậu xử lý tiếng Việt và pipeline tích hợp.
- `pytest --cov=src --cov-report=term-missing`: **173 passed**, coverage **86,44%** (bao gồm branch coverage), không có test bị bỏ qua.
- Từng lệnh `Verify` của `Task 4.1` -> `Task 4.4` đều đạt; integration test dùng PDF hỗn hợp thật và xác nhận trang text-based đi theo fast path, không rasterize, không tiền xử lý và không gọi OCR engine.
- Pipeline duy trì một engine session dùng lại giữa các trang, tự chuyển sang engine dự phòng khi nhận diện lỗi, hợp nhất trang hybrid và bọc lỗi bất ngờ bằng `PDFOCRError` không làm lộ chi tiết nội bộ.
- Quality gates `black`, `isort`, `ruff`, `mypy --strict`, `bandit`, `git diff --check` đều đạt; rà soát 5 trục không còn phát hiện bắt buộc, mọi file dưới 800 dòng và hàm dưới 50 dòng.

---

### Giai Đoạn 5: Bộ Xuất Tài Liệu Đa Định Dạng Mở Rộng (Extensible Multi-Format Exporters)

- [x] **Task 5.1: Thiết kế giao diện BaseExporter, ExporterRegistry & Kiểm tra đường dẫn xuất**
  - **Mục tiêu:** Cài đặt Abstract Base Class `BaseExporter` và `ExporterRegistry` cho phép đăng ký linh hoạt các định dạng xuất mới bằng `@register_exporter`. Tích hợp Input Validation kiểm tra quyền ghi (write permission) và dung lượng đĩa khả dụng của đường dẫn đích, ném `ExportError` khi không đạt.
  - **Acceptance:** Dễ dàng đăng ký thêm các định dạng xuất mới; ném `ExportError` rõ ràng khi phân vùng đầy hoặc không có quyền ghi; không làm crash pipeline.
  - **Verify:** `pytest -m unit tests/unit/test_exporter_registry.py -v`
  - **Files:** `src/exporters/base_exporter.py`, `src/exporters/exporter_registry.py`, `tests/unit/test_exporter_registry.py`

- [x] **Task 5.2: Bộ xuất Searchable PDF (Ctrl + F với Invisible Text Layer)**
  - **Mục tiêu:** Cài đặt `src/exporters/pdf_exporter.py` sử dụng PyMuPDF nhúng lớp chữ vô hình (render mode 3 - invisible text) trùng khớp 100% tọa độ bounding box với ảnh scan gốc.
  - **Acceptance:** File PDF đầu ra giữ nguyên hình ảnh sắc nét gốc, cho phép bôi đen chuột, copy text và tìm kiếm bằng `Ctrl + F` trên Adobe Reader / Chrome.
  - **Verify:** `pytest -m unit tests/unit/test_pdf_exporter.py -v`
  - **Files:** `src/exporters/pdf_exporter.py`, `tests/unit/test_pdf_exporter.py`

- [x] **Task 5.3: Bộ xuất Microsoft Word (.docx) bảo toàn bố cục & bảng biểu**
  - **Mục tiêu:** Cài đặt `src/exporters/docx_exporter.py` sử dụng `python-docx` tái tạo các cấp tiêu đề (H1, H2, H3), đoạn văn canh lề, ngắt trang và bảng biểu định dạng bảng Word.
  - **Acceptance:** File `.docx` mở được trực tiếp trên Microsoft Word / Google Docs, bảng biểu có viền và ô ngăn nắp.
  - **Verify:** `pytest -m unit tests/unit/test_docx_exporter.py -v`
  - **Files:** `src/exporters/docx_exporter.py`, `tests/unit/test_docx_exporter.py`

- [x] **Task 5.4: Bộ xuất Microsoft Excel (.xlsx) cho bảng biểu**
  - **Mục tiêu:** Cài đặt `src/exporters/xlsx_exporter.py` sử dụng `openpyxl` trích xuất toàn bộ bảng phát hiện được thành các Worksheet riêng biệt hoặc nối tiếp.
  - **Acceptance:** File `.xlsx` mở trên Microsoft Excel hiển thị dữ liệu bảng chuẩn xác theo hàng và cột.
  - **Verify:** `pytest -m unit tests/unit/test_xlsx_exporter.py -v`
  - **Files:** `src/exporters/xlsx_exporter.py`, `tests/unit/test_xlsx_exporter.py`

- [x] **Task 5.5: Bộ xuất Markdown (.md), Plain Text (.txt) & JSON**
  - **Mục tiêu:** Cài đặt `src/exporters/text_exporter.py` và `src/exporters/json_exporter.py`.
  - **Acceptance:** Xuất text định dạng Markdown tiêu chuẩn (tiêu đề `#`, bảng Markdown `|---|`) và file JSON chứa tọa độ chi tiết.
  - **Verify:** `pytest -m unit tests/unit/test_text_json_exporters.py -v`
  - **Files:** `src/exporters/text_exporter.py`, `src/exporters/json_exporter.py`, `tests/unit/test_text_json_exporters.py`

**Kết quả nghiệm thu giai đoạn 5 (15/09/2026):**
- Hoàn thành toàn bộ 5/5 tasks của Giai đoạn 5 (`Task 5.1` -> `Task 5.5`), với registry mở rộng cho PDF, DOCX, XLSX, Markdown, plain text và JSON.
- Các bộ xuất dùng ghi tệp nguyên tử, kiểm tra phần mở rộng/quyền ghi/dung lượng đĩa; Excel giữ Unicode, ô gộp, header style và fallback text; JSON giữ đầy đủ tọa độ OCR.
- Từng lệnh Verify của `Task 5.1` -> `Task 5.5` đều đạt; nhóm kiểm thử exporter hiện có **16 passed**.
- Đã render/kiểm tra trực quan output PDF searchable và DOCX; output XLSX được đọc lại bằng `openpyxl` để xác nhận worksheet, merge, style, freeze pane và metadata.

---

### Giai Đoạn 6: Giao Diện Người Dùng PySide6 & Bộ So Sánh Lỗi (Modern PySide6 Desktop GUI)

- [x] **Task 6.1: Cửa sổ chính MainWindow, Thanh Menu Bar, Tool Bar & Error Boundary**
  - **Mục tiêu:** Cài đặt `src/gui/main_window.py`, `src/gui/components/menu_bar.py`, `src/gui/components/tool_bar.py` với các hành động: Mở file, Mở thư mục, Chạy OCR, Xuất file, Phóng to/thu nhỏ, Cài đặt. Tích hợp **GUI Error Boundary** (bắt toàn bộ `PDFOCRError` và exception bất ngờ, hiển thị `QMessageBox` an toàn, ghi log chi tiết, không làm crash GUI), **Drag & Drop** (kéo thả file từ File Explorer), **Recent Files** (menu 10 file gần nhất), **Window State Persistence** (lưu/phục hồi vị trí và bố trí dock bằng `QSettings`).
  - **Acceptance:** Cửa sổ chính khởi chạy mượt mà, đầy đủ menu chuẩn desktop, phím tắt (`Ctrl+O`, `Ctrl+S`, `Ctrl+Q`, `F5`); kéo thả file mở đúng; danh sách Recent Files cập nhật chính xác; đóng mở lại app giữ nguyên layout; khi core ném lỗi thì GUI hiển thị dialog thông báo thân thiện.
  - **Verify:** `pytest -m gui tests/gui/test_main_window.py -v`
  - **Files:** `src/gui/main_window.py`, `src/gui/components/menu_bar.py`, `src/gui/components/tool_bar.py`, `tests/gui/test_main_window.py`

- [x] **Task 6.2: Khung xem trước tài liệu tương tác (Document Canvas - QGraphicsView)**
  - **Mục tiêu:** Cài đặt `src/gui/components/document_canvas.py` hiển thị ảnh trang tài liệu, hỗ trợ Zoom vô cực bằng con lăn chuột, Pan kéo thả, vẽ các hộp Bounding Box nhiều màu theo loại khối (Text, Title, Table).
  - **Acceptance:** Hiển thị ảnh sắc nét, thao tác zoom/pan mượt mà không giật lag, click chọn được bounding box trên ảnh.
  - **Verify:** `pytest -m gui tests/gui/test_document_canvas.py -v`
  - **Files:** `src/gui/components/document_canvas.py`, `tests/gui/test_document_canvas.py`

- [x] **Task 6.3: Bộ so sánh lỗi song song & Trình soạn thảo văn bản (Side-by-Side Verification Editor)**
  - **Mục tiêu:** Cài đặt `src/gui/components/comparison_dock.py` kết nối đồng bộ hai chiều giữa `DocumentCanvas` (ảnh gốc) và `QTextEdit` (văn bản quét):
    1. Click từ bên text -> Canvas tự động zoom/pan đến vùng ảnh gốc tương ứng.
    2. Click bounding box trên Canvas -> Con trỏ text nhảy đến vị trí từ tương ứng.
    3. Tự động tô màu nền vàng nhạt các từ có điểm tin cậy thấp (<80%).
    4. Hỗ trợ đầy đủ Undo/Redo (`Ctrl+Z` / `Ctrl+Y`).
  - **Acceptance:** Thao tác đồng bộ phản hồi tức thì ($< 100\text{ ms}$), hỗ trợ người dùng chỉnh sửa trực tiếp nội dung văn bản với Undo/Redo mượt mà.
  - **Verify:** `pytest -m gui tests/gui/test_comparison_dock.py -v`
  - **Files:** `src/gui/components/comparison_dock.py`, `tests/gui/test_comparison_dock.py`

- [x] **Task 6.4: Hộp thoại Cài Đặt Toàn Diện & Quản Lý Weights (Settings Dialog)**
  - **Mục tiêu:** Cài đặt `src/gui/dialogs/settings_dialog.py` cho phép người dùng:
    1. Chọn thư mục lưu Model & Weights tùy chỉnh (có nút Duyệt, validate đường dẫn chống Path Traversal và hiển thị dung lượng đĩa trống).
    2. Nút "Di chuyển Weights sang thư mục mới" với thanh tiến trình copy file.
    3. Chọn thiết bị thực thi (`Tự động phát hiện`, `CPU`, `CUDA GPU`), kèm **dò khả năng GPU** (CUDA khả dụng, tên thiết bị, VRAM) và cảnh báo rõ ràng khi máy không có GPU.
    4. Cấu hình thư mục Input/Output mặc định.
  - **Acceptance:** Thay đổi thư mục weights lập tức áp dụng qua `ModelWeightsManager` và lưu bền vững vào `ConfigManager`; kiểm tra dung lượng ổ đĩa khả dụng trước khi áp dụng.
  - **Verify:** `pytest -m gui tests/gui/test_settings_dialog.py -v`
  - **Files:** `src/gui/dialogs/settings_dialog.py`, `src/gui/components/settings_dock.py`, `tests/gui/test_settings_dialog.py`

- [x] **Task 6.5: Hộp thoại chỉnh sửa bảng biểu tương tác (Table Editor Dialog)**
  - **Mục tiêu:** Cài đặt `src/gui/dialogs/table_editor.py` hiển thị cấu trúc bảng dưới dạng lưới `QTableWidget`, cho phép người dùng sửa text từng ô, thêm/xóa dòng cột trước khi xuất ra Excel.
  - **Acceptance:** Cho phép sửa trực tiếp dữ liệu bảng và đồng bộ lại vào dữ liệu trang của `OCRDocument`.
  - **Verify:** `pytest -m gui tests/gui/test_table_editor.py -v`
  - **Files:** `src/gui/dialogs/table_editor.py`, `tests/gui/test_table_editor.py`

- [x] **Task 6.6: Hệ thống Theme giao diện hiện đại (Dark & Light Themes)**
  - **Mục tiêu:** Xây dựng `src/gui/styles/dark_theme.qss` và `light_theme.qss` với ngôn ngữ thiết kế hiện đại, chuyên nghiệp: bảng màu và thang khoảng cách nhất quán, bo góc tinh tế, trạng thái hover/focus/disabled rõ ràng, độ tương phản văn bản đạt chuẩn WCAG AA, chuyển đổi theme tức thì (Sáng / Tối / Theo hệ thống).
  - **Acceptance:** Giao diện hiển thị chuyên nghiệp, không lỗi vỡ style khi chuyển đổi giữa chế độ Dark và Light.
  - **Verify:** `pytest -m gui tests/gui/test_theme_manager.py -v`
  - **Files:** `src/gui/styles/dark_theme.qss`, `src/gui/styles/light_theme.qss`, `src/gui/styles/style_manager.py`, `tests/gui/test_theme_manager.py`

- [x] **Task 6.7: Hộp thoại tải Model Weights với Retry & SHA256 (Download Progress Dialog)**
  - **Mục tiêu:** Cài đặt `src/gui/dialogs/download_dialog.py` hiển thị thanh tiến trình % tải, tốc độ mạng (KB/s, MB/s), thời gian ước tính còn lại, nút Hủy tải an toàn. Tích hợp cơ chế tự động thử lại 3 lần (exponential backoff) khi mạng chập chờn. Sau khi tải xong, xác minh tính toàn vẹn file bằng mã băm SHA256 trước khi lưu.
  - **Acceptance:** Tải model hiển thị % chính xác; tự phục hồi khi mạng gián đoạn nhẹ; hủy giữa chừng không corrupt file weights; báo lỗi rõ ràng khi không có Internet.
  - **Verify:** `pytest -m gui tests/gui/test_download_dialog.py -v`
  - **Files:** `src/gui/dialogs/download_dialog.py`, `src/services/weights_manager.py`, `tests/gui/test_download_dialog.py`

- [x] **Task 6.8: Chọn vùng OCR trên ảnh (Region Selection)**
  - **Mục tiêu:** Bổ sung chế độ vẽ hình chữ nhật trên `DocumentCanvas` cho phép người dùng chọn một vùng cụ thể trên trang để chỉ OCR vùng đó thay vì toàn bộ trang. Kết quả OCR vùng chọn hiển thị ngay trong Bộ so sánh lỗi.
  - **Acceptance:** Vẽ vùng chọn mượt mà, OCR chỉ chạy trên vùng đã chọn, kết quả hiển thị chính xác.
  - **Verify:** `pytest -m gui tests/gui/test_region_selection.py -v`
  - **Files:** `src/gui/components/document_canvas.py`, `tests/gui/test_region_selection.py`

- [x] **Task 6.9: Find & Replace trong Bộ so sánh lỗi**
  - **Mục tiêu:** Cài đặt `src/gui/dialogs/find_replace.py` cung cấp hộp thoại `Ctrl+H` cho phép tìm kiếm và thay thế hàng loạt lỗi OCR lặp lại trong trình soạn thảo văn bản (ví dụ: thay tất cả `đuợc` thành `được`).
  - **Acceptance:** Find & Replace hoạt động chuẩn: tìm đúng, thay thế đúng, hỗ trợ Replace All; tích hợp Undo/Redo.
  - **Verify:** `pytest -m gui tests/gui/test_find_replace.py -v`
  - **Files:** `src/gui/dialogs/find_replace.py`, `src/gui/components/comparison_dock.py`, `tests/gui/test_find_replace.py`

- [x] **Task 6.10: Kho cấu hình SQLite của ứng dụng (Application Settings Database)**
  - **Mục tiêu:** Bổ sung `src/services/settings_store.py` dùng **SQLite** (thư viện chuẩn `sqlite3`) đặt trong thư mục ứng dụng để lưu cài đặt, tham số engine, lịch sử tệp và thông số phiên làm việc. `ConfigManager` đọc/ghi SQLite làm **nguồn chính**, vẫn xuất bản sao JSON để tương thích ngược và cho người dùng xem; tự nạp dữ liệu JSON cũ vào cơ sở dữ liệu ở lần chạy đầu.
  - **Acceptance:** Cài đặt lưu bền vững qua các lần khởi động; cấu hình JSON cũ được di chuyển sang SQLite không mất dữ liệu; ghi dữ liệu là giao dịch nguyên tử, hỏng tệp cơ sở dữ liệu vẫn không làm sập ứng dụng; câu lệnh SQL luôn tham số hóa.
  - **Verify:** `pytest -m unit tests/unit/test_settings_store.py -v`
  - **Files:** `src/services/settings_store.py`, `src/config.py`, `tests/unit/test_settings_store.py`

- [x] **Task 6.11: Hệ thống thông báo tùy chỉnh trong ứng dụng (Custom Toast Notifications)**
  - **Mục tiêu:** Cài đặt `src/gui/components/notifications.py` cung cấp thông báo toast bốn cấp (thành công, thông tin, cảnh báo, lỗi): hiện ở góc cửa sổ, tự ẩn sau thời gian cấu hình, xếp chồng nhiều thông báo, có nút đóng và không chặn thao tác người dùng. Thay các `QMessageBox` không bắt buộc bằng toast; chỉ giữ hộp thoại chặn cho lỗi nghiêm trọng cần người dùng xác nhận.
  - **Acceptance:** Thông báo hiển thị đúng cấp độ và màu sắc theo theme, tự ẩn đúng thời gian, nhiều thông báo không đè lên nhau, đóng ứng dụng khi còn toast không gây lỗi.
  - **Verify:** `pytest -m gui tests/gui/test_notifications.py -v`
  - **Files:** `src/gui/components/notifications.py`, `src/gui/main_window.py`, `tests/gui/test_notifications.py`

- [x] **Task 6.12: Đa ngôn ngữ giao diện Việt - Anh (Interface Localization)**
  - **Mục tiêu:** Cài đặt `src/gui/i18n.py` quản lý `QTranslator`, bảng ngôn ngữ khả dụng và ngôn ngữ mặc định (tiếng Việt). Đưa chuỗi hiển thị của giao diện qua cơ chế dịch, bổ sung mục chọn ngôn ngữ trong Hộp thoại Cài đặt và lưu lựa chọn vào kho cấu hình.
  - **Acceptance:** Đổi ngôn ngữ trong Cài đặt áp dụng ngay cho giao diện đang mở; khởi động lại vẫn giữ đúng ngôn ngữ đã chọn; thiếu tệp dịch thì lùi về tiếng Việt thay vì báo lỗi.
  - **Verify:** `pytest -m gui tests/gui/test_i18n.py -v`
  - **Files:** `src/gui/i18n.py`, `src/gui/dialogs/settings_dialog.py`, `tests/gui/test_i18n.py`

- [x] **Task 6.13: Nối đầy đủ chức năng vào cửa sổ chính (Main Window Wiring)**
  - **Mục tiêu:** Mỗi tài liệu có một `DocumentSession` (`src/gui/document_session.py`) giữ trang đã render (bộ đệm nhỏ), kết quả OCR theo trang và trang hiện tại. Kết quả hiển thị ngay bên cạnh trang ở đúng hệ tọa độ; chỉnh sửa trong Bộ so sánh lỗi được gộp ngược vào mô hình trang (`src/core/transcript.py`) để tệp xuất có nội dung đã sửa. Lệnh Xuất tài liệu mở hộp thoại lưu với mọi định dạng đã đăng ký và ghi tệp dưới nền (`src/workers/export_worker.py`). Mở thư mục chạy hàng loạt mọi tài liệu hỗ trợ, bỏ qua tệp hỏng khi xem trước. Chọn vùng OCR lấy lớp chữ PDF nếu có, nếu không thì nhận diện vùng cắt dưới nền (`src/workers/region_worker.py`). Đóng cửa sổ khi đang chạy hàng loạt sẽ hủy và chờ trang đang xử lý.
  - **Acceptance:** Mở tệp thấy ngay trang và chuyển trang được (PgUp/PgDn); OCR xong thấy văn bản và khung khối; sửa văn bản rồi xuất thì tệp chứa nội dung đã sửa; xuất lỗi báo thông báo thân thiện; thư mục trống hoặc tệp hỏng không làm dừng ứng dụng; đóng cửa sổ giữa chừng không gây lỗi.
  - **Verify:** `pytest tests/gui/test_main_window.py tests/unit/test_document_session.py tests/unit/test_transcript.py tests/unit/test_export_worker.py tests/unit/test_region_worker.py -v`
  - **Files:** `src/gui/main_window.py`, `src/gui/document_session.py`, `src/core/transcript.py`, `src/workers/export_worker.py`, `src/workers/region_worker.py`, `src/gui/components/comparison_dock.py`, `tests/gui/test_main_window.py`, `tests/unit/test_document_session.py`, `tests/unit/test_transcript.py`, `tests/unit/test_export_worker.py`, `tests/unit/test_region_worker.py`

- [x] **Task 6.14: Hoàn thiện chi tiết giao diện (UI Polish)**
  - **Mục tiêu:** Bổ sung biểu tượng SVG cho checkbox đã chọn, nút tăng/giảm và mũi tên ô chọn ở cả hai theme (`src/gui/styles/icons`, đường dẫn được `StyleManager` điền lúc nạp theme); nút mặc định khi vô hiệu trông giống nút vô hiệu thường; khung kết quả vùng chọn có tiêu đề, nút Sao chép và giới hạn chiều cao; chữ trong toast không bị viền khung; toast không che thanh trạng thái; nhãn nút hộp thoại chuẩn bằng tiếng Việt; mọi lệnh có bản dịch tiếng Anh.
  - **Acceptance:** Ảnh chụp giao diện sáng và tối với tệp PDF thật hiển thị đúng dấu tích, mũi tên, trạng thái nút và thông báo; mọi ảnh mà theme dùng đều tồn tại khi đóng gói.
  - **Verify:** `pytest tests/gui/test_theme_manager.py tests/gui/test_notifications.py tests/gui/test_region_selection.py tests/gui/test_i18n.py -v`
  - **Files:** `src/gui/styles/*.qss`, `src/gui/styles/icons/*.svg`, `src/gui/styles/style_manager.py`, `src/gui/components/notifications.py`, `src/gui/i18n.py`, `packaging/pdf-ocr.spec`, `pyproject.toml`

---

### Giai Đoạn 7: Xử Lý Đa Luồng & Quét Hàng Loạt (Batch Processing & Concurrency)

- [x] **Task 7.1: Quản lý hàng đợi tác vụ nền (QThreadPool & OCRWorker)**
  - **Mục tiêu:** Cài đặt `src/workers/ocr_worker.py` (kế thừa `QRunnable`) và `src/workers/batch_manager.py` xử lý tuần tự hoặc song song nhiều trang tài liệu mà không làm đơ giao diện chính.
  - **Acceptance:** Xử lý file PDF lớn (50-100 trang) hoàn toàn dưới nền; GUI duy trì phản hồi 60 FPS.
  - **Verify:** `pytest -m unit tests/unit/test_batch_manager.py -v`
  - **Files:** `src/workers/ocr_worker.py`, `src/workers/batch_manager.py`, `src/workers/signals.py`, `tests/unit/test_batch_manager.py`

- [x] **Task 7.2: Giám sát tiến độ, ước tính thời gian (ETA) & Tạm dừng/Hủy bỏ**
  - **Mục tiêu:** Cài đặt các tính năng điều khiển an toàn: Tạm dừng (Pause), Tiếp tục (Resume), Hủy bỏ (Cancel) trên thanh StatusBar và hộp thoại Batch Dialog.
  - **Acceptance:** Nút Pause dừng nhận trang mới ngay lập tức; Cancel hủy an toàn mà không làm crash ứng dụng; tính toán chính xác % tiến độ và ETA.
  - **Verify:** `pytest -m gui tests/gui/test_batch_dialog.py -v`
  - **Files:** `src/gui/dialogs/batch_dialog.py`, `src/gui/components/status_bar.py`, `tests/gui/test_batch_dialog.py`

- [x] **Task 7.3: Quản lý rò rỉ bộ nhớ & Thu hồi tài nguyên GPU (Memory Hygiene & engine_session)**
  - **Mục tiêu:** Kết nối với context manager `engine_session` để tự động thu hồi VRAM sau mỗi trang; kích hoạt garbage collection (`gc.collect()`) và giải phóng bộ nhớ đệm PyTorch (`torch.cuda.empty_cache()`).
  - **Acceptance:** Xử lý liên tục 100 trang PDF không làm tăng vọt mức tiêu thụ RAM/VRAM; không để sót dangling tensors trên GPU.
  - **Verify:** `pytest -m integration tests/integration/test_memory_leak.py -v`
  - **Files:** `src/workers/ocr_worker.py`, `src/services/pipeline_service.py`, `tests/integration/test_memory_leak.py`

---

### Giai Đoạn 8: Kiểm Thử Toàn Trình, Đóng Gói & Nghiệm Thu (E2E Verification & Release)

- [x] **Task 8.1: Xây dựng bộ dữ liệu mẫu kiểm nghiệm (Test Fixtures & E2E Suite)**
  - **Mục tiêu:** Thu thập các tài liệu mẫu thực tế: PDF scan tiếng Việt có dấu, tài liệu nhiều cột báo, bảng biểu hóa đơn, ảnh chữ viết tay, ảnh bị xoay nghiêng/bóng đổ.
  - **Acceptance:** Bộ kiểm thử E2E chạy tự động trên toàn bộ các mẫu fixture và kiểm tra đầu ra cho tất cả các định dạng xuất.
  - **Verify:** `pytest -m integration tests/integration/test_e2e.py -v`
  - **Files:** `tests/fixtures/*`, `tests/integration/test_e2e.py`

- [x] **Task 8.2: Rà soát mã nguồn toàn diện theo 5 Trục (5-Axis Code Review Audit)**
  - **Mục tiêu:** Thực hiện kiểm tra toàn diện chất lượng code: Correctness (đạt 100% spec), Readability (hàm $\le 50$ dòng, file $\le 800$ dòng, nesting $\le 4$, không có `print()`, immutability frozen dataclasses), Architecture (Provider pattern, layer separation), Security (`bandit` 0 lỗ hổng, path traversal prevention), Performance (Lazy Loading, zero UI freeze); Test Coverage $\ge 80\%$.
  - **Acceptance:** `ruff check src/` đạt 0 lỗi, `black --check src/` và `isort --check src/` chuẩn format, `mypy src/` đạt 0 lỗi, `bandit -r src/` đạt 0 cảnh báo, độ phủ test $\ge 80\%$, dọn dẹp 100% dead code/unused imports.
  - **Verify:** `pytest tests/ --cov=src --cov-report=term-missing && ruff check src/ && black --check src/ && isort --check src/ && mypy src/ && bandit -r src/`
  - **Files:** Toàn bộ repository

- [x] **Task 8.3: Hoàn thiện Sổ tay Hướng dẫn Sử Dụng (User Guide & Docs)**
  - **Mục tiêu:** Soạn thảo `docs/user_guide.md` chi tiết với hình ảnh minh họa cách sử dụng từng tính năng, cách cấu hình lưu weights vào ổ cứng ngoài, phím tắt và mẹo tối ưu hóa nhận diện.
  - **Acceptance:** Tài liệu đầy đủ, dễ hiểu, hướng dẫn chi tiết từ cài đặt đến xuất file.
  - **Verify:** Kiểm tra tính đầy đủ của file `docs/user_guide.md`
  - **Files:** `docs/user_guide.md`

- [x] **Task 8.4: Đóng gói ứng dụng Portable bằng PyInstaller & Chạy Offline trên máy khác**
  - **Mục tiêu:** Cài đặt file cấu hình `packaging/pdf-ocr.spec` và kịch bản đóng gói `packaging/build_portable.py` sử dụng PyInstaller (chế độ Onedir). Tích hợp cơ chế phát hiện môi trường `sys.frozen` để ứng dụng tự động nhận diện thư mục `src/models/` (hoặc `models/`) đi kèm trong bundle phân phối.
  - **Acceptance:** Tạo thành công gói ứng dụng độc lập trong thư mục `dist/pdf-ocr/` chứa `pdf-ocr.exe`; khi sao chép thư mục bundle này kèm theo thư mục weights sang máy tính khác (máy trắng không cài Python, không có Internet), ứng dụng khởi động thành công, nhận diện được weights cục bộ và thực hiện OCR offline 100%.
  - **Verify:** `pyinstaller packaging/pdf-ocr.spec --noconfirm`
  - **Files:** `packaging/pdf-ocr.spec`, `packaging/build_portable.py`, `src/services/weights_manager.py`

- [x] **Task 8.5: Kiểm định Quy trình Git & Chuẩn bị Phát hành (Git Workflow & Release Preparation)**
  - **Mục tiêu:** Rà soát toàn bộ lịch sử commit tuân thủ Conventional Commits (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`), chuẩn bị PR hoàn chỉnh kèm test plan và release notes.
  - **Acceptance:** 100% commit messages tuân thủ định dạng; không có commit trực tiếp vào `main`; toàn bộ test và linters đều xanh trên CI/local.
  - **Verify:** `git log --oneline -n 20`
  - **Files:** `README.md`, `docs/checklist.md`

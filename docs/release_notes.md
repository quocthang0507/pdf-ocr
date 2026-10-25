# Ghi Chú Phát Hành

## v0.3.0 — Đồng Bộ Trực Tiếp Cài Đặt 6 Danh Mục, Mở Khóa PDF Bảo Mật, Lưu Phiên OCR, Dấu Thanh Tiếng Việt, Xuất Hàng Loạt & Benchmark Định Lượng

### Điểm nổi bật

**1. Kết nối trực tiếp toàn bộ 18 tùy chọn trong 6 danh mục Cài đặt (`Preferences` Live Wiring)**
- Mọi thay đổi trong `SettingsDialog` (`Ctrl+,`) được áp dụng tức thì qua tín hiệu `preferences_applied` tới `MainWindow`, `SettingsDock`, `NavigationDock`, `DocumentSession`, `ComparisonDock`, `BatchManager` và `PDFExporter`.
- Đồng bộ tự động mô hình OCR mặc định, DPI, các bước tiền xử lý, chế độ màu trang đọc (`normal` / `sepia` / `night`), thu phóng mặc định (`fit_page` / `fit_width` / `actual_size`), kích thước bộ nhớ đệm trang (`cache_size_pages`), số luồng xử lý song song (`max_worker_threads`), tự động chạy OCR khi mở PDF scan (`auto_ocr_on_open`), xác nhận xóa trang PDF (`confirm_page_delete`), và mức nén PDF xuất ra (`fast` / `balanced` / `max`).

**2. Mở khóa PDF bảo mật AES-256 & Lưu phiên nhận diện tự động (`OCRSessionStore`)**
- `DocumentLoader` hỗ trợ mở khóa tệp PDF được mã hóa mật khẩu (`PasswordRequiredError` + hộp thoại nhập mật khẩu trên giao diện).
- Tự động lưu và khôi phục kết quả `OCRPage` đã nhận diện/chỉnh sửa trong SQLite (`SettingsStore`) theo dấu vân tay của tệp gốc (`path`, `size`, `mtime_ns`), giúp đóng mở lại tài liệu hàng trăm trang không cần chạy lại OCR.

**3. Tùy chọn kiểu dấu thanh tiếng Việt (`tone_style`), Từ điển cá nhân & Ngưỡng tin cậy động**
- Hỗ trợ 3 kiểu đặt dấu thanh tiếng Việt trên `oa, oe, uy`: **Kiểu mới** (`hoà, thuý, khoẻ`), **Truyền thống — Nghị định 30** (`hòa, thúy, khỏe`, tự động giữ nguyên `quý, hoàng, toàn`), và **Giữ nguyên**.
- `VietnameseSpellCorrector` nạp từ điển cá nhân (`custom_dictionary`) hỗ trợ cả danh sách từ bảo vệ chuyên ngành và quy tắc thay thế nhanh `sai => đúng` / `sai -> đúng`.
- `ComparisonDock` cập nhật tức thì danh sách từ nghi ngờ tô vàng khi người dùng thay đổi `confidence_threshold`.

**4. Bộ nhớ đệm Thumbnail, Menu ngữ cảnh vùng chọn & Xuất hàng loạt (`Batch Export`)**
- Lưu đệm `QIcon` thumbnail theo trang, góc xoay và chế độ màu kèm tải lười khi cuộn cho tài liệu lớn.
- Menu chuột phải trực tiếp trên vùng chọn của `DocumentCanvas`: nhận dạng lại vùng chọn, sao chép ảnh vùng chọn vào bộ nhớ tạm, tô sáng (Highlight), che mật (Redact) hoặc mở Bộ công cụ PDF.
- Nút **`Xuất tất cả…`** trong `BatchDialog` cho phép xuất toàn bộ các tài liệu đã nhận diện trong hàng loạt ra thư mục đích chỉ với 1 cú nhấp chuột.

**5. Bộ đo kiểm chất lượng OCR định lượng (`src/services/benchmark_service.py`)**
- Cung cấp hàm tính `CER` (Character Error Rate), `CAR` (Character Accuracy Rate), `WER` (Word Error Rate) chuẩn hóa Unicode NFC và xuất báo cáo Markdown/JSON nghiệm thu `SC-3` và `SC-4`.

**6. Nâng cấp tách dòng/đoạn tiếng Việt, khử bóng đổ khi Deskew, giao diện & thư mục Weights**
- `segment_lines`: gộp dải dấu tiếng Việt bị tách rời về đúng dòng chữ và tách các dòng sát nhau do khoảng cách dòng hẹp.
- `LayoutAnalyzer`: đánh giá ngắt đoạn theo nhịp dòng trên trang, giữ riêng các dòng in hoa toàn bộ, ghép các hộp từ cùng hàng và tăng độ chính xác tách cột.
- `Preprocessor` & `TrOCR`: làm phẳng ánh sáng không đều trước khi nhị phân hóa để tránh xoay nhầm 90° trên trang có bóng đổ; lặp biên (`BORDER_REPLICATE`) khi làm thẳng ảnh; cắt dòng dài tại khoảng trắng từ cho TrOCR.
- `VietnameseSpellCorrector`: tự động khôi phục chữ hoa đầu câu sau dấu chấm và viết hoa họ người Việt phổ biến (`Nguyễn`, `Trần`, `Phạm`...).
- Giao diện & thư mục `weights`: vẽ biểu tượng SVG thanh công cụ theo đúng màu chủ đề hiện hành; cố định chiều rộng `QComboBox` trong `SettingsDock`; giữ nguyên thư mục weights tùy chỉnh khi khởi động và cập nhật trực tiếp bộ nhớ đệm `HuggingFace` / `PaddleX` ngay trong phiên chạy.

---

## v0.2.0 — Nâng cấp Trình đọc PDF Chuyên nghiệp, 7 Mô hình OCR Đa Biến Thể, Sửa Chính Tả Tiếng Việt N-gram & HiDPI


### Điểm nổi bật

**1. Mở rộng lên 7 Mô hình OCR kèm đầy đủ Biến thể & Trọng số tùy chỉnh**
- **PaddleOCR nâng cấp toàn diện:** hỗ trợ chọn phiên bản `PP-OCRv6`, `PP-OCRv5`, `PP-OCRv4`, `PP-OCRv3`; chế độ pipeline `ocr` (tiêu chuẩn), `pp_structure_v3` (phân tích bố cục & bảng biểu nâng cao), và `paddleocr_vl` (Vision-Language 0.9B cho bảng/công thức phức tạp); hạng mô hình `mobile` / `server` / `tiny`; và 8 ngôn ngữ (`vi`, `en`, `latin`, `ch`, `japan`, `korean`, `fr`, `german`).
- **Tích hợp Chandra OCR & dots.ocr:** bổ sung `ChandraOCREngine` (`datalab-to/chandra` v1, `datalab-to/chandra-ocr-2` 5B flagship, chế độ `ocr_layout` / `ocr`, backend `hf` / `vllm`) và `DotsOCREngine` (`rednote-hilab/dots.ocr` 1.7B, `rednote-hilab/dots.mocr` 1.5, `dots-studio/dots.ocr`).
- **Đa biến thể cho VietOCR, TrOCR & EasyOCR:** chọn trực tiếp `vgg_transformer` / `vgg_seq2seq` / `resnet_transformer` (VietOCR); `small` / `base` / `large` cho Handwritten, Printed và Scene Text `str` (TrOCR); mạng nhận diện `latin_g2` / `english_g2` / `latin_g1` và mạng phát hiện `craft` / `dbnet18` (EasyOCR).
- **Nhập model tùy chỉnh linh hoạt:** nạp trực tiếp tệp trọng số `.pth`, `.pdparams` hoặc thư mục checkpoint từ hộp thoại Cài đặt hoặc ngay trong ô chọn biến thể của từng engine.

**2. Không gian đọc PDF & Soát lỗi OCR chuyên nghiệp**
- **Khung Điều hướng bên trái (`NavigationDock`):** thẻ thông tin tài liệu (tên tệp, số trang, dung lượng, bộ đếm `Đã OCR: X/Y trang`, nút **OCR trang hiện tại**), cùng 3 tab: **Trang** (kèm huy hiệu `✓ Đã OCR` / `○ Chưa OCR`), **Mục lục** (cây Bookmarks/Outline của PDF) và **Tìm kiếm** toàn văn xuyên suốt các trang.
- **Điều khiển trang & hiển thị nâng cao:** nút **Vừa trang**, **Vừa ngang** (`fit_width`), xoay trang 90° (`↺` / `↻`), lăn chuột tự chuyển trang khi chạm biên đầu/cuối và `Ctrl + Lăn chuột` để thu phóng tại con trỏ.
- **Điều hướng từ nghi ngờ & Ép buộc OCR:** nút **`◀ Từ nghi ngờ` / `Từ nghi ngờ ▶`** giúp nhảy qua từng từ có độ tin cậy thấp (`< 80%`); tùy chọn **Ép buộc OCR (`force_ocr`)** cho phép bỏ qua lớp chữ gốc bị lỗi font/bảng mã của PDF.

**3. Sửa lỗi chính tả & dấu tiếng Việt theo ngữ cảnh N-gram (`VietnameseSpellCorrector`)**
- Xây dựng bộ sửa lỗi chính tả tiếng Việt hậu OCR (`src/core/spell_corrector.py`) kết hợp ngữ cảnh cụm từ 1/2/3-gram và từ điển âm tiết tiếng Việt (tự động tích hợp `SymSpell` nếu có).
- Khắc phục chính xác các lỗi nhầm dấu thanh và mũ nguyên âm phổ biến (`đưạc` → `được`, `cấp dưởi` → `cấp dưới`, `gổm` → `gồm`, `tổ chửc` → `tổ chức`, `không ngửng đổi mởi` → `không ngừng đổi mới`, `nhan vien` → `nhân viên`, `thuong hiệu tiếp can` → `thương hiệu tiếp cận`, `rộng hon` → `rộng hơn`).
- Tự động nhận diện và **bảo vệ** từ hợp lệ: số, phần trăm, ngày tháng, email, số điện thoại Việt Nam và tên riêng viết hoa (`Np`).
- Bổ sung thuật toán chiếu ngang/dọc (`projection_by_bboxes`, `split_projection_profile`, `merge_overlapping_boxes`) trong `src/core/layout_analyzer.py` giúp tách dòng/cột sạch hơn trước khi nhận diện.
- Có thể bật tự động trong pipeline hoặc bấm nút **`Sửa chính tả`** 1 chạm trên thanh công cụ so sánh (hỗ trợ `Ctrl+Z`).

**4. Tương thích hoàn hảo màn hình HiDPI (125%, 150%, 200%, 4K)**
- Kích hoạt `HighDpiScaleFactorRoundingPolicy.PassThrough` trước khi khởi tạo `QApplication`.
- Dựng biểu tượng thanh công cụ đa độ phân giải (`1x` và `2x` `devicePixelRatio`) sắc nét trên màn hình Retina/4K.
- Loại bỏ các giới hạn kích thước cứng gây cắt chữ tiếng Việt ở tỷ lệ phóng đại cao; chia thanh điều hướng ảnh thành 2 hàng gọn gàng kèm khoảng đệm an toàn ở mọi góc cửa sổ.

### Chất lượng mã nguồn (v0.2.0)

| Chỉ số | Kết quả |
| :-- | :-- |
| Kiểm thử | 600+ xanh (unit, integration, gui) |
| Độ phủ | ~90% (ngưỡng 80%) |
| `ruff`, `black`, `isort` | 0 lỗi |
| `mypy --strict` | 0 lỗi trên 71 tệp |
| `bandit` | 0 cảnh báo |
| Hàm dài nhất | ≤ 50 dòng (giới hạn 50) |
| Tệp dài nhất | ≤ 800 dòng (giới hạn 800) |
| `print()` trong `src/` | 0 |

---

## v0.1.0 — Bản hoàn chỉnh đầu tiên

Hoàn tất toàn bộ 8 giai đoạn của [kế hoạch triển khai](implementation_plan.md): từ nền tảng
domain đến ứng dụng desktop đóng gói được, chạy ngoại tuyến trên Windows, macOS và Linux.

### Điểm nổi bật

**Giao diện desktop hoàn chỉnh**
Cửa sổ chính với menu, thanh công cụ, kéo thả tệp, 10 tệp gần đây và ghi nhớ bố trí cửa sổ.
Bộ so sánh lỗi song song đồng bộ hai chiều giữa ảnh gốc và văn bản: đặt con trỏ trong văn bản
thì ảnh cuộn tới đúng khối, bấm khung trên ảnh thì con trỏ nhảy tới đoạn tương ứng. Những từ
mô hình không chắc chắn được tô vàng để soát trước.

**Xử lý nền không làm đơ giao diện**
Mỗi trang là một tác vụ trên `QThreadPool`. Tạm dừng, tiếp tục và hủy đều an toàn; một trang
lỗi không làm dừng cả lượt quét; phần trăm và thời gian còn lại được ước tính theo tốc độ thực
tế. Bộ nhớ RAM và VRAM được thu hồi sau **mỗi trang**, nên quét 100 trang liên tục không làm
ứng dụng phình bộ nhớ, trong khi mô hình chỉ nạp một lần cho cả lượt.

**Quản lý mô hình an toàn**
Thư mục weights tùy chỉnh được, kể cả trên ổ ngoài, kèm hiển thị dung lượng trống và chặn
path traversal. Di chuyển weights **sao chép trước, xóa sau**: hủy giữa chừng không mất dữ
liệu. Tải weights tự thử lại 3 lần với backoff, xác minh SHA256 trước khi giữ lại tệp, và
tải vào tệp `.part` nên hủy hay mất mạng không để lại tệp hỏng.

**Sáu định dạng xuất, ghi nguyên tử**
PDF tìm kiếm được, Word, Excel, Markdown, văn bản thuần và JSON. Mọi tệp được ghi ra tệp tạm
rồi mới đổi tên, nên tệp cũ không bao giờ bị hỏng giữa chừng.

**Trải nghiệm hiện đại**
Chủ đề Sáng/Tối/Theo hệ thống với độ tương phản đạt chuẩn WCAG AA, đổi tức thì. Thông báo
toast bốn cấp thay cho hộp thoại chặn màn hình. Giao diện tiếng Việt và tiếng Anh, đổi ngôn
ngữ áp dụng ngay không cần khởi động lại.

**Chạy hoàn toàn ngoại tuyến**
Bản Portable đóng gói bằng PyInstaller chạy trên máy không cài Python và không có mạng, tự
tìm thư mục `models/` bên cạnh tệp thực thi. Cấu hình và nhật ký nằm cạnh ứng dụng, không ghi
vào thư mục hệ thống ẩn.

### Đối chiếu tiêu chí nghiệm thu

| Mã | Tiêu chí | Trạng thái |
| :-- | :-- | :-- |
| SC-1 | Thư mục weights tùy chỉnh | Đạt — có kiểm tra dung lượng, chống traversal, di chuyển an toàn |
| SC-2 | Tự làm thẳng và xoay ảnh | Đạt — Hough + minAreaRect, có kiểm thử |
| SC-5 | Bảo toàn bố cục đa cột | Đạt — kiểm thử E2E xác minh không đọc nối ngang cột |
| SC-6 | Trích xuất bảng ra Excel | Đạt — số dòng, cột và nội dung khớp trong kiểm thử E2E |
| SC-7 | PDF tìm kiếm được | Đạt — kiểm thử tìm được chữ trong lớp text ẩn |
| SC-8 | Hiệu năng xử lý hàng loạt | Đạt — chạy nền, thu hồi bộ nhớ mỗi trang, kiểm thử 100 trang |
| SC-9 | Bộ so sánh lỗi trực quan | Đạt — đồng bộ hai chiều tức thì |
| SC-10 | PDF có text layer | Đạt — kiểm thử yêu cầu dưới 1 giây mỗi trang |
| SC-11 | Tải weights có tiến trình | Đạt — %, tốc độ, ETA, hủy an toàn, xác minh SHA256 |
| SC-12 | Portable chạy máy khác | Đạt — đã dựng và chạy thử bundle khi không có Python trên PATH |
| SC-3 | Độ chính xác tiếng Việt > 96% CAR | **Chưa đo** — cần chạy VietOCR thật trên bộ mẫu có nhãn |
| SC-4 | Nhận diện chữ viết tay | **Chưa đo** — cần chạy TrOCR thật trên mẫu viết tay |

> SC-3 và SC-4 là tiêu chí về chất lượng mô hình, phải đo bằng model weights thật trên tập dữ
> liệu có nhãn. Toàn bộ đường đi của dữ liệu đã được kiểm thử; phần còn lại là chạy benchmark.

### Chất lượng mã nguồn (v0.1.0)

| Chỉ số | Kết quả |
| :-- | :-- |
| Kiểm thử | 489 xanh (unit, integration, gui) |
| Độ phủ | 89.6% (ngưỡng 80%) |
| `ruff`, `black`, `isort` | 0 lỗi |
| `mypy --strict` | 0 lỗi trên 62 tệp |
| `bandit` | 0 cảnh báo |
| Hàm dài nhất | 50 dòng (giới hạn 50) |
| Tệp dài nhất | 410 dòng (giới hạn 800) |
| `print()` trong `src/` | 0 |

### Yêu cầu hệ thống

- Python 3.10 trở lên (chỉ khi chạy từ mã nguồn); **numpy 2.1+**
- Không bắt buộc GPU. Có GPU NVIDIA (CUDA) thì nhanh hơn đáng kể; ứng dụng tự dò và lùi về CPU
- Dung lượng: khoảng 700 MB cho bundle, cộng thêm dung lượng model tùy engine

### Vấn đề đã biết

- **Chuẩn hóa dấu thanh:** hậu xử lý đổi `hòa` thành `hoà`, `thúy` thành `thuý` (dấu đặt trên
  nguyên âm thứ hai của `oa`, `oe`, `uy`). Văn bản hành chính thường dùng kiểu cũ; nếu cần giữ
  nguyên, dùng `Ctrl+H` để đổi lại sau khi nhận diện.
- **SC-3, SC-4 chưa đo** như ghi ở bảng trên.
- **Chưa có cơ chế cập nhật tự động** — đã thống nhất nằm ngoài phạm vi bản này.

---

## Test plan cho Pull Request

Chạy trên máy phát triển trước khi gộp:

```bash
# 1. Toàn bộ kiểm thử kèm độ phủ
python -m pytest tests/ --cov=src --cov-report=term-missing

# 2. Từng nhóm kiểm thử
python -m pytest -m unit
python -m pytest -m integration
python -m pytest -m gui

# 3. Cổng chất lượng tĩnh
python -m ruff check src/ tests/
python -m black --check src/ tests/
python -X utf8 -m isort --check-only src/ tests/
python -m mypy src/
python -m bandit -c pyproject.toml -r src/

# 4. Đóng gói
python packaging/build_portable.py --no-archive
```

Kiểm tra thủ công:

1. Mở `tests/fixtures/sample_vi_text.pdf` — phải đọc ra chữ ngay, không chạy OCR.
2. Mở `tests/fixtures/sample_skewed.png` — ảnh phải được làm thẳng trước khi nhận diện.
3. Chạy OCR một thư mục nhiều tệp, bấm **Tạm dừng** rồi **Tiếp tục** rồi **Hủy** — không treo,
   không crash.
4. Đổi chủ đề Sáng ↔ Tối và đổi ngôn ngữ Việt ↔ Anh — giao diện đổi ngay, không vỡ bố cục.
5. Xuất đủ sáu định dạng, mở từng tệp bằng ứng dụng tương ứng.
6. Đổi thư mục weights sang ổ khác và bấm **Di chuyển weights** — dữ liệu gốc còn nguyên cho
   tới khi sao chép xong.

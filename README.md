# pdf-ocr

Ứng dụng desktop nhận diện chữ (OCR) đa mô hình cho tài liệu tiếng Việt: giữ nguyên bố cục
nhiều cột, tách bảng biểu, soát lỗi song song ảnh–văn bản, xuất ra PDF tìm kiếm được, Word,
Excel, Markdown, JSON. Chạy trên **Windows, macOS, Linux** và hoạt động **100% ngoại tuyến**
sau khi đã tải mô hình.

- **Hướng dẫn sử dụng:** [docs/user_guide.md](docs/user_guide.md)
- **Đặc tả kỹ thuật:** [docs/implementation_plan.md](docs/implementation_plan.md)
- **Tiến độ triển khai:** [docs/checklist.md](docs/checklist.md)
- **Ghi chú phát hành:** [docs/release_notes.md](docs/release_notes.md)

---

## Tính năng

| Nhóm | Nội dung |
| :-- | :-- |
| **Đầu vào** | PDF, PNG, JPG, TIFF, BMP, WebP; kéo thả; mở cả thư mục |
| **Nhận diện (7 Engine)** | **VietOCR** (`vgg_transformer`, `vgg_seq2seq`, `resnet_transformer`), **PaddleOCR** (PP-OCRv3/v4/v5/v6, `PP-StructureV3`, `PaddleOCR-VL` 0.9B, tier `mobile`/`server`/`tiny`, 8 ngôn ngữ), **Surya OCR**, **TrOCR** (Small/Base/Large Handwritten, Printed, Scene Text `str`), **EasyOCR** (`latin_g2`, `english_g2`, `latin_g1`, `craft`/`dbnet18`), **Chandra OCR** (`chandra` v1, `chandra-ocr-2` 5B), **dots.ocr** (`dots.ocr` 1.7B, `dots.mocr` 1.5); tự động lùi sang engine dự phòng |
| **Model tùy chỉnh** | Nhập trực tiếp tệp trọng số riêng (`.pth`, `.pdparams`) hoặc thư mục checkpoint HuggingFace/Paddle từ giao diện |
| **PDF có sẵn text** | Đọc thẳng lớp text dưới 1 giây/trang; có tùy chọn **Ép buộc OCR** (`force_ocr`) khi lớp chữ gốc bị lỗi bảng mã |
| **Không gian đọc PDF** | Khung điều hướng trái (**Thông tin tệp**, **Trang** kèm huy hiệu `✓ Đã OCR`, **Mục lục** PDF, **Tìm kiếm** toàn văn), xoay trang 90° (`↺`/`↻`), vừa trang / vừa ngang, cuộn chuyển trang & `Ctrl + Lăn chuột` thu phóng, OCR nhanh riêng trang đang xem |
| **Tiền xử lý** | Tự xoay đúng hướng, làm thẳng ảnh nghiêng, cắt viền, khử bóng và tăng tương phản |
| **Bố cục** | Phân tích chiếu ngang/dọc (XY-Cut Projection Profile) & thứ tự đọc tự nhiên cho tài liệu nhiều cột; tách bảng biểu kèm ô gộp |
| **Hậu xử lý & Sửa chính tả** | Chuẩn hóa Unicode NFC, sửa nhầm lẫn ký tự, chuẩn hóa dấu thanh, và **Sửa lỗi chính tả & dấu tiếng Việt theo ngữ cảnh N-gram** (`VietnameseSpellCorrector` + `SymSpell` tùy chọn, bảo vệ số/email/SĐT/tên riêng) |
| **Soát lỗi** | So sánh ảnh–văn bản đồng bộ hai chiều, tô vàng từ tin cậy thấp, nút điều hướng nhanh **◀ Từ nghi ngờ / Từ nghi ngờ ▶**, nút **Sửa chính tả** 1 chạm, Undo/Redo, Tìm & Thay thế |
| **Chọn vùng** | Vẽ hình chữ nhật (`Ctrl+R`) để chỉ nhận diện một phần trang |
| **Bảng biểu** | Trình sửa bảng dạng lưới trước khi xuất Excel |
| **Xử lý nền** | QThreadPool; tạm dừng, tiếp tục, hủy; phần trăm và thời gian còn lại; thu hồi RAM/VRAM sau mỗi trang |
| **Xuất** | PDF tìm kiếm được, DOCX, XLSX, Markdown, TXT, JSON — ghi nguyên tử |
| **Giao diện & HiDPI** | Chủ đề Sáng/Tối/Theo hệ thống, tương thích màn hình **HiDPI** (125%, 150%, 200% với icon đa độ phân giải `@2x` và bố cục co giãn), thông báo toast, tiếng Việt và tiếng Anh |
| **Lưu trữ** | Cơ sở dữ liệu SQLite riêng trong thư mục ứng dụng; thư mục weights tùy chỉnh được |

---

## Cài đặt

### Bản Portable (người dùng cuối)

Giải nén `pdf-ocr-portable.zip`, chạy `pdf-ocr` (Windows: `pdf-ocr.exe`).
Không cần cài Python, không cần Internet. Xem
[mục 15 của sổ tay](docs/user_guide.md#15-bản-portable-mang-sang-máy-khác).

### Từ mã nguồn (lập trình viên)

Yêu cầu **Python 3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e .         # lõi + giao diện
python -m pip install -r requirements.txt      # kèm toàn bộ mô hình OCR
python -m pip install -r requirements-dev.txt  # công cụ kiểm thử

python -m src.main
```

Trong VS Code, nhấn `F5` và chọn **PDF OCR: chạy ứng dụng**.

> `numpy>=2.1` là bắt buộc: chú thích kiểu `np.ndarray` trong dự án chỉ vượt qua
> `mypy --strict` với stub của numpy 2.

---

## Kiểm thử và cổng chất lượng

```bash
python -m pytest tests/ --cov=src --cov-report=term-missing
python -m ruff check src/ tests/
python -m black --check src/ tests/
python -X utf8 -m isort --check-only src/ tests/
python -m mypy src/
python -m bandit -c pyproject.toml -r src/
```

Chạy riêng từng nhóm: `pytest -m unit`, `pytest -m integration`, `pytest -m gui`.

| Cổng | Ngưỡng | Hiện tại |
| :-- | :-- | :-- |
| Kiểm thử | Tất cả xanh | 600+ |
| Độ phủ | ≥ 80% | ~90% |
| `ruff` / `black` / `isort` | 0 lỗi | 0 |
| `mypy --strict` | 0 lỗi | 0 (71 tệp) |
| `bandit` | 0 cảnh báo | 0 |
| Kích thước hàm / tệp | ≤ 50 / ≤ 800 dòng | 50 / ≤ 800 |

Bộ tài liệu mẫu nằm ở `tests/fixtures/` và có thể dựng lại bằng
`python tests/fixtures/generate_fixtures.py`. Kiểm thử end-to-end chạy hoàn toàn ngoại tuyến:
phần nhận diện được thay bằng engine giả lập, mọi khâu còn lại là mã thật.

---

## Đóng gói bản Portable

```bash
python packaging/build_portable.py --with-weights
```

Kết quả nằm ở `dist/pdf-ocr/` kèm `dist/pdf-ocr-portable.zip`. Ứng dụng khi được đóng gói sẽ
tìm thư mục `models/` ngay cạnh tệp chạy, sau đó mới đến `src/models/`.

---

## Kiến trúc

```
src/
├── main.py            Điểm khởi chạy: HiDPI scaling → logging → ngôn ngữ → theme → weights → cửa sổ
├── config.py          Preferences bất biến; SQLite là nguồn chính, JSON là bản sao
├── constants.py       Từ vựng dùng chung: loại khối, mã màu, ngôn ngữ
├── core/              Domain thuần: models bất biến, loader, phân loại PDF, tiền xử lý,
│                      phân tích bố cục (XY-Cut), tách bảng, hậu xử lý & sửa chính tả N-gram
├── services/          Điều phối: pipeline, phiên xử lý theo trang, weights, thiết bị, SQLite
├── engines/           Provider OCR (VietOCR, PaddleOCR, Surya, TrOCR, EasyOCR, Chandra, dots.ocr)
├── exporters/         Provider xuất tệp (Registry + Adapter), ghi nguyên tử
├── workers/           QRunnable theo trang, hàng đợi batch, tín hiệu tiến độ
├── gui/               PySide6: cửa sổ chính, dock điều hướng PDF, canvas, bộ so sánh, hộp thoại, theme, i18n
└── utils/             Logging, tiện ích ảnh và đường dẫn
```

Nguyên tắc xuyên suốt:

- **Domain không biết Qt.** `src/core/` và phần lớn `src/services/` không import PySide6.
- **Bất biến.** Mọi domain model là `@dataclass(frozen=True)`; sửa đổi tạo đối tượng mới.
- **Mở rộng không sửa lõi.** Thêm engine OCR hoặc định dạng xuất chỉ cần đăng ký một lớp mới.
- **Không chặn giao diện.** Nhận diện, tải weights và di chuyển weights đều chạy luồng nền.
- **Lỗi không thoát ra vòng lặp sự kiện.** Error boundary ở tầng GUI biến mọi ngoại lệ thành
  thông báo thân thiện kèm nhật ký chi tiết; thông điệp cho người dùng không lộ đường dẫn
  hệ thống hay stack trace.

---

## Quy ước phát triển

- **Commit:** `<type>: <mô tả>` với `feat`, `fix`, `refactor`, `docs`, `test`, `chore`,
  `perf`, `ci`, `build`.
- **Nhánh:** `feature/<tên-module>`, gộp vào `main` qua Pull Request.
- **TDD:** viết kiểm thử thất bại trước, rồi mới viết mã.
- **Checklist:** đánh dấu `- [x]` trong `docs/checklist.md` ngay sau khi lệnh `Verify` của
  task đó chạy thành công.

---

## Giấy phép

[MIT](LICENSE).

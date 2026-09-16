# Ghi Chú Phát Hành

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

### Chất lượng mã nguồn

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

# Sổ Tay Hướng Dẫn Sử Dụng

## Ứng Dụng OCR Đa Mô Hình & Chuyển Đổi Tài Liệu

> Ứng dụng desktop nhận diện chữ (OCR) cho tài liệu tiếng Việt: giữ nguyên bố cục nhiều cột,
> tách bảng biểu, xuất ra PDF tìm kiếm được, Word, Excel, Markdown, JSON.
> Chạy được trên **Windows, macOS và Linux**, hoạt động **100% ngoại tuyến** sau khi đã tải mô hình.

---

## Mục lục

1. [Cài đặt](#1-cài-đặt)
2. [Làm quen với giao diện](#2-làm-quen-với-giao-diện)
3. [Quy trình cơ bản: từ tệp đến kết quả](#3-quy-trình-cơ-bản-từ-tệp-đến-kết-quả)
4. [Chọn mô hình và thiết bị chạy](#4-chọn-mô-hình-và-thiết-bị-chạy)
5. [Lưu mô hình vào ổ cứng ngoài & Nhập model riêng](#5-lưu-mô-hình-vào-ổ-cứng-ngoài--nhập-model-riêng)
6. [Soát lỗi bằng bộ so sánh song song](#6-soát-lỗi-bằng-bộ-so-sánh-song-song)
7. [Chỉ nhận diện một vùng](#7-chỉ-nhận-diện-một-vùng)
8. [Sửa bảng biểu trước khi xuất Excel](#8-sửa-bảng-biểu-trước-khi-xuất-excel)
9. [Quét hàng loạt](#9-quét-hàng-loạt)
10. [Xuất tài liệu](#10-xuất-tài-liệu)
11. [Giao diện, HiDPI và ngôn ngữ](#11-giao-diện-hidpi-và-ngôn-ngữ)
12. [Bảng phím tắt & Thao tác chuột](#12-bảng-phím-tắt--thao-tác-chuột)
13. [Mẹo tăng độ chính xác](#13-mẹo-tăng-độ-chính-xác)
14. [Xử lý sự cố](#14-xử-lý-sự-cố)
15. [Bản Portable: mang sang máy khác](#15-bản-portable-mang-sang-máy-khác)
16. [Dữ liệu của bạn được lưu ở đâu](#16-dữ-liệu-của-bạn-được-lưu-ở-đâu)

---

## 1. Cài đặt

### 1.1. Dùng bản Portable (khuyến nghị cho người dùng cuối)

Không cần cài Python. Giải nén `pdf-ocr-portable.zip`, mở thư mục `pdf-ocr` và chạy tệp
`pdf-ocr` (trên Windows là `pdf-ocr.exe`). Xem thêm [Mục 15](#15-bản-portable-mang-sang-máy-khác).

### 1.2. Chạy từ mã nguồn (dành cho lập trình viên)

Yêu cầu **Python 3.10 trở lên**.

```bash
git clone <địa-chỉ-kho-mã-nguồn> pdf-ocr
cd pdf-ocr

python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e .            # chỉ phần lõi và giao diện
pip install -r requirements.txt   # kèm toàn bộ mô hình OCR

python -m src.main
```

Trong **VS Code**, nhấn `F5` rồi chọn cấu hình **PDF OCR: chạy ứng dụng**.

### 1.3. Kiểm tra cài đặt

```bash
pytest tests/ --cov=src --cov-report=term-missing
```

---

## 2. Làm quen với giao diện

Cửa sổ chính được thiết kế theo bố cục của các trình đọc PDF chuyên nghiệp, gồm năm khu vực:

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│  Tệp   Sửa   Xem   OCR   Công cụ   Trợ giúp                        ← Thanh menu   │
├───────────────────────────────────────────────────────────────────────────────────┤
│  [Mở tệp] [Mở thư mục] │ [Chạy OCR] [Chọn vùng] …                  ← Thanh công cụ│
├──────────────────┬─────────────────────────────┬──────────────────┬───────────────┤
│ Điều hướng (Trái)│  Ảnh trang gốc              │ Văn bản nhận diện│ Tùy chọn (Phải│
│ • Thông tin tệp  │  [Vừa trang][Vừa ngang][↺][↻]│ [◀ Từ nghi ngờ ▶]│ • Mô hình OCR │
│   [OCR trang này]│  (phóng to, xoay trang,     │ [Sửa chính tả]   │ • Biến thể    │
│ • [Trang] (✓/○)  │   khung bố cục nhiều màu)   │ (sửa trực tiếp,  │ • Thiết bị    │
│ • [Mục lục PDF]  │                             │  tô vàng từ <80%,│ • Tiền xử lý  │
│ • [Tìm kiếm]     │      ← Bộ so sánh lỗi song song →              │ • Hậu xử lý   │
├──────────────────┴─────────────────────────────┴──────────────────┴───────────────┤
│  Đã xong 12/40 · Lỗi 0 · Còn lại: 1 phút  [▓▓▓▓▓░░░░░] [Tạm dừng] [Hủy]          │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### Khung Điều hướng bên trái (`NavigationDock`)

- **Thẻ thông tin tài liệu:** Hiển thị tên tệp, tổng số trang, dung lượng tệp, tiến độ số trang đã OCR (`Đã OCR: X/Y trang`), cùng nút **OCR trang hiện tại** để chạy OCR nhanh riêng trang đang mở.
- **Tab Trang:** Danh sách toàn bộ các trang kèm ảnh thu nhỏ và huy hiệu trạng thái trực quan (`✓ Đã OCR` màu xanh hoặc `○ Chưa OCR`).
- **Tab Mục lục:** Cây mục lục (Bookmarks / Outline) trích xuất tự động từ tệp PDF; nhấp vào mục bất kỳ để nhảy thẳng tới trang tương ứng.
- **Tab Tìm kiếm:** Tìm kiếm từ khóa xuyên suốt toàn bộ các trang của tài liệu (cả lớp chữ PDF gốc lẫn kết quả đã OCR) và nhảy đến trang chứa kết quả khi nhấp chọn.

**Màu khung bố cục** trên ảnh cho biết loại khối:

| Màu | Loại khối |
| :-- | :-- |
| Xanh dương | Đoạn văn bản thường |
| Tím hồng | Tiêu đề |
| Xanh lá | Bảng biểu |
| Cam | Hình ảnh |
| Đỏ (nét đứt) | Khối đang chọn / vùng bạn vừa vẽ |

---

## 3. Quy trình cơ bản: từ tệp đến kết quả

1. **Mở tài liệu** — `Ctrl+O`, hoặc **kéo thả** tệp PDF/ảnh thẳng vào cửa sổ.
   Định dạng hỗ trợ: `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.bmp`, `.webp`.
2. **Chọn mô hình, biến thể và thiết bị** ở dock *Tùy chọn nhận diện* bên phải ([Mục 4](#4-chọn-mô-hình-và-thiết-bị-chạy)).
3. **Chạy OCR** — nhấn `F5` để nhận diện toàn bộ tài liệu, hoặc bấm **OCR trang hiện tại** ở khung bên trái nếu chỉ cần xử lý trang đang xem.
4. **Soát lỗi & sửa chính tả** ở bộ so sánh song song ([Mục 6](#6-soát-lỗi-bằng-bộ-so-sánh-song-song)).
5. **Xuất tệp** — `Ctrl+S` ([Mục 10](#10-xuất-tài-liệu)).

> **PDF đã có sẵn lớp text** (xuất từ Word, trình duyệt…) được đọc thẳng, **không cần OCR**:
> nhanh dưới 1 giây mỗi trang và chính xác 100%. Nếu gặp tệp PDF có lớp chữ bị lỗi bảng mã
> (font TCVN3/VNI cũ đọc ra ký tự lạ), hãy bật **Ép buộc OCR (bỏ qua lớp chữ gốc)** ở khung tùy chọn.

---

## 4. Chọn mô hình và thiết bị chạy

### 4.1. Bảy mô hình OCR & các biến thể chuyên dụng

Ứng dụng tích hợp **7 mô hình OCR** và cho phép chọn **biến thể (variant)** tùy mục đích sử dụng ngay tại dock **Tùy chọn nhận diện**:

| Mô hình | Biến thể & Tùy chọn nổi bật | Khi nào nên chọn |
| :-- | :-- | :-- |
| **VietOCR** | `vgg_transformer` (chính xác cao), `vgg_seq2seq` (nhanh, nhẹ), `resnet_transformer`, hoặc tệp `.pth` tùy chỉnh | Văn bản tiếng Việt chữ in, hành chính, pháp lý, sách báo |
| **PaddleOCR** | • Phiên bản: `PP-OCRv6`, `PP-OCRv5`, `PP-OCRv4`, `PP-OCRv3`<br>• Chế độ: `ocr` (tiêu chuẩn), `pp_structure_v3` (bố cục & bảng biểu), `paddleocr_vl` (VLM 0.9B cho bảng/công thức phức tạp)<br>• Hạng mô hình: `mobile` (nhanh), `server` (chính xác cao), `tiny`<br>• Ngôn ngữ: `vi`, `en`, `latin`, `ch`, `japan`, `korean`, `fr`, `german` | Tài liệu nhiều bảng biểu, hóa đơn, báo cáo tài chính, tài liệu đa ngôn ngữ |
| **Surya OCR** | Nhận diện dòng đa ngôn ngữ (90+ ngôn ngữ) kèm phân tích thứ tự đọc | Sách, tạp chí nhiều cột, tài liệu học thuật song ngữ |
| **TrOCR** | • Chữ viết tay: `trocr-base-handwritten`, `trocr-small-handwritten`, `trocr-large-handwritten`<br>• Chữ in: `trocr-base-printed`, `trocr-small-printed`, `trocr-large-printed`<br>• Chữ ngoại cảnh: `trocr-base-str`, `trocr-large-str` | Ghi chú viết tay, mẫu đơn điền tay, ảnh chụp biển hiệu |
| **EasyOCR** | • Mạng nhận diện: `latin_g2`, `english_g2`, `latin_g1`, hoặc `.pth` tùy chỉnh<br>• Mạng phát hiện: `craft` (chính xác), `dbnet18` (nhanh) | Dự phòng đa ngôn ngữ gọn nhẹ trên CPU |
| **Chandra OCR** | • Biến thể: `datalab-to/chandra` (v1), `datalab-to/chandra-ocr-2` (5B flagship)<br>• Chế độ prompt: `ocr_layout` (giữ bố cục/bảng/toán), `ocr` (văn bản thuần)<br>• Backend: `hf` (cục bộ) hoặc `vllm` | Tài liệu phức tạp có công thức toán học, bảng biểu lồng nhau, biểu mẫu |
| **dots.ocr** | • Biến thể: `rednote-hilab/dots.ocr` (1.7B VLM), `rednote-hilab/dots.mocr` (1.5 đa phương thức), `dots-studio/dots.ocr`<br>• Chế độ: `layout_all` (bố cục + bảng + chữ), `ocr` | Phân tích tài liệu thông minh bằng Vision-Language Model gọn nhẹ |

> **Nhập model tùy chỉnh của riêng bạn:** Trong ô chọn biến thể của bất kỳ mô hình nào, bạn có thể chọn **`+ Chọn tệp/thư mục model tùy chỉnh…`** (hoặc vào **Công cụ → Cài đặt**) để nạp trực tiếp tệp trọng số `.pth`, `.pdparams` hay thư mục checkpoint HuggingFace/Paddle đã huấn luyện riêng.

### 4.2. Các tùy chọn xử lý trên Dock phải

| Mục | Ý nghĩa | Gợi ý |
| :-- | :-- | :-- |
| **Thiết bị** | CPU hay GPU (`CUDA`) | Để `Tự động phát hiện` |
| **Độ phân giải** | DPI khi dựng ảnh từ PDF | 300 DPI là mặc định tốt; 400–600 cho chữ rất nhỏ |
| **Tiền xử lý ảnh** | Tự xoay hướng, làm thẳng nghiêng, cắt viền, tăng tương phản | Giữ bật tất cả, trừ khi ảnh đã sạch sẵn |
| **Nhận diện bảng biểu** | Dựng lưới hàng/cột từ bảng | Kết hợp tốt nhất với `PaddleOCR` / `Chandra` / `dots.ocr` |
| **Thứ tự đọc nhiều cột** | Phân tích chiếu XY-Cut & sắp xếp đọc lần lượt từng cột | Giữ bật để tránh ghép chữ xuyên cột |
| **Gộp dòng thành đoạn** | Nối các dòng cùng đoạn | Tắt nếu cần giữ riêng từng dòng OCR |
| **Ép buộc OCR** | Bỏ qua lớp chữ có sẵn của PDF, bắt buộc quét ảnh | Bật khi PDF có lớp chữ bị lỗi font/bảng mã |
| **Sửa lỗi chính tả & dấu tiếng Việt (N-gram)** | Tự động sửa dấu thanh/mũ nguyên âm bị nhầm theo ngữ cảnh cụm từ 1/2/3-gram | Giữ bật cho tài liệu tiếng Việt để tự sửa các lỗi như `đưạc` → `được`, `tổ chửc` → `tổ chức`, `nhan vien` → `nhân viên` |

Kết quả có nhãn tiêu đề cấp 1–3 khi cỡ chữ/chiều cao dòng nổi bật rõ so với văn bản thường;
nhãn chú thích được nhận diện theo tiền tố như `Hình 1` hoặc `Table 2`.

Bốn bộ lọc tiền xử lý chạy theo thứ tự: **tự xoay đúng hướng → làm thẳng ảnh nghiêng →
cắt viền thừa → tăng cường chất lượng ảnh**.

### Về GPU

Vào **Công cụ → Cài đặt → Thiết bị thực thi**. Ứng dụng tự dò card đồ họa và hiển thị
tên cùng dung lượng VRAM, ví dụ *"Đã phát hiện NVIDIA RTX 4090 với 24.0 GB VRAM"*.
Nếu máy không có GPU CUDA, dòng chữ sẽ ghi rõ và ứng dụng chạy bằng CPU — chậm hơn
nhưng kết quả không đổi. Chế độ `Tự động` chọn GPU khi có và lùi về CPU khi không.

---

## 5. Lưu mô hình vào ổ cứng ngoài & Nhập model riêng

Các mô hình OCR nặng vài GB. Mặc định chúng nằm trong thư mục ứng dụng
(`src/models/`), **không bao giờ** ghi vào `C:\Users\...\.cache` làm đầy ổ hệ thống.

Để chuyển sang ổ ngoài hoặc nhập model riêng:

1. **Công cụ → Cài đặt** (`Ctrl+,`).
2. Ở mục **Thư mục mô hình & weights**, bấm **Duyệt…** và chọn thư mục trên ổ ngoài,
   ví dụ `E:\PDF-OCR-Models`.
3. Đọc dòng **Dung lượng trống** ngay bên dưới để chắc chắn ổ đủ chỗ.
4. Nếu đã tải mô hình từ trước, bấm **Di chuyển weights sang thư mục mới**. Thanh tiến trình
   hiển thị tiến độ sao chép.
5. Nếu bạn có sẵn tệp trọng số `.pth` hoặc thư mục model tự huấn luyện, dùng nút **+ Nhập tệp model (.pth)…** hoặc **+ Nhập thư mục model…** để sao chép vào kho mô hình của ứng dụng.
6. Bấm **OK**.

> **An toàn dữ liệu:** thao tác di chuyển **sao chép trước, xóa sau**. Nếu bạn hủy giữa chừng
> hoặc rút nhầm ổ cứng, mô hình gốc vẫn còn nguyên. Ứng dụng cũng từ chối những đường dẫn
> chứa `..` và những thư mục đích nằm bên trong thư mục nguồn.

Sau khi đổi, các biến môi trường cache của PyTorch, HuggingFace, PaddleOCR và EasyOCR
đều được chuyển hướng vào thư mục bạn chọn.

---

## 6. Soát lỗi bằng bộ so sánh song song

Bộ so sánh lỗi song song kết hợp công cụ xem PDF chuyên nghiệp ở bên trái và trình biên tập văn bản ở bên phải:

- **Từ văn bản sang ảnh:** đặt con trỏ vào một đoạn ở khung phải → khung trái tự cuộn đến
  đúng khối tương ứng và tô viền đỏ.
- **Từ ảnh sang văn bản:** bấm vào một khung bố cục ở khung trái → con trỏ nhảy tới đoạn đó.
- **Điều khiển trang & hiển thị ảnh (thanh điều hướng 2 hàng chuẩn HiDPI):**
  - **Vừa trang** (`Ctrl+0`): thu phóng để thấy trọn vẹn cả trang.
  - **Vừa ngang**: thu phóng vừa khít chiều ngang khung nhìn để đọc chữ rõ nhất.
  - **Xoay trang 90° (`↺` / `↻`)**: xoay nhanh trang bị quét ngược hoặc nằm ngang.
  - **Cuộn chuột chuyển trang & thu phóng:** lăn chuột khi đang ở đầu/cuối trang sẽ tự động chuyển sang trang trước/sau; giữ **`Ctrl + Lăn chuột`** (hoặc `Ctrl` `+` / `Ctrl` `-`) để phóng to/thu nhỏ ảnh tại vị trí con trỏ.
- **Duyệt nhanh từ nghi ngờ (`◀ Từ nghi ngờ` / `Từ nghi ngờ ▶`):** những từ mô hình không chắc chắn (độ tin cậy dưới 80%) được tô nền vàng nhạt kèm bộ đếm số lượng từ nghi ngờ. Bấm hai nút này để nhảy lần lượt qua từng từ cần kiểm tra mà không sợ bỏ sót.
- **Nút `Sửa chính tả` 1 chạm:** bấm nút **Sửa chính tả** ngay trên thanh công cụ của bộ so sánh để chạy bộ sửa lỗi chính tả & dấu tiếng Việt theo ngữ cảnh N-gram trên toàn bộ nội dung văn bản đang mở (hỗ trợ hoàn tác bằng `Ctrl+Z`).
- **Sửa trực tiếp:** gõ thẳng vào khung phải. `Ctrl+Z` hoàn tác, `Ctrl+Y` làm lại.

### Sửa hàng loạt một lỗi lặp lại

Mô hình thường sai cùng một chỗ trên nhiều trang (ví dụ `đuợc` thay vì `được`).

1. `Ctrl+H` mở hộp thoại **Tìm và thay thế**.
2. Gõ chữ sai vào ô **Tìm**, chữ đúng vào ô **Thay bằng**.
3. Bấm **Thay tất cả**.

> Toàn bộ lần thay thế hàng loạt chỉ tính là **một bước hoàn tác**: bấm `Ctrl+Z` một lần
> là quay lại nguyên trạng, không phải bấm hàng chục lần.

Tùy chọn **Phân biệt hoa thường** và **Đúng toàn bộ từ** giúp thu hẹp phạm vi tìm.

---

## 7. Chỉ nhận diện một vùng

Khi bạn chỉ cần một đoạn hoặc một bảng trong trang:

1. Bấm **Chọn vùng OCR** trên thanh công cụ, hoặc `Ctrl+R` (nút trên thanh công cụ sẽ sáng nổi bật khi chế độ chọn vùng đang bật).
2. Kéo chuột vẽ hình chữ nhật trên ảnh. Vùng chọn hiện nét đứt màu đỏ.
3. Kết quả của riêng vùng đó hiển thị ngay dưới khung văn bản.
4. Bấm `Ctrl+R` lần nữa để tắt chế độ vẽ và quay lại kéo thả ảnh như thường.

Vùng chọn luôn được cắt gọn trong phạm vi trang, kéo theo chiều nào cũng cho hình chữ nhật hợp lệ.
Nếu đang chọn **PaddleOCR** và bật **Nhận diện bảng biểu**, bảng tìm thấy trong vùng sẽ được thêm vào
kết quả trang hiện tại, hiện trong danh sách bảng và có thể chỉnh sửa hoặc xuất ra Excel. Với PDF có
lớp chữ, nội dung chữ dùng trực tiếp từ PDF; phần nhận diện cấu trúc bảng vẫn chạy nền.

---

## 8. Sửa bảng biểu trước khi xuất Excel

**Nhấp đúp** vào một khung bảng (viền xanh lá) trên ảnh để mở trình sửa bảng:

- Sửa nội dung từng ô bằng cách nhấp đúp vào ô đó.
- **Thêm dòng** / **Xóa dòng** / **Thêm cột** / **Xóa cột**.
- Bấm **OK** để ghi nhận.

Trình sửa luôn giữ bảng ở dạng chữ nhật hợp lệ: không cho xóa dòng hoặc cột cuối cùng, và
tự bỏ những ô gộp không còn nằm trong kích thước mới.

---

## 9. Quét hàng loạt

1. **Tệp → Mở thư mục** (`Ctrl+Shift+O`), hoặc chọn nhiều tệp.
2. Nhấn `F5`. Cửa sổ **Quét hàng loạt** hiện ra, liệt kê từng tài liệu kèm trạng thái:
   **Chờ → Đang chạy → Xong** (hoặc **Lỗi**).
3. Thanh trạng thái và cửa sổ batch hiển thị phần trăm, số trang đã xong, số trang lỗi và
   **thời gian còn lại** ước tính theo tốc độ thực tế.

| Nút | Tác dụng |
| :-- | :-- |
| **Tạm dừng** | Không nhận trang mới; trang đang chạy vẫn hoàn tất bình thường |
| **Tiếp tục** | Chạy tiếp từ chỗ dừng |
| **Hủy** | Bỏ mọi trang chưa bắt đầu; không để lại tệp dở dang |

Một trang lỗi **không làm dừng cả lượt quét** — ứng dụng ghi nhận và chạy tiếp trang sau.
Đóng cửa sổ batch giữa chừng sẽ tự hủy lượt quét và chờ luồng nền dừng hẳn, không bỏ sót
tiến trình chạy ngầm.

> Toàn bộ quá trình chạy trên luồng nền. Bộ nhớ RAM và VRAM được thu hồi **sau mỗi trang**,
> nên quét 100 trang liên tục không làm ứng dụng phình bộ nhớ.

---

## 10. Xuất tài liệu

`Ctrl+S`, hoặc **Tệp → Xuất tài liệu**.

| Định dạng | Đuôi | Dùng khi nào |
| :-- | :-- | :-- |
| **PDF tìm kiếm được** | `.pdf` | Lưu trữ: giữ nguyên ảnh gốc, thêm lớp text ẩn để `Ctrl+F` tìm được |
| **Word** | `.docx` | Cần sửa tiếp, giữ tiêu đề và bảng |
| **Excel** | `.xlsx` | Chỉ lấy bảng biểu, mỗi bảng một sheet |
| **Markdown** | `.md` | Đưa vào tài liệu kỹ thuật, wiki |
| **Văn bản thuần** | `.txt` | Chỉ cần nội dung chữ |
| **JSON** | `.json` | Lập trình: kèm tọa độ và độ tin cậy từng từ |

Mọi tệp xuất đều **ghi nguyên tử**: ứng dụng ghi ra tệp tạm rồi mới đổi tên. Nếu hết dung
lượng hoặc mất quyền ghi giữa chừng, tệp cũ của bạn vẫn nguyên vẹn, không có tệp dở dang.

---

## 11. Giao diện, HiDPI và ngôn ngữ

**Công cụ → Cài đặt → Giao diện**:

- **Chủ đề:** `Theo hệ thống` / `Sáng` / `Tối`. Đổi là áp dụng ngay, không cần khởi động lại.
- **Ngôn ngữ:** `Tiếng Việt` / `English`. Cũng áp dụng ngay.
- **Tương thích màn hình phân giải cao (HiDPI):** Ứng dụng tự động nhận diện tỷ lệ phóng đại của màn hình (125%, 150%, 175%, 200%, 4K) với chính sách `PassThrough` của Qt 6, dựng biểu tượng thanh công cụ đa độ phân giải (`@1x` / `@2x`) sắc nét và tự động co giãn chiều cao nút bấm, hộp chọn mà không bị cắt chữ.

Cả chủ đề và ngôn ngữ đều được ghi nhớ cho lần mở sau.

---

## 12. Bảng phím tắt & Thao tác chuột

| Phím tắt / Thao tác | Chức năng |
| :-- | :-- |
| `Ctrl+O` | Mở tệp |
| `Ctrl+Shift+O` | Mở thư mục |
| `Ctrl+S` | Xuất tài liệu |
| `Ctrl+Q` | Thoát |
| `F5` | Chạy OCR toàn tài liệu |
| `Ctrl+R` | Bật/tắt chế độ chọn vùng OCR |
| `Ctrl+H` | Tìm và thay thế |
| `Ctrl+Z` / `Ctrl+Y` | Hoàn tác / Làm lại |
| `Ctrl` `+` / `Ctrl` `-` | Phóng to / Thu nhỏ |
| `Ctrl + Lăn chuột` | Phóng to / Thu nhỏ mượt tại vị trí con trỏ |
| `Lăn chuột` | Cuộn trang hiện tại; tự chuyển sang trang trước/sau khi chạm biên đầu/cuối |
| `Ctrl+0` | Vừa khung cửa sổ (Vừa trang) |
| `PgUp` / `PgDn` | Chuyển trang trước / trang sau |
| `Ctrl+,` | Mở Cài đặt |

Menu **Tệp → Tệp gần đây** lưu 10 tài liệu mở gần nhất.
Vị trí cửa sổ và cách bố trí các dock được ghi nhớ giữa các lần chạy.

---

## 13. Mẹo tăng độ chính xác

**Về tài liệu đầu vào**

- Scan ở **300 DPI** trở lên. Dưới 200 DPI chữ nhỏ sẽ mất nét.
- Chụp bằng điện thoại: đặt giấy trên nền phẳng, đủ sáng, tránh bóng tay và nếp gấp.
  Ứng dụng tự làm thẳng ảnh nghiêng và xóa bóng, nhưng ảnh gốc tốt vẫn cho kết quả tốt hơn.
- Scan **đen trắng có ngưỡng cứng** thường kém hơn scan **thang xám**.

**Về lựa chọn trong ứng dụng**

- PDF đã có lớp text: cứ mở bình thường, đừng ép chạy OCR — trừ khi lớp chữ gốc của PDF bị lỗi font/bảng mã thì mới bật **Ép buộc OCR**.
- Chữ rất nhỏ hoặc dấu bị dính: nâng **Độ phân giải** lên 400–600 DPI.
- Văn bản tiếng Việt hành chính/sách báo: chọn **VietOCR** (`vgg_transformer`) và bật **Sửa lỗi chính tả & dấu tiếng Việt (N-gram)**.
- Tài liệu nhiều bảng biểu: chọn **PaddleOCR** (chế độ `pp_structure_v3` hoặc `paddleocr_vl`), **Chandra OCR** (`chandra-ocr-2`) hoặc **dots.ocr**.
- Chữ viết tay: chọn **TrOCR** (`trocr-base-handwritten` hoặc `trocr-large-handwritten`).
- Ảnh đã được xử lý sạch từ trước: **tắt** các bộ lọc tiền xử lý để tránh xử lý chồng.
- Chỉ cần một đoạn nhỏ: dùng **chọn vùng** (`Ctrl+R`) hoặc **OCR trang hiện tại** — nhanh hơn và ít nhiễu hơn.

**Về khâu soát lỗi**

- Dùng nút **`◀ Từ nghi ngờ` / `Từ nghi ngờ ▶`** để duyệt nhanh qua các từ tô vàng.
- Bấm **`Sửa chính tả`** trên thanh công cụ so sánh để tự động khôi phục dấu tiếng Việt theo ngữ cảnh cụm từ (số, email, số điện thoại và tên riêng viết hoa được bảo vệ tự động).
- Gặp lỗi lặp lại, dùng `Ctrl+H` **Thay tất cả** thay vì sửa thủ công từng chỗ.

---

## 14. Xử lý sự cố

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
| :-- | :-- | :-- |
| *"Định dạng tệp này chưa được hỗ trợ."* | Đuôi tệp ngoài danh sách ở [Mục 3](#3-quy-trình-cơ-bản-từ-tệp-đến-kết-quả) | Chuyển sang PDF hoặc PNG |
| *"Không thể mở tài liệu…"* | PDF đặt mật khẩu, hoặc tệp hỏng | Bỏ mật khẩu rồi mở lại |
| *"Không đủ dung lượng trống."* | Ổ đĩa đầy khi tải hoặc di chuyển mô hình | Dọn ổ, hoặc đổi sang ổ khác ở Cài đặt |
| *"Không thể tải mô hình. Vui lòng kiểm tra kết nối mạng…"* | Mất mạng khi tải lần đầu | Kiểm tra mạng; ứng dụng đã tự thử lại 3 lần |
| *"Tệp tải về không đạt kiểm tra toàn vẹn SHA256."* | Tải bị hỏng giữa chừng | Tải lại; tệp hỏng đã tự bị xóa, không lưu vào máy |
| *"Không phát hiện GPU CUDA…"* | Máy không có card NVIDIA, hoặc thiếu driver | Dùng CPU, hoặc cài lại driver CUDA |
| PDF mở ra hiện ký tự lạ (lỗi font TCVN3/VNI) | Lớp chữ gốc của PDF dùng bảng mã cũ | Tích chọn **Ép buộc OCR (bỏ qua lớp chữ gốc)** rồi nhấn `F5` |
| Chạy OCR rất chậm | Đang chạy bằng CPU, hoặc DPI quá cao | Hạ DPI về 300; chọn biến thể `mobile` / `vgg_seq2seq`; bật GPU nếu có |
| Kết quả sai nhiều dấu tiếng Việt | Ảnh mờ hoặc chưa bật sửa chính tả ngữ cảnh | Bật **Sửa lỗi chính tả & dấu tiếng Việt (N-gram)** hoặc bấm nút **Sửa chính tả** |
| Chữ cột 1 bị nối sang cột 2 | Khoảng cách cột trong bản gốc quá hẹp | Bật **Thứ tự đọc nhiều cột** hoặc dùng **chọn vùng** (`Ctrl+R`) |

Thông báo lỗi hiện ở góc dưới bên phải dưới dạng thẻ màu. Thẻ **lỗi (đỏ)** ở lại đến khi bạn
đóng; thẻ thành công và thông tin tự ẩn sau vài giây. Nhật ký chi tiết dành cho kỹ thuật viên
nằm trong thư mục `logs/` ([Mục 16](#16-dữ-liệu-của-bạn-được-lưu-ở-đâu)).

> **Lưu ý về chính tả:** ứng dụng chuẩn hóa vị trí dấu thanh theo kiểu `hoà`, `khoẻ`, `thuý`
> (dấu đặt trên nguyên âm thứ hai của `oa`, `oe`, `uy`). Nếu tài liệu của bạn cần kiểu cũ
> (`hòa`, `khỏe`, `thúy`), hãy dùng `Ctrl+H` để đổi lại sau khi nhận diện.

---

## 15. Bản Portable: mang sang máy khác

Bản Portable chạy trên máy **không cài Python và không có Internet**.

**Tạo bản Portable** (trên máy đã cài đặt mã nguồn):

```bash
python packaging/build_portable.py --with-weights
```

Kết quả: `dist/pdf-ocr/` và tệp nén `dist/pdf-ocr-portable.zip`.

**Mang sang máy khác:**

1. Chép cả thư mục `pdf-ocr` (hoặc giải nén tệp zip) sang máy đích — USB, ổ ngoài đều được.
2. Bảo đảm thư mục `models` nằm **ngay cạnh** tệp chạy:

   ```
   pdf-ocr/
   ├── pdf-ocr(.exe)     ← tệp chạy
   ├── _internal/        ← thư viện đi kèm
   ├── models/           ← mô hình OCR (bắt buộc để chạy ngoại tuyến)
   ├── config/           ← cấu hình, tự tạo khi chạy lần đầu
   └── logs/             ← nhật ký, tự tạo khi chạy lần đầu
   ```

3. Chạy tệp `pdf-ocr`. Ứng dụng tự tìm thư mục `models` bên cạnh và nhận diện hoàn toàn
   ngoại tuyến.

Nếu quên `--with-weights`, hãy chép tay thư mục `src/models` của máy nguồn vào thành
`pdf-ocr/models` trên máy đích.

---

## 16. Dữ liệu của bạn được lưu ở đâu

Ứng dụng **không ghi gì vào thư mục hệ thống ẩn**. Mọi thứ nằm trong thư mục ứng dụng:

| Thư mục / tệp | Nội dung |
| :-- | :-- |
| `config/settings.db` | Cơ sở dữ liệu SQLite: cài đặt, tham số mô hình, thông số phiên làm việc |
| `config/preferences.json` | Bản sao cấu hình dạng văn bản, dễ đọc và sao lưu |
| `config/preferences.ini` | Bản sao cho Qt |
| `logs/app.log` | Nhật ký ứng dụng, tự xoay vòng 10 MB, giữ 14 ngày |
| `src/models/` (hoặc `models/`) | Mô hình OCR và cache của PyTorch, HuggingFace, PaddleOCR, EasyOCR |

Sao lưu thư mục `config` là đủ để giữ lại toàn bộ tùy chỉnh của bạn.
Nhật ký **không ghi nội dung tài liệu** của bạn.

---

*Gặp vấn đề chưa có trong sổ tay này? Hãy gửi kèm tệp `logs/app.log` khi báo lỗi.*

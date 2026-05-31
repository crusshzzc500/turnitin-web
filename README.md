# Minh Chứng

Nền tảng đối chiếu văn bản độc lập, có API, kho nguồn cục bộ và crawler web tuân
thủ giới hạn truy cập.

## Mở ứng dụng

Cách đơn giản nhất trên Windows:

1. Mở `start-minh-chung.cmd`.
2. Chờ trình duyệt mở `http://127.0.0.1:8765`.
3. Chọn **Dùng bài mẫu**, sau đó bấm **Tạo báo cáo tương đồng**.

Cách chạy thủ công:

```powershell
& 'C:\Users\Minh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' run.py
```

## Đã có

- Tải hoặc dán `.txt`, `.md`, `.docx`, `.pdf`.
- Ba vai trò thử nghiệm `admin`, `instructor`, `student`; dữ liệu riêng được giới hạn theo tổ chức.
- Kho nguồn SQLite và chỉ mục toàn văn FTS5.
- Lưu lịch sử phiên bản nguồn bất biến khi nội dung website thay đổi.
- Đoạn tô màu, tỷ lệ tương đồng, danh sách nguồn và lịch sử báo cáo phía server.
- Xuất báo cáo PDF có thông tin tổ chức, điểm tương đồng, nguồn, đoạn đối chiếu và cảnh báo liêm chính.
- PDF scan ít chữ tự thử OCR khi máy chủ có Tesseract và `pdf2image`.
- Bộ lọc trích dẫn, tài liệu tham khảo và độ dài tối thiểu.
- Thêm nguồn riêng từ giao diện.
- Kho bài nộp nội bộ chỉ lập chỉ mục khi người dùng đồng ý; có thao tác rút bài
  và nguồn liên quan khỏi kho đối chiếu.
- Cảnh báo ký tự vô hình, ký tự giả dạng và một số thủ thuật định dạng DOCX.
- Crawler nhận URL hạt giống, đọc `robots.txt`, giới hạn tốc độ, giới hạn dung
  lượng, chỉ đi tiếp trong cùng tên miền theo mặc định và chặn mạng nội bộ.
- Retry có backoff cho lỗi mạng hoặc lỗi máy chủ tạm thời; dashboard theo dõi
  hàng đợi và thao tác đưa URL lỗi trở lại queue.
- Lớp tìm kiếm tách rời: mặc định SQLite FTS5, có adapter OpenSearch và thao tác
  lập lại chỉ mục khi chuyển hạ tầng.
- Chế độ cục bộ dự phòng khi mở thẳng `index.html`.

## Thu thập web

Trong **Kho nguồn**, nhập URL hạt giống rồi chọn số trang và độ sâu. Chỉ thêm
website bạn được phép lập chỉ mục. Tôn trọng `robots.txt` không tự động tạo ra
quyền sử dụng dữ liệu. Với website có sitemap XML, đánh dấu **URL là sitemap
XML** để nhập nhiều trang trong một lần.

Crawler hiện chạy trên một máy. Để thu thập hàng triệu trang, cần chuyển sang
kiến trúc phân tán mô tả trong [ARCHITECTURE.md](./ARCHITECTURE.md).

Danh sách API hiện có nằm trong [API.md](./API.md).

## OCR cho PDF scan

OCR là lớp dự phòng tùy chọn. Máy chủ hiện vẫn đọc PDF có lớp văn bản bằng `pypdf` mà không cần
Tesseract. Với PDF scan, cài Tesseract OCR và cấu hình nếu chương trình không nằm trong `PATH`:

```powershell
$env:MINH_CHUNG_TESSERACT_PATH = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
$env:MINH_CHUNG_OCR_LANGUAGES = 'vie+eng'
```

Kiểm tra trạng thái bằng `GET /api/ocr/status`.

## Kiểm thử

```powershell
& 'C:\Users\Minh\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s .\tests -v
```

## Lưu ý

Minh Chứng hỗ trợ rà soát liêm chính học thuật. Tỷ lệ tương đồng không phải là
kết luận tự động về đạo văn.

## Nâng cấp bản dùng tự do + quét web công khai

Bản này đã được chỉnh theo hướng ai cũng dùng được, không cần chọn tài khoản giáo viên/sinh viên. Mặc định hệ thống dùng người nội bộ `demo-admin` để backend hoạt động, nhưng giao diện không hiển thị phân quyền.

### Quét web tự động như bản mô phỏng Turnitin

Không thể quét “toàn bộ Internet” giống Turnitin thật vì Turnitin có kho dữ liệu thương mại riêng và quyền truy cập đặc biệt. Bản này dùng cách khả thi hơn:

1. Lấy vài câu nổi bật trong bài.
2. Gửi truy vấn qua API tìm kiếm web.
3. Lập chỉ mục các nguồn công khai trả về.
4. Chạy lại bộ so khớp để hiện nguồn và đoạn trùng.

### Dịch vụ miễn phí nên dùng

Ưu tiên Tavily vì có gói miễn phí, dễ lấy nội dung thô của trang và không cần thẻ ngân hàng ở gói miễn phí.

Cách cấu hình trên Windows PowerShell:

```powershell
setx TAVILY_API_KEY "dán_key_của_bạn_vào_đây"
```

Sau đó đóng cửa sổ terminal, mở lại và chạy:

```bash
python run.py
```

Nếu muốn dùng Brave Search API:

```powershell
setx BRAVE_SEARCH_API_KEY "dán_key_của_bạn_vào_đây"
```

Lưu ý: nếu chưa cấu hình API key, nút “Quét nguồn web công khai tự động” vẫn hiện nhưng backend sẽ báo chưa cấu hình và chỉ đối chiếu với kho nguồn đang có.

### Khuyến nghị sử dụng

- Dùng Tavily cho bản miễn phí, học tập, demo lâu dài.
- Không nên dùng Google Custom Search cho dự án mới vì API này không còn phù hợp cho khách hàng mới và có lộ trình dừng.
- Không crawler ồ ạt nhiều website. Hãy tôn trọng robots.txt và điều khoản của từng trang.

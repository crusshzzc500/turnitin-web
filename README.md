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

Để deploy bản chính thức quy mô nhỏ lên Render và Neon, dùng [DEPLOY_RENDER.md](./DEPLOY_RENDER.md).
File `render.yaml` bật đăng nhập mật khẩu và lưu dữ liệu bền vững qua `DATABASE_URL`.

## Đã có

- Tải nguyên bài hoặc dán `.txt`, `.md`, `.docx`, `.pdf`; giới hạn mặc định `250 MB`.
- Thanh tiến trình phần trăm khi đọc tệp, quét web, đối chiếu nguồn và hoàn thiện báo cáo.
- Bản local có ba vai trò thử nghiệm `admin`, `instructor`, `student`; bản Render dùng tài khoản mật khẩu thật.
- Kho nguồn SQLite và chỉ mục toàn văn FTS5 cho local; PostgreSQL Neon và tìm kiếm `ILIKE` cho Render nhỏ gọn.
- Lưu lịch sử phiên bản nguồn bất biến khi nội dung website thay đổi.
- Đoạn tô màu, tỷ lệ tương đồng, danh sách nguồn và lịch sử báo cáo phía server.
- Xuất báo cáo PDF có thông tin tổ chức, điểm tương đồng, nguồn, đoạn đối chiếu và cảnh báo liêm chính.
- PDF scan ít chữ tự thử OCR khi máy chủ có Tesseract và `pdf2image`.
- Quét bổ sung nguồn web công khai qua Serper, Tavily, Exa, WebSearchAPI.ai, Linkup hoặc Brave khi người dùng chủ động bật;
  Serper thử một truy vấn chính xác trước, Tavily dùng `fast`, các tầng sau chỉ chạy fallback khi nguồn trước còn thiếu, và mỗi nhà cung cấp dừng chờ
  nguồn chậm sau ngân sách thời gian cấu hình.
- Chuẩn hóa Unicode cho văn bản đầu vào có lỗi mã hóa có thể phục hồi; nội dung báo cáo hiển thị bằng
  Times New Roman.
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

## Tìm thêm nguồn web khi tạo báo cáo

Tùy chọn **Quét thêm nguồn web công khai** mặc định tắt. Khi người dùng chủ động bật, hệ thống
chọn thông minh tối đa `10` dấu vân tay nội dung và gửi truy vấn song song sang Tavily. Bộ chọn ưu tiên
câu có nhiều thuật ngữ hiếm, cắt câu dài thành cửa sổ có thể tìm kiếm, tránh truy vấn gần trùng và dành
một phần ngân sách sẵn có cho chữ ký từ khóa cô đọng để bắt cả nội dung đã sửa nhẹ câu chữ. Khi Tavily trả về ít hơn
`8` nguồn hữu ích hoặc không dùng được, Exa fallback chỉ nhận tối đa `3` truy vấn để tiết kiệm quota.
Serper thử tối đa `1` truy vấn chính xác trước chuỗi trên để dừng sớm nếu tìm thấy bản sao toàn bài. Nếu tổng nguồn
vẫn thiếu, WebSearchAPI.ai và Linkup lần lượt chỉ nhận tối đa `1` truy vấn. Brave là lựa chọn dự phòng tiếp theo. Mỗi truy vấn
nhận tối đa `10` kết quả ứng viên, sau đó hệ thống lập chỉ mục nguồn phù hợp trong phạm vi tổ chức
rồi mới chạy đối chiếu. URL tracking được chuẩn hóa để tránh nguồn trùng; kết quả ít liên quan bị loại
bằng điểm phủ từ khóa và cụm từ liên tiếp. Với tối đa `2` ứng viên tốt có đoạn mô tả ngắn, hệ thống tải
trang công khai theo `robots.txt` để bổ sung nội dung đầy đủ hơn mà không tốn thêm credit API.
Không gửi toàn bộ tài liệu và không trả API key về trình duyệt.

Nguồn tìm được lưu bằng khóa nội bộ theo tổ chức, nên hai trường cùng tìm thấy một URL không ghi
đè dữ liệu của nhau. Cấu hình một trong hai biến môi trường:

```powershell
$env:TAVILY_API_KEY = '...'
$env:EXA_API_KEY = '...'
$env:WEBSEARCHAPI_API_KEY = '...'
$env:LINKUP_API_KEY = '...'
$env:SERPER_API_KEY = '...'
$env:BRAVE_SEARCH_API_KEY = '...'
```

Tavily được ưu tiên nếu nhiều key cùng tồn tại. Mặc định Tavily dùng `fast`, không yêu cầu tải
`raw_content`, và WebDiscovery trả kết quả hiện có sau ngân sách chờ chung khoảng `22` giây.
Exa fallback dùng `instant` và chỉ lấy `highlights`, không tải toàn văn trang.
WebSearchAPI.ai dùng tìm kiếm cơ bản không tải toàn văn; Linkup dùng `fast` và `searchResults`.
Serper precision chỉ lấy các đoạn tóm tắt kết quả Google và bị khóa tối đa `1` truy vấn cho mỗi báo cáo.
Riêng lượt tự rà của trợ lý Gemini dùng chế độ xác minh sâu: dừng sớm khi đã thấy bản sao toàn bài; nếu chưa,
hệ thống hỏi thêm từng nhà cung cấp đã cấu hình trong ngân sách tối đa `55` giây cho mỗi lượt rà. Chế độ này
có thể dùng thêm quota miễn phí để tăng độ phủ nguồn.
Có thể điều chỉnh giới hạn bằng
`MINH_CHUNG_WEB_DISCOVERY_MAX_QUERIES`, `MINH_CHUNG_WEB_DISCOVERY_MAX_RESULTS` và
`MINH_CHUNG_WEB_DISCOVERY_MAX_CONTENT_CHARS`. Số truy vấn đồng thời dùng
`MINH_CHUNG_WEB_DISCOVERY_PARALLEL_WORKERS`. Chế độ Tavily và thời gian chờ dùng
`MINH_CHUNG_WEB_DISCOVERY_MODE`, `MINH_CHUNG_WEB_DISCOVERY_TIME_BUDGET_SECONDS`,
`MINH_CHUNG_WEB_DISCOVERY_THOROUGH_TIME_BUDGET_SECONDS` và
`MINH_CHUNG_WEB_DISCOVERY_REQUEST_TIMEOUT_SECONDS`. Fallback Exa dùng
`MINH_CHUNG_WEB_DISCOVERY_FALLBACK_MIN_SOURCES`, `MINH_CHUNG_WEB_DISCOVERY_EXA_MAX_QUERIES` và
`MINH_CHUNG_WEB_DISCOVERY_EXA_MODE`. Giới hạn WebSearchAPI.ai và Linkup dùng
`MINH_CHUNG_WEB_DISCOVERY_WEBSEARCHAPI_MAX_QUERIES`, `MINH_CHUNG_WEB_DISCOVERY_LINKUP_MAX_QUERIES` và
`MINH_CHUNG_WEB_DISCOVERY_LINKUP_DEPTH`. Giới hạn Serper dùng
`MINH_CHUNG_WEB_DISCOVERY_SERPER_MAX_QUERIES` và luôn bị chặn ở tối đa `1`.
Giới hạn tải bổ sung trang nguồn công khai dùng `MINH_CHUNG_WEB_DISCOVERY_ENRICHMENT_MAX_SOURCES`.

## Chế độ demo công khai

Đặt `MINH_CHUNG_PUBLIC_MODE=1` cho website mở tự do. Server sẽ ép mọi khách về quyền sinh viên,
không tin header chọn vai trò từ client, khóa API quản trị và không lưu bài nộp hoặc báo cáo.
Deployment có biến `PORT` như Render mặc định bật chế độ này; có thể đặt rõ
`MINH_CHUNG_PUBLIC_MODE=0` cho bản nội bộ. Chế độ cục bộ mặc định vẫn giữ ba vai trò demo để
phát triển và kiểm thử.

## Chế độ chính thức nhỏ gọn

Đặt `DATABASE_URL` bằng connection string Neon, `MINH_CHUNG_PUBLIC_MODE=0` và
`MINH_CHUNG_AUTH_MODE=password`. Người dùng tự đăng ký tài khoản sinh viên; mật khẩu được băm PBKDF2,
phiên đăng nhập dùng cookie `HttpOnly`, và lịch sử báo cáo được lưu trong PostgreSQL Neon.

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

## Optional Gemini query expansion

Set `GEMINI_API_KEY` on the server to let `gemini-3-flash-preview` generate up to `3` additional public-web search queries when an exact source has not already been found. Gemini is tried first because it has a free API tier suitable for small projects. The model improves query coverage only: reported similarity still requires text evidence from indexed source URLs. A stale `GEMINI_MODEL=gemini-3.5-flash` value is automatically migrated to the official `gemini-3-flash-preview` model ID.

When this option is enabled, the server may send up to `12,000` characters from the submitted text to Gemini. Free-tier Gemini API content may be used by Google to improve its products, so do not enable this option for confidential documents. Without `GEMINI_API_KEY`, no text is sent to Gemini and the existing web search flow continues unchanged. Keep the key in Render Environment variables only; do not commit it or include it in a ZIP file.

Optional tuning variables:

```powershell
$env:GEMINI_MODEL = 'gemini-3-flash-preview'
$env:MINH_CHUNG_GEMINI_QUERY_EXPANSION_MAX_QUERIES = '3'
$env:MINH_CHUNG_GEMINI_TIMEOUT_SECONDS = '4'
```

## Citation-aware Gemini writing assistant

When Gemini is configured, a report can open a citation-aware revision assistant. The user must explicitly enable public-web scanning before requesting a revision. The server scans the original draft, asks Gemini to improve clarity and add source markers, scans the proposed revision again, and returns both similarity percentages for review.

The two assistant scans use a bounded thorough verification mode. Unless an exact document match is already found, the server consults each configured public-web provider with small per-provider caps. This can use more free-tier quota than a normal report and has a default budget of up to `55` seconds for each web scan.

The assistant is intentionally not a plagiarism-evasion or AI-detector-evasion tool. It does not claim that generated writing is human-authored or original. It preserves quotations, adds `[Nguồn n]` markers for verified sources, and uses `[Cần trích dẫn nguồn]` when attribution still needs manual work. Turnitin is not called unless a future deployment receives an official licensed API integration.

Optional tuning variables:

```powershell
$env:MINH_CHUNG_GEMINI_REVISION_TIMEOUT_SECONDS = '45'
$env:MINH_CHUNG_GEMINI_REVISION_MAX_INPUT_CHARS = '30000'
```

## Optional OpenAI fallback

Set `OPENAI_API_KEY` on the server to use `gpt-5-nano` as a fallback when Gemini is unavailable or returns no useful expansion queries.

When this option is enabled, the server may send up to `12,000` characters from the submitted text to OpenAI. Without `OPENAI_API_KEY`, no text is sent to OpenAI and the existing web search flow continues unchanged. Keep the key in Render Environment variables only; do not commit it or include it in a ZIP file.

Optional tuning variables:

```powershell
$env:OPENAI_MODEL = 'gpt-5-nano'
$env:MINH_CHUNG_OPENAI_QUERY_EXPANSION_MAX_QUERIES = '3'
$env:MINH_CHUNG_OPENAI_TIMEOUT_SECONDS = '4'
```

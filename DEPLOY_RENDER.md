# Triển khai Minh Chứng trên Render

## Bản chính thức quy mô nhỏ

`render.yaml` cấu hình `MINH_CHUNG_PUBLIC_MODE=0`, `MINH_CHUNG_AUTH_MODE=password` và dùng
PostgreSQL Neon qua biến `DATABASE_URL`. Ở chế độ này:

- Người dùng đăng ký và đăng nhập bằng mật khẩu; mật khẩu chỉ được lưu dưới dạng băm PBKDF2.
- Phiên đăng nhập dùng cookie `HttpOnly`, kéo dài tối đa 7 ngày.
- Tài khoản tự đăng ký có quyền sinh viên, không thể dùng header để giả mạo `admin`.
- Báo cáo, nguồn quét web và lịch sử được lưu trong Neon nên không mất sau khi Render restart.

Khi `DATABASE_URL` có giá trị, ứng dụng cũng tự ưu tiên chế độ chính thức và đăng nhập mật khẩu.
Điều này tránh việc một biến demo cũ còn sót lại trên Render vô tình tắt lưu lịch sử.
- Tùy chọn quét web mặc định tắt; chỉ gửi đoạn trích sang nhà cung cấp tìm kiếm bên ngoài khi khách chủ động bật.
- Serper thử tối đa `1` truy vấn chính xác trước để dừng sớm nếu tìm thấy bản sao toàn bài.
- Tavily dùng `fast`, không lấy toàn bộ nội dung trang và báo cáo thường có ngân sách chờ tối đa `22` giây.
- Exa chỉ chạy fallback khi Tavily thiếu nguồn, dùng `instant`, lấy `highlights` và nhận tối đa `3`
  truy vấn mỗi báo cáo để tiết kiệm quota miễn phí.
- WebSearchAPI.ai và Linkup chỉ chạy fallback nếu tổng nguồn vẫn thiếu; mỗi bên nhận tối đa `1` truy vấn.
- Lượt tự rà của trợ lý Gemini dùng xác minh sâu với ngân sách tối đa `55` giây cho mỗi lượt rà; nếu chưa
  thấy bản sao toàn bài, hệ thống hỏi thêm từng nhà cung cấp đã cấu hình và có thể dùng thêm quota miễn phí.

Tạo Blueprint từ repository chứa file `render.yaml`, sau đó nhập connection string Neon vào `DATABASE_URL`.
Tiếp theo nhập `TAVILY_API_KEY`, `EXA_API_KEY`,
`WEBSEARCHAPI_API_KEY`, `LINKUP_API_KEY`, `SERPER_API_KEY` hoặc `BRAVE_SEARCH_API_KEY` trong phần Environment
của Render. Không đưa API key vào Git hoặc ZIP.

Render cung cấp biến `PORT`; máy chủ đã tự nhận biến này và bind `0.0.0.0`.

`render.yaml` đặt giới hạn upload ứng dụng là `250 MB`. Reverse proxy và bộ nhớ của gói Render
thực tế vẫn có thể áp giới hạn thấp hơn; với file lớn thường xuyên nên dùng object storage và
upload nhiều phần thay vì giữ toàn bộ tệp trong RAM.

## Giới hạn của gói miễn phí

Filesystem của Render free có thể mất dữ liệu sau lần deploy hoặc restart. Vì vậy bản chính thức
không dùng file SQLite trên Render; dữ liệu cần giữ lại được ghi vào Neon.

Để vận hành thật:

1. Dùng OpenSearch cho chỉ mục tìm kiếm khi kho nguồn lớn.
2. Dùng object storage cho nội dung gốc và phiên bản nguồn.
3. Tách crawler sang worker riêng có queue phân tán.
4. Thêm xác minh email, quên mật khẩu và giới hạn số lần đăng nhập sai nếu mở cho nhiều người.

## Bản nội bộ

Không đặt `MINH_CHUNG_PUBLIC_MODE=1` cho bản cần lưu lịch sử. Bản local không có `DATABASE_URL`
vẫn dùng SQLite và header giả lập vai trò để phát triển, còn Render dùng Neon và đăng nhập mật khẩu.

## Optional Gemini query expansion

Add `GEMINI_API_KEY` in Render Environment to enable server-side AI query expansion and the citation-aware revision assistant. Keep the key secret. `GEMINI_MODEL=gemini-3-flash-preview`, `MINH_CHUNG_GEMINI_QUERY_EXPANSION_MAX_QUERIES=3`, `MINH_CHUNG_GEMINI_TIMEOUT_SECONDS=4`, `MINH_CHUNG_GEMINI_REVISION_TIMEOUT_SECONDS=45`, and `MINH_CHUNG_GEMINI_REVISION_MAX_INPUT_CHARS=30000` are configured by the Blueprint. A stale `GEMINI_MODEL=gemini-3.5-flash` value is automatically migrated to the official model ID.

This option sends up to `12,000` characters of submitted text to Gemini only when an exact source has not already been found. It generates additional search queries; similarity percentages still require evidence from indexed source URLs. Free-tier Gemini API content may be used by Google to improve its products, so do not use this option for confidential documents.

The revision assistant can send a submitted draft of up to `30,000` characters to Gemini after the user explicitly asks for a citation-aware revision. It scans the draft and the proposed revision with Minh Chứng. It does not bypass similarity tools or call Turnitin without an official licensed API integration.
The two public-web scans use bounded thorough verification with `MINH_CHUNG_WEB_DISCOVERY_THOROUGH_TIME_BUDGET_SECONDS=55`.

## Optional OpenAI fallback

Add `OPENAI_API_KEY` in Render Environment to use OpenAI only when Gemini is unavailable or returns no useful expansion queries. Keep the key secret. `OPENAI_MODEL=gpt-5-nano`, `MINH_CHUNG_OPENAI_QUERY_EXPANSION_MAX_QUERIES=3`, and `MINH_CHUNG_OPENAI_TIMEOUT_SECONDS=4` are configured by the Blueprint.

This option sends up to `12,000` characters of submitted text to OpenAI only when an exact source has not already been found. It generates additional search queries; similarity percentages still require evidence from indexed source URLs. OpenAI API usage is billed separately from a ChatGPT subscription.

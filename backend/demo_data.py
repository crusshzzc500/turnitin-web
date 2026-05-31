from __future__ import annotations

from .storage import Storage

DEMO_SOURCES = [
    {
        "url": "https://example.edu.vn/hoc-tap-so",
        "title": "Hướng dẫn xây dựng môi trường học tập số",
        "source_type": "chuyên khảo",
        "text_content": (
            "Chuyển đổi số trong giáo dục không chỉ là việc đưa tài liệu lên môi trường trực tuyến. "
            "Quá trình này đòi hỏi nhà trường thiết kế lại trải nghiệm học tập, phương pháp đánh giá "
            "và cách người học tiếp cận tri thức. Dữ liệu cần được sử dụng minh bạch, có mục đích và "
            "tôn trọng quyền riêng tư của người học."
        ),
    },
    {
        "url": "https://library.example.edu.vn/dao-duc-hoc-thuat",
        "title": "Sổ tay về đạo đức học thuật",
        "source_type": "nội bộ",
        "text_content": (
            "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. Người học cần "
            "phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao chép nội dung mà không ghi "
            "nhận nguồn. Báo cáo tương đồng chỉ là công cụ hỗ trợ rà soát, không phải là kết luận tự động "
            "về hành vi đạo văn."
        ),
    },
    {
        "url": "https://journal.example.org/minh-bach-trong-danh-gia",
        "title": "Báo cáo nghiên cứu về đánh giá minh bạch",
        "source_type": "tạp chí",
        "text_content": (
            "Một quy trình đánh giá tốt cần cho phép người đọc truy vết nguồn thông tin và hiểu lý do của "
            "từng cảnh báo. Khi hệ thống chỉ đưa ra một tỷ lệ tổng hợp, người sử dụng dễ bỏ qua bối cảnh "
            "của bài viết. Vì vậy, báo cáo cần kết hợp số liệu với bằng chứng có thể kiểm tra."
        ),
    },
    {
        "url": "https://example.org/quy-tac-viet-hoc-thuat",
        "title": "Quy tắc sử dụng công cụ hỗ trợ viết",
        "source_type": "website",
        "text_content": (
            "Công cụ phân tích văn bản nên giúp người viết cải thiện kỹ năng dẫn nguồn. Kết quả cần chỉ "
            "ra đoạn văn liên quan, nguồn có khả năng trùng lặp và mức độ cần xem xét. Quyền quyết định "
            "cuối cùng vẫn thuộc về người đánh giá."
        ),
    },
]


def seed_demo_sources(storage: Storage) -> None:
    if storage.stats()["sources"]:
        return
    for source in DEMO_SOURCES:
        storage.upsert_source(**source)


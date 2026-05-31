from __future__ import annotations

import json
import base64
import io
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.analysis import SimilarityAnalyzer
from backend.config import Settings
from backend.crawler import Crawler
from backend.demo_data import seed_demo_sources
from backend.extractors import extract_document
from backend.search import OpenSearchBackend
from backend.server import create_server
from backend.storage import Storage, utc_now


class LocalSiteHandler(BaseHTTPRequestHandler):
    flaky_hits = 0

    def do_GET(self) -> None:
        base = f"http://{self.headers['Host']}"
        if self.path == "/flaky":
            type(self).flaky_hits += 1
            if type(self).flaky_hits < 3:
                body = "temporary server error"
                payload = body.encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
        if self.path == "/always-fail":
            body = "persistent server error"
            payload = body.encode("utf-8")
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        pages = {
            "/robots.txt": (
                "text/plain",
                "User-agent: *\nAllow: /allowed\nAllow: /next\nAllow: /flaky\nAllow: /always-fail\nDisallow: /blocked\n",
            ),
            "/allowed": (
                "text/html",
                """
                <html><head><title>Nguồn được phép</title></head>
                <body>
                  <article>
                    <h1>Nguồn công khai</h1>
                    <p>Nội dung công khai đủ dài để crawler lập chỉ mục phục vụ việc đối chiếu tài liệu học thuật.</p>
                    <a href="/next">Trang kế tiếp</a>
                    <a href="/blocked">Trang bị chặn</a>
                  </article>
                </body></html>
                """,
            ),
            "/next": (
                "text/html",
                """
                <html><head><title>Nguồn kế tiếp</title></head>
                <body><p>Trang kế tiếp cũng có nội dung công khai đủ dài để được đưa vào chỉ mục tìm kiếm văn bản.</p></body>
                </html>
                """,
            ),
            "/blocked": (
                "text/html",
                "<html><body><p>Nội dung này không được phép thu thập theo robots.txt và không được lập chỉ mục.</p></body></html>",
            ),
            "/flaky": (
                "text/html",
                """
                <html><head><title>Nguồn hồi phục</title></head>
                <body><p>Nguồn này hồi phục sau lỗi tạm thời và có đủ nội dung để được lập chỉ mục tìm kiếm.</p></body></html>
                """,
            ),
            "/sitemap.xml": (
                "application/xml",
                f"""
                <?xml version="1.0" encoding="UTF-8"?>
                <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>{base}/allowed</loc></url>
                  <url><loc>{base}/next</loc></url>
                </urlset>
                """.strip(),
            ),
        }
        content_type, body = pages.get(self.path, ("text/plain", "not found"))
        status = 200 if self.path in pages else 404
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


class FakeOpenSearchHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def do_GET(self) -> None:
        self._record_and_send({"cluster_name": "minh-chung-test"})

    def do_PUT(self) -> None:
        self._record_and_send({"acknowledged": True})

    def do_POST(self) -> None:
        if self.path.endswith("/_search"):
            self._record_and_send(
                {
                    "hits": {
                        "hits": [
                            {
                                "_source": {
                                    "chunk_id": 1,
                                    "text_content": "Nội dung OpenSearch thử nghiệm",
                                    "token_count": 4,
                                    "source_id": 9,
                                    "url": "https://example.org/opensearch",
                                    "title": "Nguồn OpenSearch",
                                    "source_type": "website",
                                }
                            }
                        ]
                    }
                }
            )
            return
        self._record_and_send({"acknowledged": True})

    def _record_and_send(self, response: dict) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        type(self).requests.append({"method": self.command, "path": self.path, "body": body})
        payload = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args) -> None:
        return


def settings_for(
    root: Path,
    *,
    port: int = 0,
    allow_private: bool = False,
    max_attempts: int = 3,
    retry_base_seconds: float = 0,
) -> Settings:
    return Settings(
        root_dir=root,
        database_path=root / "test.db",
        static_dir=ROOT,
        host="127.0.0.1",
        port=port,
        crawler_delay_seconds=0,
        crawler_timeout_seconds=3,
        crawler_allow_private_hosts=allow_private,
        crawler_max_attempts=max_attempts,
        crawler_retry_base_seconds=retry_base_seconds,
    )


class SimilarityAnalyzerTest(unittest.TestCase):
    def test_finds_matching_source_and_integrity_flag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "test.db")
            seed_demo_sources(storage)
            report = SimilarityAnalyzer(storage).analyze(
                "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. "
                "Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao "
                "chép nội dung mà không ghi nhận nguồn. Ký tự thử nghiệm a\u200bb."
            )
            self.assertGreater(report["percent"], 70)
            self.assertEqual(report["sources"][0]["title"], "Sổ tay về đạo đức học thuật")
            self.assertEqual(report["integrityFlags"][0]["kind"], "zero_width_characters")

    def test_manual_source_is_added_to_search_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "test.db")
            storage.upsert_source(
                url="manual://source/test",
                title="Nguồn tự thêm",
                source_type="tự thêm",
                text_content="Nguồn tự thêm có đủ nội dung để được lập chỉ mục và tìm kiếm trong kho dữ liệu.",
            )
            self.assertEqual(storage.stats()["sources"], 1)
            self.assertGreater(storage.stats()["chunks"], 0)

    def test_source_versions_preserve_previous_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "test.db")
            source_id = storage.upsert_source(
                url="https://example.org/versioned",
                title="Nguồn phiên bản",
                text_content="Phiên bản đầu tiên có đủ nội dung để được ghi nhận trong lịch sử nguồn dữ liệu.",
            )
            storage.upsert_source(
                url="https://example.org/versioned",
                title="Nguồn phiên bản đã sửa",
                text_content="Phiên bản thứ hai đã thay đổi và vẫn được ghi nhận trong lịch sử nguồn dữ liệu.",
            )
            storage.upsert_source(
                url="https://example.org/versioned",
                title="Nguồn phiên bản đã sửa",
                text_content="Phiên bản thứ hai đã thay đổi và vẫn được ghi nhận trong lịch sử nguồn dữ liệu.",
            )
            versions = storage.list_source_versions(source_id)
            self.assertEqual(storage.stats()["source_versions"], 2)
            self.assertEqual([item["version_number"] for item in versions], [2, 1])
            self.assertEqual(versions[0]["title"], "Nguồn phiên bản đã sửa")

    def test_existing_sources_are_backfilled_with_initial_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.db"
            connection = sqlite3.connect(database)
            connection.execute(
                """
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    canonical_url TEXT,
                    title TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'website',
                    text_content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    fetched_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO sources(
                    url, title, text_content, content_hash, word_count,
                    fetched_at, created_at, updated_at
                )
                VALUES ('https://example.org/legacy', 'Nguồn cũ', 'Nội dung cũ', 'legacy-hash', 3,
                        '2026-01-01', '2026-01-01', '2026-01-01')
                """
            )
            connection.commit()
            connection.close()
            storage = Storage(database)
            self.assertEqual(storage.stats()["source_versions"], 1)
            self.assertEqual(storage.list_source_versions(1)[0]["title"], "Nguồn cũ")


class SearchBackendTest(unittest.TestCase):
    def test_opensearch_adapter_indexes_deletes_searches_and_reports_status(self) -> None:
        FakeOpenSearchHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenSearchHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = OpenSearchBackend(f"http://127.0.0.1:{server.server_address[1]}", "chunks-test")
            backend.replace_source(
                9,
                [
                    {
                        "chunk_id": 1,
                        "text_content": "Nội dung OpenSearch thử nghiệm",
                        "normalized_text": "nội dung opensearch thử nghiệm",
                        "folded_text": "noi dung opensearch thu nghiem",
                        "token_count": 4,
                        "source_id": 9,
                        "url": "https://example.org/opensearch",
                        "title": "Nguồn OpenSearch",
                        "source_type": "website",
                    }
                ],
            )
            matches = backend.search_chunks("Nội dung OpenSearch thử nghiệm")
            status = backend.status()
            paths = [item["path"] for item in FakeOpenSearchHandler.requests]
            self.assertEqual(matches[0]["source_id"], 9)
            self.assertEqual(status["clusterName"], "minh-chung-test")
            self.assertIn("/chunks-test", paths)
            self.assertTrue(any(path.startswith("/chunks-test/_delete_by_query") for path in paths))
            self.assertIn("/_bulk", paths)
            self.assertIn("/chunks-test/_search", paths)
        finally:
            server.shutdown()
            server.server_close()


class ExtractorTest(unittest.TestCase):
    def test_pdf_with_little_embedded_text_uses_optional_ocr_fallback(self) -> None:
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf is not installed")

        stream = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=300, height=300)
        writer.write(stream)
        ocr_text = (
            "Nội dung OCR thử nghiệm có đủ số lượng từ để chứng minh rằng PDF scan "
            "được chuyển sang văn bản trước khi tạo báo cáo tương đồng cho người dùng."
        )
        with patch(
            "backend.extractors.extract_pdf_text_with_ocr",
            return_value={"text": ocr_text, "metadata": {"attempted": True, "available": True}},
        ):
            extracted = extract_document("scan.pdf", stream.getvalue())
        self.assertEqual(extracted["text"], ocr_text)
        self.assertTrue(extracted["metadata"]["ocr"]["attempted"])


class CrawlerTest(unittest.TestCase):
    def test_respects_robots_txt_and_indexes_allowed_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = ThreadingHTTPServer(("127.0.0.1", 0), LocalSiteHandler)
            thread = threading.Thread(target=site.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(directory)
                storage = Storage(root / "test.db")
                crawler = Crawler(storage, settings_for(root, allow_private=True))
                base = f"http://127.0.0.1:{site.server_address[1]}"
                crawler.enqueue(f"{base}/allowed")
                result = crawler.crawl_queued(max_pages=3, max_depth=1)
                urls = {source["url"] for source in storage.list_sources()}
                self.assertEqual(result["indexed"], 2)
                self.assertEqual(result["skipped"], 1)
                self.assertIn(f"{base}/allowed", urls)
                self.assertIn(f"{base}/next", urls)
                self.assertNotIn(f"{base}/blocked", urls)
            finally:
                site.shutdown()
                site.server_close()

    def test_rejects_private_hosts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "test.db")
            crawler = Crawler(storage, settings_for(Path(directory)))
            with self.assertRaises(ValueError):
                crawler.enqueue("http://127.0.0.1/private")

    def test_enqueues_pages_from_xml_sitemap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = ThreadingHTTPServer(("127.0.0.1", 0), LocalSiteHandler)
            thread = threading.Thread(target=site.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(directory)
                storage = Storage(root / "test.db")
                crawler = Crawler(storage, settings_for(root, allow_private=True))
                base = f"http://127.0.0.1:{site.server_address[1]}"
                result = crawler.enqueue_sitemap(f"{base}/sitemap.xml")
                self.assertEqual(result["sitemaps"], 1)
                self.assertEqual(result["queued"], 2)
                self.assertEqual(storage.stats()["crawl_queue"]["queued"], 2)
            finally:
                site.shutdown()
                site.server_close()

    def test_retries_temporary_server_errors_until_page_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            LocalSiteHandler.flaky_hits = 0
            site = ThreadingHTTPServer(("127.0.0.1", 0), LocalSiteHandler)
            thread = threading.Thread(target=site.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(directory)
                storage = Storage(root / "test.db")
                crawler = Crawler(storage, settings_for(root, allow_private=True))
                base = f"http://127.0.0.1:{site.server_address[1]}"
                crawler.enqueue(f"{base}/flaky")
                result = crawler.crawl_queued(max_pages=3, max_depth=0)
                operations = storage.crawl_operations()
                self.assertEqual(result["retryScheduled"], 2)
                self.assertEqual(result["indexed"], 1)
                self.assertEqual(operations["queue"]["indexed"], 1)
                self.assertEqual(operations["recent"][0]["attempts"], 3)
            finally:
                site.shutdown()
                site.server_close()

    def test_failed_url_can_be_requeued_manually(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            site = ThreadingHTTPServer(("127.0.0.1", 0), LocalSiteHandler)
            thread = threading.Thread(target=site.serve_forever, daemon=True)
            thread.start()
            try:
                root = Path(directory)
                storage = Storage(root / "test.db")
                crawler = Crawler(storage, settings_for(root, allow_private=True, max_attempts=2))
                base = f"http://127.0.0.1:{site.server_address[1]}"
                crawler.enqueue(f"{base}/always-fail")
                result = crawler.crawl_queued(max_pages=2, max_depth=0)
                self.assertEqual(result["retryScheduled"], 1)
                self.assertEqual(result["failed"], 1)
                self.assertEqual(storage.stats()["crawl_queue"]["failed"], 1)
                self.assertEqual(storage.requeue_failed_urls(), 1)
                self.assertEqual(storage.stats()["crawl_queue"]["queued"], 1)
            finally:
                site.shutdown()
                site.server_close()


class ApiTest(unittest.TestCase):
    def test_health_stats_and_analysis_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                health = self._json(f"{base}/api/health")
                stats = self._json(f"{base}/api/stats")
                search_status = self._json(f"{base}/api/search/status")
                reindex = self._json(f"{base}/api/search/reindex", method="POST", payload={})
                report = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={
                        "text": (
                            "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. "
                            "Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao "
                            "chép nội dung mà không ghi nhận nguồn."
                        )
                    },
                )
                self.assertTrue(health["ok"])
                self.assertEqual(health["searchBackend"], "sqlite-fts5")
                self.assertEqual(search_status["backend"], "sqlite-fts5")
                self.assertEqual(reindex["chunks"], 20)
                self.assertEqual(stats["sources"], 4)
                self.assertGreater(report["percent"], 70)
                self.assertTrue(report["reportId"])
            finally:
                server.shutdown()
                server.server_close()

    def test_docx_upload_extracts_text_and_metadata(self) -> None:
        try:
            from docx import Document
        except ImportError:
            self.skipTest("python-docx is not installed")

        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                document = Document()
                document.core_properties.author = "Minh Chung QA"
                document.add_paragraph(
                    "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. "
                    "Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao "
                    "chép nội dung mà không ghi nhận nguồn."
                )
                stream = io.BytesIO()
                document.save(stream)
                report = self._json(
                    f"http://127.0.0.1:{server.server_address[1]}/api/analyze-upload",
                    method="POST",
                    payload={
                        "filename": "kiem-tra.docx",
                        "contentBase64": base64.b64encode(stream.getvalue()).decode("ascii"),
                    },
                )
                self.assertGreater(report["percent"], 70)
                self.assertEqual(report["documentMetadata"]["author"], "Minh Chung QA")
            finally:
                server.shutdown()
                server.server_close()

    def test_opt_in_submission_becomes_internal_comparison_source_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                text = (
                    "Đây là bài nộp nội bộ thử nghiệm với nội dung riêng biệt để kiểm tra cơ chế đồng ý "
                    "lập chỉ mục cho những lần đối chiếu tiếp theo trong cùng một tổ chức giáo dục."
                )
                first = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={"text": text, "indexForComparison": True},
                )
                second = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={"text": text, "indexForComparison": True},
                )
                stats = self._json(f"{base}/api/stats")
                submissions = self._json(f"{base}/api/submissions")
                self.assertEqual(first["submissionId"], second["submissionId"])
                self.assertGreater(second["percent"], 90)
                self.assertEqual(second["sources"][0]["type"], "bài nộp nội bộ")
                self.assertEqual(stats["indexed_submissions"], 1)
                self.assertEqual(len(submissions["submissions"]), 1)
                deleted = self._json(f"{base}/api/submissions/{first['submissionId']}", method="DELETE")
                stats_after_delete = self._json(f"{base}/api/stats")
                self.assertTrue(deleted["ok"])
                self.assertEqual(stats_after_delete["indexed_submissions"], 0)
                self.assertEqual(stats_after_delete["sources"], 4)
            finally:
                server.shutdown()
                server.server_close()

    def test_operations_retry_and_source_version_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                source = self._json(
                    f"{base}/api/sources",
                    method="POST",
                    payload={
                        "title": "Nguồn API có phiên bản",
                        "url": "https://example.org/api-version",
                        "content": "Nguồn API có đủ nội dung để tạo phiên bản và kiểm tra endpoint lịch sử dữ liệu.",
                    },
                )
                versions = self._json(f"{base}/api/sources/{source['sourceId']}/versions")
                storage = server.context.storage  # type: ignore[attr-defined]
                storage.enqueue_url("https://example.org/failed")
                claimed = storage.claim_next_url()
                storage.finish_crawl(claimed["id"], "failed", "Lỗi thử nghiệm")
                operations = self._json(f"{base}/api/crawl/operations")
                retry = self._json(f"{base}/api/crawl/retry", method="POST", payload={"limit": 10})
                self.assertEqual(len(versions["versions"]), 1)
                self.assertEqual(operations["queue"]["failed"], 1)
                self.assertEqual(retry["requeued"], 1)
            finally:
                server.shutdown()
                server.server_close()

    def test_pdf_export_ocr_status_and_audit_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                report = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={
                        "text": (
                            "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. "
                            "Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao "
                            "chép nội dung mà không ghi nhận nguồn."
                        )
                    },
                )
                pdf = self._raw(f"{base}/api/reports/{report['reportId']}/pdf")
                ocr = self._json(f"{base}/api/ocr/status")
                audit = self._json(f"{base}/api/audit")
                self.assertTrue(pdf.startswith(b"%PDF"))
                self.assertIn("available", ocr)
                self.assertIn("reason", ocr)
                self.assertIn("report.export_pdf", {event["action"] for event in audit["events"]})
            finally:
                server.shutdown()
                server.server_close()

    def test_roles_and_organizations_isolate_private_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                private_text = (
                    "Cụm từ tenant biệt lập alpha beta gamma delta chỉ thuộc kho nội bộ của trường "
                    "Minh Chứng và được dùng để xác minh ranh giới dữ liệu giữa các tổ chức."
                )
                source = self._json(
                    f"{base}/api/sources",
                    method="POST",
                    payload={"title": "Nguồn riêng trường Minh Chứng", "content": private_text},
                    headers={"X-Minh-Chung-User": "demo-instructor"},
                )
                same_org = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={"text": private_text},
                    headers={"X-Minh-Chung-User": "demo-student"},
                )
                with server.context.storage.connect() as connection:  # type: ignore[attr-defined]
                    cursor = connection.execute(
                        "INSERT INTO organizations(slug, name, created_at) VALUES (?, ?, ?)",
                        ("other-school", "Trường Khác", utc_now()),
                    )
                    other_organization_id = int(cursor.lastrowid)
                    connection.execute(
                        """
                        INSERT INTO users(organization_id, username, display_name, role, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (other_organization_id, "other-student", "Sinh viên Trường Khác", "student", utc_now()),
                    )
                other_sources = self._json(
                    f"{base}/api/sources",
                    headers={"X-Minh-Chung-User": "other-student"},
                )
                other_org = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={"text": private_text},
                    headers={"X-Minh-Chung-User": "other-student"},
                )
                with self.assertRaises(HTTPError) as error:
                    self._json(
                        f"{base}/api/crawl/operations",
                        headers={"X-Minh-Chung-User": "demo-student"},
                    )
                self.assertEqual(error.exception.code, 403)
                self.assertTrue(source["sourceId"])
                self.assertIn("Nguồn riêng trường Minh Chứng", {item["title"] for item in same_org["sources"]})
                self.assertNotIn(
                    "Nguồn riêng trường Minh Chứng",
                    {item["title"] for item in other_sources["sources"]},
                )
                self.assertNotIn("Nguồn riêng trường Minh Chứng", {item["title"] for item in other_org["sources"]})
            finally:
                server.shutdown()
                server.server_close()

    @staticmethod
    def _json(
        url: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        content = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        request = Request(
            url,
            method=method,
            data=content,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _raw(url: str, *, headers: dict[str, str] | None = None) -> bytes:
        request = Request(url, headers=headers or {})
        with urlopen(request, timeout=5) as response:
            return response.read()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import base64
import io
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.analysis import SimilarityAnalyzer
from backend.config import Settings
from backend.crawler import Crawler
from backend.demo_data import seed_demo_sources
from backend.extractors import extract_document
from backend.jobs import AnalysisJobManager
from backend.search import OpenSearchBackend
from backend.server import create_server
from backend.storage import Storage, utc_now
from backend.text import normalize_display_text
from backend.web_discovery import DiscoveryResult, WebDiscovery, build_queries


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
    tavily_api_key: str = "",
    exa_api_key: str = "",
    websearchapi_api_key: str = "",
    linkup_api_key: str = "",
    serper_api_key: str = "",
    public_mode: bool = False,
    auth_mode: str = "demo",
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
        tavily_api_key=tavily_api_key,
        exa_api_key=exa_api_key,
        websearchapi_api_key=websearchapi_api_key,
        linkup_api_key=linkup_api_key,
        serper_api_key=serper_api_key,
        public_mode=public_mode,
        auth_mode=auth_mode,
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


class ConfigTest(unittest.TestCase):
    def test_render_port_enables_external_bind_and_public_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PORT": "9123"}, clear=True):
                settings = Settings.from_env(Path(directory))
            self.assertEqual(settings.host, "0.0.0.0")
            self.assertEqual(settings.port, 9123)
            self.assertTrue(settings.public_mode)

    def test_platform_public_mode_can_be_explicitly_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PORT": "9123", "MINH_CHUNG_PUBLIC_MODE": "0"}, clear=True):
                settings = Settings.from_env(Path(directory))
            self.assertFalse(settings.public_mode)


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


class WebDiscoveryTest(unittest.TestCase):
    def test_websearchapi_uses_basic_search_without_content_with_server_side_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, websearchapi_api_key="websearch-test-key"), storage)
            captured: dict = {}

            def fake_request(url, payload, *, headers, timeout):
                captured.update({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
                return {"organic": []}

            with patch.object(WebDiscovery, "_json_request", side_effect=fake_request):
                discovery._fetch_websearchapi("academic integrity", 10)
            self.assertEqual(captured["url"], "https://api.websearchapi.ai/ai-search")
            self.assertFalse(captured["payload"]["includeContent"])
            self.assertFalse(captured["payload"]["includeAnswer"])
            self.assertEqual(captured["headers"]["Authorization"], "Bearer websearch-test-key")
            self.assertEqual(captured["timeout"], 45.0)

    def test_linkup_uses_fast_search_results_with_server_side_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, linkup_api_key="linkup-test-key"), storage)
            captured: dict = {}

            def fake_request(url, payload, *, headers, timeout):
                captured.update({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
                return {"results": []}

            with patch.object(WebDiscovery, "_json_request", side_effect=fake_request):
                discovery._fetch_linkup("academic integrity", 10)
            self.assertEqual(captured["url"], "https://api.linkup.so/v1/search")
            self.assertEqual(captured["payload"]["depth"], "fast")
            self.assertEqual(captured["payload"]["outputType"], "searchResults")
            self.assertEqual(captured["headers"]["Authorization"], "Bearer linkup-test-key")
            self.assertEqual(captured["timeout"], 45.0)

    def test_serper_uses_one_query_shape_with_server_side_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, serper_api_key="serper-test-key"), storage)
            captured: dict = {}

            def fake_request(url, payload, *, headers, timeout):
                captured.update({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
                return {"organic": []}

            with patch.object(WebDiscovery, "_json_request", side_effect=fake_request):
                discovery._fetch_serper("academic integrity", 10)
            self.assertEqual(captured["url"], "https://google.serper.dev/search")
            self.assertEqual(captured["payload"], {"q": "academic integrity", "num": 10})
            self.assertEqual(captured["headers"]["X-API-KEY"], "serper-test-key")
            self.assertEqual(captured["timeout"], 45.0)

    def test_serper_hard_caps_queries_even_if_called_with_more_than_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, serper_api_key="serper-test-key"), storage)
            with patch.object(discovery, "_fetch_serper", return_value={"organic": []}) as fetch:
                result = discovery._serper(["one", "two", "three"], organization_id=1, max_results=10)
            self.assertEqual(result.queries, ["one"])
            fetch.assert_called_once_with("one", 10)

    def test_new_fallbacks_hard_cap_queries_even_if_called_with_more_than_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(
                settings_for(root, websearchapi_api_key="websearch", linkup_api_key="linkup"),
                storage,
            )
            with (
                patch.object(discovery, "_fetch_websearchapi", return_value={"organic": []}) as websearch,
                patch.object(discovery, "_fetch_linkup", return_value={"results": []}) as linkup,
            ):
                websearch_result = discovery._websearchapi(["one", "two"], organization_id=1, max_results=10)
                linkup_result = discovery._linkup(["one", "two"], organization_id=1, max_results=10)
            self.assertEqual(websearch_result.queries, ["one"])
            self.assertEqual(linkup_result.queries, ["one"])
            websearch.assert_called_once_with("one", 10)
            linkup.assert_called_once_with("one", 10)

    def test_exa_uses_instant_search_with_highlights_and_server_side_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, exa_api_key="exa-test-key"), storage)
            captured: dict = {}

            def fake_request(_url, payload, *, headers, timeout):
                captured.update({"payload": payload, "headers": headers, "timeout": timeout})
                return {"results": []}

            with patch.object(WebDiscovery, "_json_request", side_effect=fake_request):
                discovery._fetch_exa("liêm chính học thuật", 10)
            self.assertEqual(captured["payload"]["type"], "instant")
            self.assertEqual(captured["payload"]["numResults"], 10)
            self.assertEqual(captured["payload"]["contents"]["highlights"]["maxCharacters"], 1200)
            self.assertEqual(captured["headers"]["x-api-key"], "exa-test-key")
            self.assertEqual(captured["timeout"], 45.0)

    def test_exa_fallback_runs_only_when_tavily_returns_too_few_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, tavily_api_key="tavily", exa_api_key="exa"), storage)
            text = (
                "Đoạn đầu tiên có đủ số lượng từ và chứa nội dung riêng để dùng làm truy vấn tìm kiếm công khai. "
                "Đoạn thứ hai cũng có đủ số lượng từ nhưng mang thêm nhiều thuật ngữ học thuật khác nhau để kiểm tra. "
                "Đoạn thứ ba tiếp tục bổ sung nội dung nhằm chắc chắn bộ chọn không gửi toàn bộ tài liệu ra bên ngoài."
            )
            primary = DiscoveryResult("tavily", True, True, ["primary"], 0, 0, "Tavily thiếu nguồn.", [])
            fallback = DiscoveryResult(
                "exa",
                True,
                True,
                ["fallback"],
                1,
                0,
                "Exa bổ sung nguồn.",
                [{"id": 9, "title": "Nguồn Exa", "url": "https://example.org/exa"}],
            )
            with (
                patch.object(discovery, "_tavily", return_value=primary),
                patch.object(discovery, "_exa", return_value=fallback) as exa,
            ):
                result = discovery.discover_and_index(text, organization_id=1)
            self.assertEqual(result["provider"], "tavily+exa")
            self.assertEqual(result["indexed"], 1)
            self.assertLessEqual(len(exa.call_args.args[0]), 3)

    def test_exa_fallback_is_skipped_when_tavily_has_enough_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(
                settings_for(root, tavily_api_key="tavily", exa_api_key="exa", serper_api_key="serper"),
                storage,
            )
            text = "Nội dung đủ dài để tạo truy vấn kiểm tra và xác minh bộ điều phối không gọi Exa khi Tavily đã đủ nguồn."
            sources = [
                {"id": index, "title": f"Nguồn {index}", "url": f"https://example.org/{index}"}
                for index in range(8)
            ]
            primary = DiscoveryResult("tavily", True, True, ["primary"], 8, 0, "Tavily đủ nguồn.", sources)
            with (
                patch.object(discovery, "_tavily", return_value=primary),
                patch.object(discovery, "_exa") as exa,
                patch.object(discovery, "_serper") as serper,
            ):
                result = discovery.discover_and_index(text, organization_id=1)
            self.assertEqual(result["provider"], "tavily")
            exa.assert_not_called()
            serper.assert_not_called()

    def test_serper_fallback_runs_after_tavily_and_exa_still_have_too_few_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(
                settings_for(root, tavily_api_key="tavily", exa_api_key="exa", serper_api_key="serper"),
                storage,
            )
            text = "This sufficiently long excerpt exists to verify the final public web search fallback provider."
            tavily = DiscoveryResult("tavily", True, True, ["primary"], 0, 0, "Tavily empty.", [])
            exa = DiscoveryResult(
                "exa",
                True,
                True,
                ["fallback-exa"],
                1,
                0,
                "Exa added one source.",
                [{"id": 9, "title": "Exa source", "url": "https://example.org/exa"}],
            )
            serper_result = DiscoveryResult(
                "serper",
                True,
                True,
                ["fallback-serper"],
                1,
                0,
                "Serper added one source.",
                [{"id": 10, "title": "Serper source", "url": "https://example.org/serper"}],
            )
            with (
                patch.object(discovery, "_tavily", return_value=tavily),
                patch.object(discovery, "_exa", return_value=exa),
                patch.object(discovery, "_serper", return_value=serper_result) as serper,
            ):
                result = discovery.discover_and_index(text, organization_id=1)
            self.assertEqual(result["provider"], "tavily+exa+serper")
            self.assertEqual(result["indexed"], 2)
            self.assertLessEqual(len(serper.call_args.args[0]), 1)

    def test_new_fallbacks_run_between_exa_and_serper_when_sources_are_still_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(
                settings_for(
                    root,
                    tavily_api_key="tavily",
                    exa_api_key="exa",
                    websearchapi_api_key="websearch",
                    linkup_api_key="linkup",
                    serper_api_key="serper",
                ),
                storage,
            )
            text = "This sufficiently long excerpt verifies the complete quota saving public web fallback chain."
            calls: list[str] = []

            def result(provider: str, url: str) -> DiscoveryResult:
                return DiscoveryResult(
                    provider,
                    True,
                    True,
                    [provider],
                    1,
                    0,
                    f"{provider} source.",
                    [{"id": len(calls), "title": provider, "url": url}],
                )

            with (
                patch.object(discovery, "_tavily", side_effect=lambda *args: (calls.append("tavily"), result("tavily", "https://example.org/tavily"))[1]),
                patch.object(discovery, "_exa", side_effect=lambda *args, **kwargs: (calls.append("exa"), result("exa", "https://example.org/exa"))[1]),
                patch.object(discovery, "_websearchapi", side_effect=lambda *args, **kwargs: (calls.append("websearchapi"), result("websearchapi", "https://example.org/websearchapi"))[1]) as websearch,
                patch.object(discovery, "_linkup", side_effect=lambda *args, **kwargs: (calls.append("linkup"), result("linkup", "https://example.org/linkup"))[1]) as linkup,
                patch.object(discovery, "_serper", side_effect=lambda *args, **kwargs: (calls.append("serper"), result("serper", "https://example.org/serper"))[1]) as serper,
            ):
                result_payload = discovery.discover_and_index(text, organization_id=1)
            self.assertEqual(calls, ["tavily", "exa", "websearchapi", "linkup", "serper"])
            self.assertEqual(result_payload["provider"], "tavily+exa+websearchapi+linkup+serper")
            self.assertLessEqual(len(websearch.call_args.args[0]), 1)
            self.assertLessEqual(len(linkup.call_args.args[0]), 1)
            self.assertLessEqual(len(serper.call_args.args[0]), 1)

    def test_tavily_uses_fast_snippets_without_raw_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, tavily_api_key="test-key"), storage)
            captured: dict = {}

            def fake_request(_url, payload, *, headers, timeout):
                captured.update({"payload": payload, "headers": headers, "timeout": timeout})
                return {"results": []}

            with patch.object(WebDiscovery, "_json_request", side_effect=fake_request):
                discovery._fetch_tavily("liêm chính học thuật", 10)
            self.assertEqual(captured["payload"]["search_depth"], "fast")
            self.assertFalse(captured["payload"]["include_raw_content"])
            self.assertEqual(captured["timeout"], 45.0)

    def test_build_queries_selects_a_small_number_of_excerpts(self) -> None:
        text = (
            "Đoạn đầu tiên có đủ số lượng từ và chứa nội dung riêng để dùng làm truy vấn tìm kiếm công khai. "
            "Đoạn thứ hai cũng có đủ số lượng từ nhưng mang thêm nhiều thuật ngữ học thuật khác nhau để kiểm tra. "
            "Đoạn thứ ba tiếp tục bổ sung nội dung nhằm chắc chắn bộ chọn không gửi toàn bộ tài liệu ra bên ngoài."
        )
        queries = build_queries(text, max_queries=2)
        self.assertEqual(len(queries), 2)
        self.assertTrue(all(len(query) <= 360 for query in queries))

    def test_tavily_results_are_namespaced_per_organization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            discovery = WebDiscovery(settings_for(root, tavily_api_key="test-key"), storage)
            content = (
                "Nguồn Tavily công khai có nội dung đủ dài để được lập chỉ mục cho việc kiểm tra tương đồng. "
                "Dữ liệu này lặp lại một số cụm từ mô phỏng bài viết học thuật và giúp xác minh cách lưu nguồn "
                "riêng theo từng tổ chức mà không ghi đè hoặc làm rò rỉ dữ liệu giữa hai trường khác nhau. "
                "Phần bổ sung bảo đảm văn bản vượt qua ngưỡng tối thiểu bốn mươi từ của lớp tìm kiếm web."
            )
            response = {"results": [{"url": "https://example.org/shared", "title": "Nguồn chung", "raw_content": content}]}
            with storage.connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO organizations(slug, name, created_at) VALUES (?, ?, ?)",
                    ("other-school", "Trường Khác", utc_now()),
                )
                second_organization_id = int(cursor.lastrowid)
            with patch.object(WebDiscovery, "_json_request", return_value=response):
                first = discovery.discover_and_index(content, organization_id=1)
                second = discovery.discover_and_index(content, organization_id=second_organization_id)
            self.assertEqual(first["indexed"], 1)
            self.assertEqual(second["indexed"], 1)
            self.assertNotEqual(first["sources"][0]["id"], second["sources"][0]["id"])
            with storage.connect() as connection:
                urls = {
                    row["organization_id"]: row["url"]
                    for row in connection.execute(
                        "SELECT organization_id, url FROM sources WHERE source_type = 'web-tavily'"
                    )
                }
            self.assertTrue(urls[1].startswith("web-discovery://1/"))
            self.assertTrue(urls[second_organization_id].startswith(f"web-discovery://{second_organization_id}/"))

    def test_tavily_queries_run_in_parallel_and_report_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            settings = replace(
                settings_for(root, tavily_api_key="test-key"),
                web_discovery_max_queries=3,
                web_discovery_parallel_workers=3,
            )
            discovery = WebDiscovery(settings, storage)
            text = (
                "Đoạn đầu tiên có đủ số lượng từ riêng biệt để làm truy vấn tìm kiếm công khai cho tài liệu. "
                "Đoạn thứ hai bổ sung nhiều thuật ngữ học thuật khác nhau nhằm kiểm tra xử lý tìm nguồn đồng thời. "
                "Đoạn thứ ba tiếp tục cung cấp nội dung độc lập để xác minh tiến trình quét web được cập nhật."
            )
            active = 0
            max_active = 0
            lock = threading.Lock()
            updates: list[tuple[int, int, int]] = []

            def fake_request(*_args, **_kwargs) -> dict:
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.08)
                    return {"results": []}
                finally:
                    with lock:
                        active -= 1

            with patch.object(WebDiscovery, "_json_request", side_effect=fake_request):
                result = discovery.discover_and_index(
                    text,
                    organization_id=1,
                    progress_callback=lambda completed, total, indexed: updates.append((completed, total, indexed)),
                )
            self.assertGreaterEqual(max_active, 2)
            self.assertEqual(result["provider"], "tavily")
            self.assertEqual(updates[-1][:2], (3, 3))

    def test_tavily_returns_partial_results_after_time_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            storage = Storage(root / "test.db")
            settings = replace(
                settings_for(root, tavily_api_key="test-key"),
                web_discovery_max_queries=3,
                web_discovery_parallel_workers=3,
                web_discovery_time_budget_seconds=0.03,
            )
            discovery = WebDiscovery(settings, storage)
            text = (
                "Đoạn thứ nhất có đủ từ riêng biệt để tạo truy vấn tìm kiếm công khai và đo thời gian phản hồi. "
                "Đoạn thứ hai bổ sung thuật ngữ khác nhau nhằm tạo thêm truy vấn tìm nguồn chạy song song. "
                "Đoạn thứ ba tiếp tục cung cấp nội dung độc lập để xác minh giới hạn chờ được áp dụng."
            )

            def slow_request(*_args, **_kwargs) -> dict:
                time.sleep(0.15)
                return {"results": []}

            started = time.monotonic()
            with patch.object(WebDiscovery, "_json_request", side_effect=slow_request):
                result = discovery.discover_and_index(text, organization_id=1)
            self.assertLess(time.monotonic() - started, 0.12)
            self.assertIn("Đã dừng chờ", result["message"])


class TextDisplayTest(unittest.TestCase):
    def test_repairs_reversible_utf8_mojibake_and_preserves_valid_vietnamese(self) -> None:
        self.assertEqual(normalize_display_text("LiÃªm chÃ­nh há»c thuáº­t"), "Liêm chính học thuật")
        self.assertEqual(normalize_display_text("Liêm chính học thuật"), "Liêm chính học thuật")


class ResponseWriterTest(unittest.TestCase):
    def test_broken_pipe_is_treated_as_client_disconnect(self) -> None:
        from backend.server import AppRequestHandler

        handler = AppRequestHandler.__new__(AppRequestHandler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=BrokenPipeError)
        handler.close_connection = False
        handler._write_response(b"ok", 200, [])
        self.assertTrue(handler.close_connection)


class AnalysisJobManagerTest(unittest.TestCase):
    def test_job_progress_is_monotonic_and_protected_by_token(self) -> None:
        manager = AnalysisJobManager(max_workers=1, ttl_seconds=60)
        release = threading.Event()

        def work(progress):
            progress(25, "extracting", "Đang đọc tài liệu.")
            release.wait(timeout=2)
            progress(78, "matching", "Đang đối chiếu.")
            return {"ok": True}

        created = manager.create(work)
        status = None
        for _attempt in range(50):
            status = manager.get(created["jobId"], created["jobToken"])
            if status and status["progress"] >= 25:
                break
            time.sleep(0.01)
        self.assertIsNone(manager.get(created["jobId"], "wrong-token"))
        self.assertIsNotNone(status)
        self.assertGreaterEqual(status["progress"], 25)
        release.set()
        for _attempt in range(50):
            status = manager.get(created["jobId"], created["jobToken"])
            if status and status["status"] == "completed":
                break
            time.sleep(0.01)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["progress"], 100)
        self.assertEqual(status["result"], {"ok": True})


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
                self.assertEqual(health["webDiscoveryLimits"]["queries"], 10)
                self.assertEqual(health["webDiscoveryLimits"]["parallelWorkers"], 10)
                self.assertEqual(health["webDiscoveryLimits"]["mode"], "fast")
                self.assertEqual(health["webDiscoveryLimits"]["timeBudgetSeconds"], 150.0)
                self.assertEqual(health["webDiscoveryLimits"]["fallbackMinSources"], 8)
                self.assertEqual(health["webDiscoveryLimits"]["exaMaxQueries"], 3)
                self.assertEqual(health["webDiscoveryLimits"]["exaMode"], "instant")
                self.assertEqual(health["webDiscoveryLimits"]["websearchapiMaxQueries"], 1)
                self.assertEqual(health["webDiscoveryLimits"]["linkupMaxQueries"], 1)
                self.assertEqual(health["webDiscoveryLimits"]["linkupDepth"], "fast")
                self.assertEqual(health["webDiscoveryLimits"]["serperMaxQueries"], 1)
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

    def test_large_docx_upload_job_accepts_file_over_old_ten_megabyte_limit(self) -> None:
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
                document.core_properties.author = "Minh Chung Large DOCX QA"
                document.add_paragraph(
                    "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. "
                    "Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao "
                    "chép nội dung mà không ghi nhận nguồn."
                )
                compact_stream = io.BytesIO()
                document.save(compact_stream)
                expanded_stream = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(compact_stream.getvalue())) as source_archive:
                    with zipfile.ZipFile(expanded_stream, "w") as destination_archive:
                        for item in source_archive.infolist():
                            destination_archive.writestr(item, source_archive.read(item.filename))
                        destination_archive.writestr(
                            "word/media/qa-padding.bin",
                            os.urandom(10_500_000),
                            compress_type=zipfile.ZIP_STORED,
                        )
                content = expanded_stream.getvalue()
                self.assertGreater(len(content), 10_000_000)
                base = f"http://127.0.0.1:{server.server_address[1]}"
                created = self._raw_json(
                    f"{base}/api/analysis-jobs/upload",
                    content=content,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "X-Minh-Chung-Filename": "large-document.docx",
                    },
                )
                report = self._poll_job(base, created)["result"]
                self.assertGreater(report["percent"], 70)
                self.assertEqual(report["documentMetadata"]["author"], "Minh Chung Large DOCX QA")
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

    def test_web_discovery_runs_only_after_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                text = (
                    "Nội dung dùng để xác minh rằng quét nguồn web công khai chỉ chạy khi người dùng chủ động "
                    "bật lựa chọn gửi đoạn trích sang nhà cung cấp tìm kiếm bên ngoài để tìm nguồn liên quan."
                )
                web_result = {
                    "provider": "tavily",
                    "enabled": True,
                    "externalProcessing": True,
                    "queries": ["truy vấn thử nghiệm"],
                    "indexed": 1,
                    "skipped": 0,
                    "message": "Đã lập chỉ mục một nguồn.",
                    "sources": [],
                }
                with patch.object(server.context.web_discovery, "discover_and_index", return_value=web_result) as discover:  # type: ignore[attr-defined]
                    default_report = self._json(f"{base}/api/analyze", method="POST", payload={"text": text})
                    opted_in_report = self._json(
                        f"{base}/api/analyze",
                        method="POST",
                        payload={"text": text, "enableWebSearch": True},
                    )
                audit = self._json(f"{base}/api/audit")
                self.assertNotIn("webDiscovery", default_report)
                self.assertEqual(opted_in_report["webDiscovery"]["provider"], "tavily")
                discover.assert_called_once()
                self.assertIn("web_discovery.search", {event["action"] for event in audit["events"]})
            finally:
                server.shutdown()
                server.server_close()

    def test_public_mode_ignores_admin_header_and_does_not_store_guest_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0, public_mode=True))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                admin_header = {"X-Minh-Chung-User": "demo-admin"}
                session = self._json(f"{base}/api/session", headers=admin_header)
                users = self._json(f"{base}/api/session/users", headers=admin_header)
                report = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    headers=admin_header,
                    payload={
                        "text": (
                            "Tài liệu khách công khai có đủ số lượng từ để tạo báo cáo thử nghiệm nhưng không "
                            "được lưu trên máy chủ hoặc đưa vào kho bài nộp nội bộ dù client gửi yêu cầu lưu."
                        ),
                        "saveReport": True,
                        "indexForComparison": True,
                    },
                )
                reports = self._json(f"{base}/api/reports", headers=admin_header)
                submissions = self._json(f"{base}/api/submissions", headers=admin_header)
                with self.assertRaises(HTTPError) as error:
                    self._json(f"{base}/api/crawl/operations", headers=admin_header)
                self.assertEqual(session["user"]["username"], "demo-student")
                self.assertEqual(session["user"]["role"], "student")
                self.assertEqual([user["username"] for user in users["users"]], ["demo-student"])
                self.assertFalse(report["dataRetention"]["stored"])
                self.assertNotIn("reportId", report)
                self.assertNotIn("submissionId", report)
                self.assertEqual(reports["reports"], [])
                self.assertEqual(submissions["submissions"], [])
                self.assertEqual(error.exception.code, 403)
            finally:
                server.shutdown()
                server.server_close()

    def test_password_mode_requires_cookie_and_persists_account_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(settings_for(Path(directory), port=0, auth_mode="password"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_address[1]}"
                with self.assertRaises(HTTPError) as error:
                    self._json(f"{base}/api/session", headers={"X-Minh-Chung-User": "demo-admin"})
                self.assertEqual(error.exception.code, 401)

                request = Request(
                    f"{base}/api/auth/register",
                    method="POST",
                    data=json.dumps(
                        {"username": "minh-test", "displayName": "Minh Test", "password": "mat-khau-123"}
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(request, timeout=5) as response:
                    registered = json.loads(response.read().decode("utf-8"))
                    cookie = response.headers["Set-Cookie"].split(";", 1)[0]

                text = (
                    "Liêm chính học thuật là nền tảng của một môi trường giáo dục đáng tin cậy. "
                    "Người học cần phân biệt rõ việc tham khảo ý tưởng, trích dẫn trực tiếp và sao "
                    "chép nội dung mà không ghi nhận nguồn."
                )
                report = self._json(
                    f"{base}/api/analyze",
                    method="POST",
                    payload={"text": text},
                    headers={"Cookie": cookie},
                )
                history = self._json(f"{base}/api/reports", headers={"Cookie": cookie})
                self.assertEqual(registered["user"]["username"], "minh-test")
                self.assertTrue(report["reportId"])
                self.assertEqual(len(history["reports"]), 1)
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

    @staticmethod
    def _raw_json(
        url: str,
        *,
        content: bytes,
        headers: dict[str, str] | None = None,
    ) -> dict:
        request = Request(url, method="POST", data=content, headers=headers or {})
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    @classmethod
    def _poll_job(cls, base: str, created: dict) -> dict:
        for _attempt in range(100):
            status = cls._json(
                f"{base}/api/analysis-jobs/{created['jobId']}",
                headers={"X-Minh-Chung-Job-Token": created["jobToken"]},
            )
            if status["status"] == "completed":
                return status
            if status["status"] == "failed":
                raise AssertionError(status.get("error") or status.get("message"))
            time.sleep(0.03)
        raise AssertionError("Analysis job did not complete in time.")


if __name__ == "__main__":
    unittest.main()

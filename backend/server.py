from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import traceback
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .analysis import SimilarityAnalyzer
from .auth import AuthenticationError, AuthorizationError, Principal, principal_from_user
from .config import Settings
from .crawler import CrawlPolicyError, CrawlRunner, Crawler
from .demo_data import seed_demo_sources
from .extractors import UnsupportedDocumentError, extract_document
from .ocr import ocr_status
from .pdf_report import build_report_pdf
from .search import SearchBackend, create_search_backend
from .storage import Storage
from .text import count_words
from .web_discovery import WebDiscovery


@dataclass
class AppContext:
    settings: Settings
    storage: Storage
    analyzer: SimilarityAnalyzer
    crawler: Crawler
    crawl_runner: CrawlRunner
    search_backend: SearchBackend
    web_discovery: WebDiscovery

    @classmethod
    def create(cls, settings: Settings) -> "AppContext":
        storage = Storage(settings.database_path)
        search_backend = create_search_backend(settings, storage)
        if search_backend.name != "sqlite-fts5":
            storage.attach_search_mirror(search_backend)
        seed_demo_sources(storage)
        crawler = Crawler(storage, settings)
        return cls(
            settings=settings,
            storage=storage,
            analyzer=SimilarityAnalyzer(search_backend),
            crawler=crawler,
            crawl_runner=CrawlRunner(crawler),
            search_backend=search_backend,
            web_discovery=WebDiscovery(settings, storage),
        )


class AppRequestHandler(BaseHTTPRequestHandler):
    context: AppContext
    server_version = "MinhChung/0.1"

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except AuthenticationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.UNAUTHORIZED)
        except AuthorizationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except Exception as error:  # pragma: no cover - top-level HTTP safety net
            traceback.print_exc()
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except AuthenticationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.UNAUTHORIZED)
        except AuthorizationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except (ValueError, UnsupportedDocumentError, CrawlPolicyError) as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # pragma: no cover - top-level HTTP safety net
            traceback.print_exc()
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            principal = self._principal()
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) == 3 and parts[:2] == ["api", "submissions"]:
                submission = self.context.storage.get_submission(int(parts[2]), principal.organization_id)
                if not submission:
                    self._send_json({"error": "Không tìm thấy bài nộp."}, HTTPStatus.NOT_FOUND)
                    return
                if principal.role == "student" and int(submission["user_id"]) != principal.id:
                    raise AuthorizationError("Bạn chỉ có thể rút bài nộp của chính mình.")
                deleted = self.context.storage.delete_submission(int(parts[2]), principal.organization_id)
                if not deleted:
                    self._send_json({"error": "Không tìm thấy bài nộp."}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True})
                self._audit(principal, "submission.delete", "submission", parts[2])
                return
            self._send_json({"error": "Không tìm thấy API."}, HTTPStatus.NOT_FOUND)
        except AuthenticationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.UNAUTHORIZED)
        except AuthorizationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception as error:  # pragma: no cover - top-level HTTP safety net
            traceback.print_exc()
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} - {format % args}")

    def _handle_get(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "minh-chung",
                    "searchBackend": self.context.search_backend.name,
                    "webDiscovery": {
                        "tavily": bool(self.context.settings.tavily_api_key),
                        "brave": bool(self.context.settings.brave_search_api_key),
                    },
                }
            )
            return
        if parsed.path == "/api/session/users":
            self._send_json({"users": self.context.storage.list_users()})
            return
        principal = self._principal()
        if parsed.path == "/api/session":
            self._send_json({"user": self._principal_payload(principal)})
            return
        if parsed.path == "/api/ocr/status":
            self._send_json(ocr_status())
            return
        if parsed.path == "/api/stats":
            stats = self.context.storage.stats(principal.organization_id)
            if principal.role != "admin":
                stats["crawl_queue"] = {}
            self._send_json({**stats, "crawler": self.context.crawl_runner.status() if principal.role == "admin" else {}})
            return
        if parsed.path == "/api/sources":
            self._send_json(
                {
                    "sources": self.context.storage.list_sources(
                        self._query_limit(query),
                        principal.organization_id,
                    )
                }
            )
            return
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["api", "sources"] and parts[3] == "versions":
            self._send_json(
                {
                    "versions": self.context.storage.list_source_versions(
                        int(parts[2]),
                        self._query_limit(query, 50),
                        principal.organization_id,
                    )
                }
            )
            return
        if parsed.path == "/api/reports":
            self._send_json(
                {
                    "reports": self.context.storage.list_reports(
                        self._query_limit(query, 20),
                        principal.organization_id,
                        principal.id if principal.role == "student" else None,
                    )
                }
            )
            return
        if len(parts) == 4 and parts[:2] == ["api", "reports"] and parts[3] == "pdf":
            report = self.context.storage.get_report(
                int(parts[2]),
                principal.organization_id,
                principal.id if principal.role == "student" else None,
            )
            if not report:
                self._send_json({"error": "Không tìm thấy báo cáo."}, HTTPStatus.NOT_FOUND)
                return
            pdf = build_report_pdf(report, organization_name=principal.organization_name)
            self._send_bytes(
                pdf,
                "application/pdf",
                filename=f"minh-chung-report-{report['id']}.pdf",
            )
            self._audit(principal, "report.export_pdf", "report", report["id"])
            return
        if parsed.path == "/api/submissions":
            self._send_json(
                {
                    "submissions": self.context.storage.list_submissions(
                        self._query_limit(query, 100),
                        principal.organization_id,
                        principal.id if principal.role == "student" else None,
                    )
                }
            )
            return
        if parsed.path == "/api/crawl/status":
            principal.require("admin")
            self._send_json(
                {
                    **self.context.crawl_runner.status(),
                    "queue": self.context.storage.stats(principal.organization_id)["crawl_queue"],
                }
            )
            return
        if parsed.path == "/api/crawl/operations":
            principal.require("admin")
            self._send_json(self.context.storage.crawl_operations(self._query_limit(query, 50)))
            return
        if parsed.path == "/api/search/status":
            self._send_json(self.context.search_backend.status())
            return
        if parsed.path == "/api/audit":
            principal.require("admin")
            self._send_json(
                {
                    "events": self.context.storage.list_audit_events(
                        principal.organization_id,
                        self._query_limit(query, 100),
                    )
                }
            )
            return
        self._serve_static(parsed.path)

    def _handle_post(self) -> None:
        parsed = urlparse(self.path)
        payload = self._read_json()
        principal = self._principal()
        if parsed.path == "/api/analyze":
            self._analyze_text(payload, principal)
            return
        if parsed.path == "/api/analyze-upload":
            self._analyze_upload(payload, principal)
            return
        if parsed.path == "/api/sources":
            principal.require("admin", "instructor")
            self._add_source(payload, principal)
            return
        if parsed.path == "/api/crawl/seeds":
            principal.require("admin")
            self._add_crawl_seeds(payload, principal)
            return
        if parsed.path == "/api/crawl/sitemaps":
            principal.require("admin")
            self._add_crawl_sitemaps(payload, principal)
            return
        if parsed.path == "/api/crawl/run":
            principal.require("admin")
            self._run_crawler(payload, principal)
            return
        if parsed.path == "/api/crawl/retry":
            principal.require("admin")
            self._retry_failed_crawls(payload, principal)
            return
        if parsed.path == "/api/search/reindex":
            principal.require("admin")
            self._reindex_search(payload, principal)
            return
        self._send_json({"error": "Không tìm thấy API."}, HTTPStatus.NOT_FOUND)

    def _analyze_text(self, payload: dict[str, Any], principal: Principal) -> None:
        text = str(payload.get("text", "")).strip()
        if count_words(text) < 20:
            raise ValueError("Tài liệu cần có ít nhất 20 từ.")
        settings = payload.get("settings") or {}
        web_discovery = None
        if bool(payload.get("enableWebSearch", False)):
            web_discovery = self.context.web_discovery.discover_and_index(
                text,
                organization_id=principal.organization_id,
                max_results=max(1, min(8, int(payload.get("webSearchMaxResults", 5)))),
            )
        result = self.context.analyzer.analyze(
            text,
            minimum_words=max(4, min(30, int(settings.get("minimumWords", 8)))),
            exclude_quotes=bool(settings.get("excludeQuotes", True)),
            exclude_bibliography=bool(settings.get("excludeBibliography", True)),
            organization_id=principal.organization_id,
        )
        title = next((line.strip() for line in text.splitlines() if line.strip()), "Tài liệu không tên")
        if web_discovery is not None:
            result["webDiscovery"] = web_discovery
        if bool(payload.get("indexForComparison", False)):
            result["submissionId"] = self.context.storage.create_submission(
                title=title[:180],
                text_content=text,
                index_for_comparison=True,
                metadata={"origin": "text"},
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        if bool(payload.get("saveReport", True)):
            result["reportId"] = self.context.storage.save_report(
                title[:180],
                text,
                result,
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        self._audit(principal, "report.analyze", "report", result.get("reportId"))
        self._send_json(result)

    def _analyze_upload(self, payload: dict[str, Any], principal: Principal) -> None:
        filename = str(payload.get("filename", "")).strip()
        encoded = str(payload.get("contentBase64", ""))
        if not filename or not encoded:
            raise ValueError("Thiếu tên tệp hoặc nội dung tệp.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError("Nội dung tệp không đúng định dạng base64.") from error
        if len(content) > self.context.settings.document_max_bytes:
            raise ValueError("Tệp vượt quá giới hạn dung lượng.")
        extracted = extract_document(filename, content)
        text = extracted["text"].strip()
        if count_words(text) < 20:
            raise ValueError("Không đọc được đủ nội dung văn bản từ tệp.")
        web_discovery = None
        if bool(payload.get("enableWebSearch", False)):
            web_discovery = self.context.web_discovery.discover_and_index(
                text,
                organization_id=principal.organization_id,
                max_results=max(1, min(8, int(payload.get("webSearchMaxResults", 5)))),
            )
        result = self.context.analyzer.analyze(text, organization_id=principal.organization_id)
        if web_discovery is not None:
            result["webDiscovery"] = web_discovery
        result["documentMetadata"] = extracted["metadata"]
        result["integrityFlags"] = extracted["integrityFlags"]
        if bool(payload.get("indexForComparison", False)):
            result["submissionId"] = self.context.storage.create_submission(
                title=filename[:180],
                text_content=text,
                index_for_comparison=True,
                metadata={"origin": "upload", **extracted["metadata"]},
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        if bool(payload.get("saveReport", True)):
            result["reportId"] = self.context.storage.save_report(
                filename[:180],
                text,
                result,
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        self._audit(principal, "report.analyze_upload", "report", result.get("reportId"))
        self._send_json(result)

    def _add_source(self, payload: dict[str, Any], principal: Principal) -> None:
        title = str(payload.get("title", "")).strip()
        text = str(payload.get("content", "")).strip()
        display_url = str(payload.get("url", "")).strip()
        digest = hashlib.sha256(f"{principal.organization_id}:{display_url}:{title}".encode("utf-8")).hexdigest()[:24]
        url = f"organization://{principal.organization_id}/manual/{digest}"
        if not title or count_words(text) < 8:
            raise ValueError("Nguồn cần có tên và nội dung tối thiểu 8 từ.")
        source_id = self.context.storage.upsert_source(
            url=url,
            title=title,
            text_content=text,
            source_type=str(payload.get("type", "tự thêm")),
            canonical_url=display_url or None,
            organization_id=principal.organization_id,
        )
        self._audit(principal, "source.create", "source", source_id)
        self._send_json({"ok": True, "sourceId": source_id}, HTTPStatus.CREATED)

    def _add_crawl_seeds(self, payload: dict[str, Any], principal: Principal) -> None:
        urls = payload.get("urls") or []
        if not isinstance(urls, list) or not urls:
            raise ValueError("Hãy nhập ít nhất một URL.")
        if len(urls) > 100:
            raise ValueError("Mỗi lần chỉ thêm tối đa 100 URL hạt giống.")
        queued = 0
        for url in urls:
            if self.context.crawler.enqueue(str(url)):
                queued += 1
        self._audit(principal, "crawl.seed", "crawl_queue", details={"queued": queued})
        self._send_json({"ok": True, "queued": queued}, HTTPStatus.CREATED)

    def _run_crawler(self, payload: dict[str, Any], principal: Principal) -> None:
        max_pages = max(1, min(10_000, int(payload.get("maxPages", 20))))
        max_depth = max(0, min(5, int(payload.get("maxDepth", 1))))
        started = self.context.crawl_runner.start(max_pages=max_pages, max_depth=max_depth)
        status = HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT
        self._audit(principal, "crawl.run", "crawler", details={"maxPages": max_pages, "maxDepth": max_depth})
        self._send_json({"ok": started, "running": True, "maxPages": max_pages, "maxDepth": max_depth}, status)

    def _add_crawl_sitemaps(self, payload: dict[str, Any], principal: Principal) -> None:
        urls = payload.get("urls") or []
        if not isinstance(urls, list) or not urls:
            raise ValueError("Hãy nhập ít nhất một sitemap URL.")
        if len(urls) > 20:
            raise ValueError("Mỗi lần chỉ thêm tối đa 20 sitemap.")
        max_urls = max(1, min(50_000, int(payload.get("maxUrls", 10_000))))
        total = {"sitemaps": 0, "queued": 0, "skipped": 0}
        for url in urls:
            result = self.context.crawler.enqueue_sitemap(str(url), max_urls=max_urls - total["queued"])
            for key in total:
                total[key] += result[key]
            if total["queued"] >= max_urls:
                break
        self._audit(principal, "crawl.sitemap", "crawl_queue", details=total)
        self._send_json({"ok": True, **total}, HTTPStatus.CREATED)

    def _retry_failed_crawls(self, payload: dict[str, Any], principal: Principal) -> None:
        limit = max(1, min(10_000, int(payload.get("limit", 100))))
        requeued = self.context.storage.requeue_failed_urls(limit=limit)
        self._audit(principal, "crawl.retry", "crawl_queue", details={"requeued": requeued})
        self._send_json({"ok": True, "requeued": requeued})

    def _reindex_search(self, payload: dict[str, Any], principal: Principal) -> None:
        result = self.context.search_backend.rebuild(self.context.storage)
        self._audit(principal, "search.reindex", "search", details=result)
        self._send_json({"ok": True, "backend": self.context.search_backend.name, **result})

    def _principal(self) -> Principal:
        username = self.headers.get("X-Minh-Chung-User", "demo-admin").strip()
        user = self.context.storage.get_user(username)
        if not user:
            raise AuthenticationError("Không nhận diện được người dùng.")
        return principal_from_user(user)

    @staticmethod
    def _principal_payload(principal: Principal) -> dict[str, Any]:
        return {
            "id": principal.id,
            "organizationId": principal.organization_id,
            "organizationName": principal.organization_name,
            "username": principal.username,
            "displayName": principal.display_name,
            "role": principal.role,
            "permissions": {
                "manageCrawler": principal.role == "admin",
                "manageSearch": principal.role == "admin",
                "manageSources": principal.role in {"admin", "instructor"},
                "viewAudit": principal.role == "admin",
            },
        }

    def _audit(
        self,
        principal: Principal,
        action: str,
        entity_type: str,
        entity_id: str | int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.context.storage.save_audit_event(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            organization_id=principal.organization_id,
            user_id=principal.id,
            details=details,
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > self.context.settings.document_max_bytes * 2:
            raise ValueError("Yêu cầu vượt quá giới hạn dung lượng.")
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as error:
            raise ValueError("Dữ liệu JSON không hợp lệ.") from error
        if not isinstance(payload, dict):
            raise ValueError("Dữ liệu JSON cần là một đối tượng.")
        return payload

    def _serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        allowed = {"index.html", "styles.css", "app.js", "preview.png"}
        if relative not in allowed:
            self._send_json({"error": "Không tìm thấy tệp."}, HTTPStatus.NOT_FOUND)
            return
        file_path = (self.context.settings.static_dir / relative).resolve()
        if file_path.parent != self.context.settings.static_dir.resolve() or not file_path.is_file():
            self._send_json({"error": "Không tìm thấy tệp."}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, *, filename: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _query_limit(query: dict[str, list[str]], default: int = 100) -> int:
        return max(1, min(500, int(query.get("limit", [str(default)])[0])))


def create_server(settings: Settings | None = None) -> ThreadingHTTPServer:
    active_settings = settings or Settings.from_env()
    context = AppContext.create(active_settings)

    class BoundHandler(AppRequestHandler):
        pass

    BoundHandler.context = context
    server = ThreadingHTTPServer((active_settings.host, active_settings.port), BoundHandler)
    server.context = context  # type: ignore[attr-defined]
    return server


def run(settings: Settings | None = None) -> None:
    server = create_server(settings)
    host, port = server.server_address
    print(f"Minh Chung is running at http://{host}:{port}")
    print("Press Ctrl+C to stop the server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Minh Chung...")
    finally:
        server.server_close()

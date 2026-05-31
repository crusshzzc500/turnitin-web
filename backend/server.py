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
from urllib.parse import parse_qs, unquote, urlparse

from .analysis import SimilarityAnalyzer
from .auth import AuthenticationError, AuthorizationError, Principal, principal_from_user
from .config import Settings
from .crawler import CrawlPolicyError, CrawlRunner, Crawler
from .demo_data import seed_demo_sources
from .extractors import UnsupportedDocumentError, extract_document
from .jobs import AnalysisJobManager, ProgressCallback
from .ocr import ocr_status
from .pdf_report import build_report_pdf
from .search import SearchBackend, create_search_backend
from .storage import Storage
from .text import count_words, normalize_display_text
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
    analysis_jobs: AnalysisJobManager

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
            analysis_jobs=AnalysisJobManager(
                max_workers=settings.analysis_job_workers,
                ttl_seconds=settings.analysis_job_ttl_seconds,
            ),
        )


class AppRequestHandler(BaseHTTPRequestHandler):
    context: AppContext
    server_version = "MinhChung/0.1"

    def do_GET(self) -> None:
        try:
            self._handle_get()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True
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
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True
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
                submission = self.context.storage.get_submission(
                    int(parts[2]),
                    self._organization_scope(principal),
                )
                if not submission:
                    self._send_json({"error": "Không tìm thấy bài nộp."}, HTTPStatus.NOT_FOUND)
                    return
                if principal.role == "student" and int(submission["user_id"]) != principal.id:
                    raise AuthorizationError("Bạn chỉ có thể rút bài nộp của chính mình.")
                deleted = self.context.storage.delete_submission(
                    int(parts[2]),
                    self._organization_scope(principal),
                )
                if not deleted:
                    self._send_json({"error": "Không tìm thấy bài nộp."}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True})
                self._audit(principal, "submission.delete", "submission", parts[2])
                return
            self._send_json({"error": "Không tìm thấy API."}, HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True
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
        parts = [part for part in parsed.path.split("/") if part]
        if parsed.path == "/api/health":
            self._send_json(
                {
                    "ok": True,
                    "service": "minh-chung",
                    "searchBackend": self.context.search_backend.name,
                    "webDiscovery": self.context.web_discovery.status(),
                    "publicMode": self.context.settings.public_mode,
                    "documentMaxBytes": self.context.settings.document_max_bytes,
                    "webDiscoveryLimits": {
                        "queries": self.context.settings.web_discovery_max_queries,
                        "resultsPerQuery": self.context.settings.web_discovery_max_results,
                        "parallelWorkers": self.context.settings.web_discovery_parallel_workers,
                        "mode": self.context.settings.web_discovery_mode,
                        "timeBudgetSeconds": self.context.settings.web_discovery_time_budget_seconds,
                        "fallbackMinSources": self.context.settings.web_discovery_fallback_min_sources,
                        "exaMaxQueries": self.context.settings.web_discovery_exa_max_queries,
                        "exaMode": self.context.settings.web_discovery_exa_mode,
                        "websearchapiMaxQueries": self.context.settings.web_discovery_websearchapi_max_queries,
                        "linkupMaxQueries": self.context.settings.web_discovery_linkup_max_queries,
                        "linkupDepth": self.context.settings.web_discovery_linkup_depth,
                        "serperMaxQueries": self.context.settings.web_discovery_serper_max_queries,
                    },
                }
            )
            return
        if parsed.path == "/api/session/users":
            users = (
                [self.context.storage.get_user("demo-student")]
                if self.context.settings.public_mode
                else self.context.storage.list_users()
            )
            self._send_json({"users": [user for user in users if user]})
            return
        principal = self._principal()
        if parsed.path == "/api/session":
            self._send_json({"user": self._principal_payload(principal)})
            return
        if len(parts) == 3 and parts[:2] == ["api", "analysis-jobs"]:
            job = self.context.analysis_jobs.get(
                parts[2],
                self.headers.get("X-Minh-Chung-Job-Token", ""),
            )
            if not job:
                self._send_json({"error": "Không tìm thấy tiến trình phân tích."}, HTTPStatus.NOT_FOUND)
                return
            self._send_json(job)
            return
        if parsed.path == "/api/ocr/status":
            self._send_json(ocr_status())
            return
        if parsed.path == "/api/stats":
            stats = self.context.storage.stats(self._organization_scope(principal))
            if principal.role != "admin":
                stats["crawl_queue"] = {}
            self._send_json({**stats, "crawler": self.context.crawl_runner.status() if principal.role == "admin" else {}})
            return
        if parsed.path == "/api/sources":
            self._send_json(
                {
                    "sources": self.context.storage.list_sources(
                        self._query_limit(query),
                        self._organization_scope(principal),
                    )
                }
            )
            return
        if len(parts) == 4 and parts[:2] == ["api", "sources"] and parts[3] == "versions":
            self._send_json(
                {
                    "versions": self.context.storage.list_source_versions(
                        int(parts[2]),
                        self._query_limit(query, 50),
                        self._organization_scope(principal),
                    )
                }
            )
            return
        if parsed.path == "/api/reports":
            self._send_json(
                {
                    "reports": self.context.storage.list_reports(
                        self._query_limit(query, 20),
                        self._organization_scope(principal),
                        principal.id if principal.role == "student" else None,
                    )
                }
            )
            return
        if len(parts) == 4 and parts[:2] == ["api", "reports"] and parts[3] == "pdf":
            report = self.context.storage.get_report(
                int(parts[2]),
                self._organization_scope(principal),
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
                        self._organization_scope(principal),
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
        principal = self._principal()
        if parsed.path == "/api/analysis-jobs/upload":
            self._create_upload_analysis_job(principal)
            return

        payload = self._read_json()
        if parsed.path == "/api/analysis-jobs":
            self._create_analysis_job(payload, principal)
            return
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

    def _create_analysis_job(self, payload: dict[str, Any], principal: Principal) -> None:
        kind = str(payload.get("kind", "text"))
        if kind == "text":
            work = lambda progress: self._build_text_analysis(payload, principal, progress)
        elif kind == "upload":
            work = lambda progress: self._build_upload_analysis(payload, principal, progress)
        else:
            raise ValueError("Loại tiến trình phân tích không hợp lệ.")
        self._send_json(self.context.analysis_jobs.create(work), HTTPStatus.ACCEPTED)

    def _create_upload_analysis_job(self, principal: Principal) -> None:
        filename = unquote(self.headers.get("X-Minh-Chung-Filename", "document.docx"))
        content = self._read_bytes()
        payload = {
            "enableWebSearch": self.headers.get("X-Minh-Chung-Enable-Web-Search", "0") == "1",
            "webSearchMaxResults": self.headers.get("X-Minh-Chung-Web-Search-Max-Results", "10"),
            "saveReport": self.headers.get("X-Minh-Chung-Save-Report", "1") == "1",
            "indexForComparison": self.headers.get("X-Minh-Chung-Index-Submission", "0") == "1",
        }
        work = lambda progress: self._build_upload_bytes_analysis(
            filename,
            content,
            payload,
            principal,
            progress,
        )
        self._send_json(self.context.analysis_jobs.create(work), HTTPStatus.ACCEPTED)

    def _analyze_text(self, payload: dict[str, Any], principal: Principal) -> None:
        self._send_json(self._build_text_analysis(payload, principal))

    def _build_text_analysis(
        self,
        payload: dict[str, Any],
        principal: Principal,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        text = normalize_display_text(str(payload.get("text", ""))).strip()
        if count_words(text) < 20:
            raise ValueError("Tài liệu cần có ít nhất 20 từ.")
        settings = payload.get("settings") or {}
        self._progress(progress, 12, "extracting", "Đã đọc nội dung tài liệu.")
        web_discovery = self._discover_web_sources(payload, text, principal, progress)
        self._progress(progress, 76, "matching", "Đang đối chiếu với kho nguồn.")
        result = self.context.analyzer.analyze(
            text,
            minimum_words=max(4, min(30, int(settings.get("minimumWords", 8)))),
            exclude_quotes=bool(settings.get("excludeQuotes", True)),
            exclude_bibliography=bool(settings.get("excludeBibliography", True)),
            organization_id=self._organization_scope(principal),
        )
        title = next((line.strip() for line in text.splitlines() if line.strip()), "Tài liệu không tên")
        if web_discovery is not None:
            result["webDiscovery"] = web_discovery
        if bool(payload.get("indexForComparison", False)) and not self.context.settings.public_mode:
            result["submissionId"] = self.context.storage.create_submission(
                title=title[:180],
                text_content=text,
                index_for_comparison=True,
                metadata={"origin": "text"},
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        if bool(payload.get("saveReport", True)) and not self.context.settings.public_mode:
            result["reportId"] = self.context.storage.save_report(
                title[:180],
                text,
                result,
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        self._add_public_retention_notice(result)
        self._audit(principal, "report.analyze", "report", result.get("reportId"))
        self._progress(progress, 96, "finalizing", "Đang hoàn thiện báo cáo.")
        return result

    def _analyze_upload(self, payload: dict[str, Any], principal: Principal) -> None:
        self._send_json(self._build_upload_analysis(payload, principal))

    def _build_upload_analysis(
        self,
        payload: dict[str, Any],
        principal: Principal,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
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
        return self._build_upload_bytes_analysis(filename, content, payload, principal, progress)

    def _build_upload_bytes_analysis(
        self,
        filename: str,
        content: bytes,
        payload: dict[str, Any],
        principal: Principal,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        self._progress(progress, 8, "extracting", "Đang đọc nội dung tệp.")
        extracted = extract_document(filename, content)
        text = normalize_display_text(extracted["text"]).strip()
        if count_words(text) < 20:
            raise ValueError("Không đọc được đủ nội dung văn bản từ tệp.")
        self._progress(progress, 18, "extracting", "Đã trích xuất nội dung tệp.")
        web_discovery = self._discover_web_sources(payload, text, principal, progress)
        self._progress(progress, 76, "matching", "Đang đối chiếu với kho nguồn.")
        result = self.context.analyzer.analyze(text, organization_id=self._organization_scope(principal))
        if web_discovery is not None:
            result["webDiscovery"] = web_discovery
        result["documentMetadata"] = extracted["metadata"]
        result["integrityFlags"] = extracted["integrityFlags"]
        if bool(payload.get("indexForComparison", False)) and not self.context.settings.public_mode:
            result["submissionId"] = self.context.storage.create_submission(
                title=filename[:180],
                text_content=text,
                index_for_comparison=True,
                metadata={"origin": "upload", **extracted["metadata"]},
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        if bool(payload.get("saveReport", True)) and not self.context.settings.public_mode:
            result["reportId"] = self.context.storage.save_report(
                filename[:180],
                text,
                result,
                organization_id=principal.organization_id,
                user_id=principal.id,
            )
        self._add_public_retention_notice(result)
        self._audit(principal, "report.analyze_upload", "report", result.get("reportId"))
        self._progress(progress, 96, "finalizing", "Đang hoàn thiện báo cáo.")
        return result

    def _discover_web_sources(
        self,
        payload: dict[str, Any],
        text: str,
        principal: Principal,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any] | None:
        if not bool(payload.get("enableWebSearch", False)):
            self._progress(progress, 42, "web_discovery", "Bỏ qua quét web theo lựa chọn của bạn.")
            return None
        self._progress(progress, 22, "web_discovery", "Đang quét song song các nguồn web công khai.")
        result = self.context.web_discovery.discover_and_index(
            text,
            organization_id=self._organization_scope(principal),
            max_results=max(1, min(20, int(payload.get("webSearchMaxResults", 10)))),
            progress_callback=lambda completed, total, indexed: self._progress(
                progress,
                22 + round((completed / max(1, total)) * 50),
                "web_discovery",
                f"Đã quét {completed}/{total} truy vấn web, tìm thấy {indexed} nguồn phù hợp.",
            ),
        )
        self._audit(
            principal,
            "web_discovery.search",
            "source",
            details={
                "provider": result["provider"],
                "indexed": result["indexed"],
                "skipped": result["skipped"],
                "queryCount": len(result["queries"]),
                "externalProcessing": result["externalProcessing"],
            },
        )
        return result

    @staticmethod
    def _progress(callback: ProgressCallback | None, value: int, phase: str, message: str) -> None:
        if callback:
            callback(value, phase, message)

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
        username = (
            "demo-student"
            if self.context.settings.public_mode
            else self.headers.get("X-Minh-Chung-User", "demo-admin").strip()
        )
        user = self.context.storage.get_user(username)
        if not user:
            raise AuthenticationError("Không nhận diện được người dùng.")
        return principal_from_user(user)

    def _organization_scope(self, principal: Principal) -> int | None:
        return None if self.context.settings.public_mode else principal.organization_id

    def _add_public_retention_notice(self, result: dict[str, Any]) -> None:
        if self.context.settings.public_mode:
            result["dataRetention"] = {
                "stored": False,
                "message": "Chế độ công khai không lưu bài nộp hoặc báo cáo trên máy chủ.",
            }

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

    def _read_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Tệp tải lên đang trống.")
        if length > self.context.settings.document_max_bytes:
            raise ValueError("Tệp vượt quá giới hạn dung lượng.")
        return self.rfile.read(length)

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
        self._write_response(
            body,
            HTTPStatus.OK,
            [
                ("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._write_response(
            body,
            status,
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )

    def _send_bytes(self, body: bytes, content_type: str, *, filename: str | None = None) -> None:
        headers = [("Content-Type", content_type), ("Content-Length", str(len(body)))]
        if filename:
            headers.append(("Content-Disposition", f'attachment; filename="{filename}"'))
        headers.append(("Cache-Control", "no-store"))
        self._write_response(body, HTTPStatus.OK, headers)

    def _write_response(self, body: bytes, status: HTTPStatus, headers: list[tuple[str, str]]) -> None:
        try:
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True

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

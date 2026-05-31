from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen

from .text import count_words, normalize_display_text, split_sentences


STOPWORDS = {
    "và", "của", "là", "các", "một", "những", "trong", "cho", "được", "với", "khi",
    "này", "đó", "để", "từ", "the", "and", "that", "this", "with", "from", "are",
    "was", "were", "have",
}
DiscoveryProgressCallback = Callable[[int, int, int], None]


@dataclass
class DiscoveryResult:
    provider: str
    enabled: bool
    external_processing: bool
    queries: list[str]
    indexed: int
    skipped: int
    message: str
    sources: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "externalProcessing": self.external_processing,
            "queries": self.queries,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "message": self.message,
            "sources": self.sources,
        }


def build_queries(text: str, *, max_queries: int = 3) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for sentence in split_sentences(text):
        clean = re.sub(r"\s+", " ", sentence).strip(" \t\n\r\"'“”‘’.:,;()[]{}")
        words = re.findall(r"[\wÀ-ỹ]+", clean, flags=re.UNICODE)
        if 10 <= len(words) <= 32:
            distinct = len({word.lower() for word in words if word.lower() not in STOPWORDS})
            candidates.append((distinct, clean[:360]))
    candidates.sort(reverse=True, key=lambda item: (item[0], len(item[1])))
    queries: list[str] = []
    for _score, sentence in candidates:
        if sentence not in queries:
            queries.append(sentence)
        if len(queries) >= max_queries:
            break
    if queries:
        return queries
    tokens = [
        token.lower()
        for token in re.findall(r"[\wÀ-ỹ]+", text, flags=re.UNICODE)
        if token.lower() not in STOPWORDS
    ]
    return [" ".join(tokens[:14])] if tokens else []


class WebDiscovery:
    def __init__(self, settings: Any, storage: Any):
        self.settings = settings
        self.storage = storage

    def status(self) -> dict[str, bool]:
        return {
            "tavily": bool(self.settings.tavily_api_key),
            "exa": bool(self.settings.exa_api_key),
            "serper": bool(self.settings.serper_api_key),
            "brave": bool(self.settings.brave_search_api_key),
        }

    def discover_and_index(
        self,
        text: str,
        *,
        organization_id: int | None,
        max_results: int | None = None,
        progress_callback: DiscoveryProgressCallback | None = None,
    ) -> dict[str, Any]:
        queries = build_queries(text, max_queries=self.settings.web_discovery_max_queries)
        if not queries:
            return DiscoveryResult(
                "none", False, False, [], 0, 0,
                "Không tạo được truy vấn tìm kiếm từ tài liệu.", [],
            ).to_dict()
        result_limit = max_results or self.settings.web_discovery_max_results
        result_limit = max(1, min(20, int(result_limit)))
        result: DiscoveryResult | None = None
        if self.settings.tavily_api_key:
            result = self._tavily(queries, organization_id, result_limit, progress_callback)
        if (
            self.settings.exa_api_key
            and (result is None or result.indexed < self.settings.web_discovery_fallback_min_sources)
        ):
            fallback = self._exa(
                queries[: self.settings.web_discovery_exa_max_queries],
                organization_id,
                min(10, result_limit),
                progress_callback,
                initial_seen_urls={source["url"] for source in result.sources} if result else None,
            )
            result = fallback if result is None else self._merge_results(result, fallback)
        if (
            self.settings.serper_api_key
            and (result is None or result.indexed < self.settings.web_discovery_fallback_min_sources)
        ):
            fallback = self._serper(
                queries[: self.settings.web_discovery_serper_max_queries],
                organization_id,
                min(10, result_limit),
                progress_callback,
                initial_seen_urls={source["url"] for source in result.sources} if result else None,
            )
            result = fallback if result is None else self._merge_results(result, fallback)
        if result is not None:
            return result.to_dict()
        if self.settings.brave_search_api_key:
            return self._brave(queries, organization_id, result_limit, progress_callback).to_dict()
        if progress_callback:
            progress_callback(len(queries), len(queries), 0)
        return DiscoveryResult(
            "not-configured",
            False,
            False,
            queries,
            0,
            0,
            "Chưa cấu hình Tavily, Exa, Serper hoặc Brave nên hệ thống chỉ đối chiếu kho nguồn đã có.",
            [],
        ).to_dict()

    @staticmethod
    def _merge_results(primary: DiscoveryResult, fallback: DiscoveryResult) -> DiscoveryResult:
        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for source in [*primary.sources, *fallback.sources]:
            if source["url"] not in seen_urls:
                sources.append(source)
                seen_urls.add(source["url"])
        return DiscoveryResult(
            provider=f"{primary.provider}+{fallback.provider}",
            enabled=True,
            external_processing=True,
            queries=[*primary.queries, *fallback.queries],
            indexed=len(sources),
            skipped=primary.skipped + fallback.skipped,
            message=f"{primary.message} {fallback.message}",
            sources=sources,
        )

    def _tavily(
        self,
        queries: list[str],
        organization_id: int | None,
        max_results: int,
        progress_callback: DiscoveryProgressCallback | None = None,
    ) -> DiscoveryResult:
        sources: list[dict[str, Any]] = []
        skipped = 0
        seen_urls: set[str] = set()
        errors: list[str] = []
        workers = min(len(queries), self.settings.web_discovery_parallel_workers)
        timed_out = 0
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            pending = {executor.submit(self._fetch_tavily, query, max_results): query for query in queries}
            for completed, future in enumerate(
                as_completed(pending, timeout=self.settings.web_discovery_time_budget_seconds),
                start=1,
            ):
                query = pending[future]
                try:
                    data = future.result()
                except Exception as error:
                    errors.append(str(error))
                    if progress_callback:
                        progress_callback(completed, len(queries), len(sources))
                    continue
                for item in data.get("results", []):
                    indexed = self._index_candidate(
                        provider="tavily",
                        query=query,
                        canonical_url=str(item.get("url") or ""),
                        title=str(item.get("title") or ""),
                        content=str(item.get("content") or item.get("raw_content") or ""),
                        organization_id=organization_id,
                        minimum_words=12,
                        seen_urls=seen_urls,
                    )
                    if indexed:
                        sources.append(indexed)
                    else:
                        skipped += 1
                if progress_callback:
                    progress_callback(completed, len(queries), len(sources))
        except FuturesTimeoutError:
            timed_out = sum(not future.done() for future in pending)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        message = (
            f"Đã tìm và lập chỉ mục {len(sources)} nguồn web công khai qua Tavily."
            if sources else "Tavily không trả về nguồn đủ nội dung để lập chỉ mục."
        )
        if errors:
            message += f" Có {len(errors)} truy vấn gặp lỗi."
        if timed_out:
            message += f" Đã dừng chờ {timed_out} truy vấn chậm để trả báo cáo sớm."
        return DiscoveryResult("tavily", True, True, queries, len(sources), skipped, message, sources)

    def _brave(
        self,
        queries: list[str],
        organization_id: int | None,
        max_results: int,
        progress_callback: DiscoveryProgressCallback | None = None,
    ) -> DiscoveryResult:
        sources: list[dict[str, Any]] = []
        skipped = 0
        seen_urls: set[str] = set()
        errors: list[str] = []
        workers = min(len(queries), self.settings.web_discovery_parallel_workers)
        timed_out = 0
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            pending = {executor.submit(self._fetch_brave, query, max_results): query for query in queries}
            for completed, future in enumerate(
                as_completed(pending, timeout=self.settings.web_discovery_time_budget_seconds),
                start=1,
            ):
                query = pending[future]
                try:
                    data = future.result()
                except Exception as error:
                    errors.append(str(error))
                    if progress_callback:
                        progress_callback(completed, len(queries), len(sources))
                    continue
                for item in (data.get("web") or {}).get("results", []):
                    indexed = self._index_candidate(
                        provider="brave",
                        query=query,
                        canonical_url=str(item.get("url") or ""),
                        title=str(item.get("title") or ""),
                        content=" ".join(
                            [str(item.get("description") or ""), " ".join(item.get("extra_snippets") or [])]
                        ),
                        organization_id=organization_id,
                        minimum_words=18,
                        seen_urls=seen_urls,
                    )
                    if indexed:
                        sources.append(indexed)
                    else:
                        skipped += 1
                if progress_callback:
                    progress_callback(completed, len(queries), len(sources))
        except FuturesTimeoutError:
            timed_out = sum(not future.done() for future in pending)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        message = (
            f"Đã lập chỉ mục {len(sources)} kết quả tóm tắt từ Brave."
            if sources else "Brave không trả về nguồn đủ nội dung để lập chỉ mục."
        )
        if errors:
            message += f" Có {len(errors)} truy vấn gặp lỗi."
        if timed_out:
            message += f" Đã dừng chờ {timed_out} truy vấn chậm để trả báo cáo sớm."
        return DiscoveryResult("brave", True, True, queries, len(sources), skipped, message, sources)

    def _exa(
        self,
        queries: list[str],
        organization_id: int | None,
        max_results: int,
        progress_callback: DiscoveryProgressCallback | None = None,
        initial_seen_urls: set[str] | None = None,
    ) -> DiscoveryResult:
        sources: list[dict[str, Any]] = []
        skipped = 0
        seen_urls = set(initial_seen_urls or ())
        errors: list[str] = []
        workers = min(len(queries), self.settings.web_discovery_parallel_workers)
        timed_out = 0
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            pending = {executor.submit(self._fetch_exa, query, max_results): query for query in queries}
            for completed, future in enumerate(
                as_completed(pending, timeout=self.settings.web_discovery_time_budget_seconds),
                start=1,
            ):
                query = pending[future]
                try:
                    data = future.result()
                except Exception as error:
                    errors.append(str(error))
                    if progress_callback:
                        progress_callback(completed, len(queries), len(sources))
                    continue
                for item in data.get("results", []):
                    indexed = self._index_candidate(
                        provider="exa",
                        query=query,
                        canonical_url=str(item.get("url") or item.get("id") or ""),
                        title=str(item.get("title") or ""),
                        content=" ".join(
                            [*(str(highlight) for highlight in item.get("highlights") or []), str(item.get("text") or "")]
                        ),
                        organization_id=organization_id,
                        minimum_words=12,
                        seen_urls=seen_urls,
                    )
                    if indexed:
                        sources.append(indexed)
                    else:
                        skipped += 1
                if progress_callback:
                    progress_callback(completed, len(queries), len(sources))
        except FuturesTimeoutError:
            timed_out = sum(not future.done() for future in pending)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        message = (
            f"Đã bổ sung {len(sources)} nguồn web công khai qua Exa fallback."
            if sources else "Exa fallback không trả về nguồn mới đủ nội dung để lập chỉ mục."
        )
        if errors:
            message += f" Có {len(errors)} truy vấn gặp lỗi."
        if timed_out:
            message += f" Đã dừng chờ {timed_out} truy vấn chậm để trả báo cáo sớm."
        return DiscoveryResult("exa", True, True, queries, len(sources), skipped, message, sources)

    def _serper(
        self,
        queries: list[str],
        organization_id: int | None,
        max_results: int,
        progress_callback: DiscoveryProgressCallback | None = None,
        initial_seen_urls: set[str] | None = None,
    ) -> DiscoveryResult:
        queries = queries[:1]
        sources: list[dict[str, Any]] = []
        skipped = 0
        seen_urls = set(initial_seen_urls or ())
        errors: list[str] = []
        workers = min(len(queries), self.settings.web_discovery_parallel_workers)
        timed_out = 0
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            pending = {executor.submit(self._fetch_serper, query, max_results): query for query in queries}
            for completed, future in enumerate(
                as_completed(pending, timeout=self.settings.web_discovery_time_budget_seconds),
                start=1,
            ):
                query = pending[future]
                try:
                    data = future.result()
                except Exception as error:
                    errors.append(str(error))
                    if progress_callback:
                        progress_callback(completed, len(queries), len(sources))
                    continue
                for item in data.get("organic", []):
                    indexed = self._index_candidate(
                        provider="serper",
                        query=query,
                        canonical_url=str(item.get("link") or ""),
                        title=str(item.get("title") or ""),
                        content=str(item.get("snippet") or ""),
                        organization_id=organization_id,
                        minimum_words=8,
                        seen_urls=seen_urls,
                    )
                    if indexed:
                        sources.append(indexed)
                    else:
                        skipped += 1
                if progress_callback:
                    progress_callback(completed, len(queries), len(sources))
        except FuturesTimeoutError:
            timed_out = sum(not future.done() for future in pending)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        message = (
            f"Đã bổ sung {len(sources)} nguồn web công khai qua Serper fallback."
            if sources else "Serper fallback không trả về nguồn mới đủ nội dung để lập chỉ mục."
        )
        if errors:
            message += f" Có {len(errors)} truy vấn gặp lỗi."
        if timed_out:
            message += f" Đã dừng chờ {timed_out} truy vấn chậm để trả báo cáo sớm."
        return DiscoveryResult("serper", True, True, queries, len(sources), skipped, message, sources)

    def _fetch_tavily(self, query: str, max_results: int) -> dict[str, Any]:
        return self._json_request(
            "https://api.tavily.com/search",
            {
                "query": query,
                "search_depth": self.settings.web_discovery_mode,
                "max_results": max_results,
                "include_raw_content": False,
                "include_answer": False,
            },
            headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"},
            timeout=self.settings.web_discovery_request_timeout_seconds,
        )

    def _fetch_brave(self, query: str, max_results: int) -> dict[str, Any]:
        return self._get_json(
            f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={max_results}",
            headers={"X-Subscription-Token": self.settings.brave_search_api_key},
            timeout=self.settings.web_discovery_request_timeout_seconds,
        )

    def _fetch_exa(self, query: str, max_results: int) -> dict[str, Any]:
        return self._json_request(
            "https://api.exa.ai/search",
            {
                "query": query,
                "type": self.settings.web_discovery_exa_mode,
                "numResults": max_results,
                "contents": {"highlights": {"maxCharacters": 1200}},
            },
            headers={"x-api-key": self.settings.exa_api_key},
            timeout=self.settings.web_discovery_request_timeout_seconds,
        )

    def _fetch_serper(self, query: str, max_results: int) -> dict[str, Any]:
        return self._json_request(
            "https://google.serper.dev/search",
            {"q": query, "num": max_results},
            headers={"X-API-KEY": self.settings.serper_api_key},
            timeout=self.settings.web_discovery_request_timeout_seconds,
        )

    def _index_candidate(
        self,
        *,
        provider: str,
        query: str,
        canonical_url: str,
        title: str,
        content: str,
        organization_id: int | None,
        minimum_words: int,
        seen_urls: set[str],
    ) -> dict[str, Any] | None:
        canonical_url = canonical_url.strip()
        parsed = urlparse(canonical_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or canonical_url in seen_urls:
            return None
        seen_urls.add(canonical_url)
        title = normalize_display_text(title)
        content = normalize_display_text(content).strip()[: self.settings.web_discovery_max_content_chars]
        if count_words(content) < minimum_words:
            return None
        namespace = str(organization_id) if organization_id is not None else "public"
        digest = hashlib.sha256(f"{namespace}:{canonical_url}".encode("utf-8")).hexdigest()[:32]
        source_id = self.storage.upsert_source(
            url=f"web-discovery://{namespace}/{digest}",
            canonical_url=canonical_url,
            title=(title.strip() or canonical_url)[:220],
            text_content=content,
            source_type=f"web-{provider}",
            metadata={"provider": provider, "query": query, "canonicalUrl": canonical_url},
            organization_id=organization_id,
        )
        return {"id": source_id, "title": (title.strip() or canonical_url)[:220], "url": canonical_url}

    @staticmethod
    def _json_request(
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> dict[str, Any]:
        request = Request(
            url,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers},
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    @staticmethod
    def _get_json(url: str, *, headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

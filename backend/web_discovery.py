from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from .text import count_words, normalize_display_text, split_sentences, tokenize


STOPWORDS = {
    "và", "của", "là", "các", "một", "những", "trong", "cho", "được", "với", "khi",
    "này", "đó", "để", "từ", "the", "and", "that", "this", "with", "from", "are",
    "was", "were", "have", "có", "đã", "đang", "không", "như", "theo", "về", "sẽ",
}
TRACKING_QUERY_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
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
            "queryStrategy": "adaptive-fingerprint-v2",
            "sources": sorted(self.sources, key=lambda item: item.get("relevanceScore", 0), reverse=True),
        }


def _informative_tokens(value: str) -> list[str]:
    return [token for token in tokenize(value) if len(token) >= 3 and token not in STOPWORDS]


def _candidate_windows(sentence: str) -> list[str]:
    words = re.findall(r"[\wÀ-ỹ]+", sentence, flags=re.UNICODE)
    if len(words) <= 32:
        return [sentence]
    windows = []
    for start in range(0, len(words), 16):
        window = words[start : start + 28]
        if len(window) >= 12:
            windows.append(" ".join(window))
        if start + 28 >= len(words):
            break
    return windows


def _query_overlap(left: str, right: str) -> float:
    left_tokens = set(_informative_tokens(left))
    right_tokens = set(_informative_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def _keyword_signature(value: str, frequencies: Counter[str], *, maximum: int = 8) -> str:
    tokens = set(_informative_tokens(value))
    ranked = sorted(tokens, key=lambda token: (frequencies[token], -len(token), token))
    return " ".join(ranked[:maximum])


def _exact_phrase_query(value: str, *, maximum_words: int = 18) -> str:
    words = re.findall(r"\w+", value, flags=re.UNICODE)[:maximum_words]
    return f'"{" ".join(words)}"' if words else ""


def build_queries(text: str, *, max_queries: int = 3) -> list[str]:
    document_tokens = _informative_tokens(text)
    frequencies = Counter(document_tokens)
    candidates: list[tuple[float, str]] = []
    for sentence in split_sentences(text):
        clean = re.sub(r"\s+", " ", sentence).strip(" \t\n\r\"'“”‘’.:,;()[]{}")
        for window in _candidate_windows(clean):
            words = tokenize(window)
            informative = set(_informative_tokens(window))
            if 10 <= len(words) <= 32 and len(informative) >= 5:
                rarity = sum(1 / max(1, frequencies[token]) for token in informative)
                candidates.append((len(informative) * 2 + rarity + min(len(words), 28) / 10, window[:360]))
    candidates.sort(reverse=True, key=lambda item: (item[0], len(item[1])))
    excerpt_budget = max_queries if max_queries <= 3 else max(2, round(max_queries * 0.7))
    excerpts: list[str] = []
    for _score, sentence in candidates:
        if sentence not in excerpts and all(_query_overlap(sentence, existing) < 0.72 for existing in excerpts):
            excerpts.append(sentence)
        if len(excerpts) >= excerpt_budget:
            break
    if excerpts:
        queries = [
            query
            for excerpt in excerpts
            if (query := _exact_phrase_query(excerpt))
        ]
        signatures = [
            *(_keyword_signature(excerpt, frequencies) for excerpt in excerpts),
            _keyword_signature(text, frequencies, maximum=10),
        ]
        added_signatures: list[str] = []
        for signature in signatures:
            if (
                signature
                and signature not in queries
                and all(_query_overlap(signature, existing) < 0.80 for existing in added_signatures)
            ):
                queries.append(signature)
                added_signatures.append(signature)
            if len(queries) >= max_queries:
                break
        for _score, sentence in candidates:
            if sentence not in queries and all(_query_overlap(sentence, existing) < 0.78 for existing in queries):
                queries.append(sentence)
            if len(queries) >= max_queries:
                break
        return queries[:max_queries]
    fallback_tokens = sorted(set(document_tokens), key=lambda token: (frequencies[token], -len(token), token))
    return [" ".join(fallback_tokens[:14])] if fallback_tokens else []


def normalize_candidate_url(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_PARAMETERS
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", urlencode(query), ""))


def _longest_shared_phrase(left: list[str], right: list[str]) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    longest = 0
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            matched = previous[index - 1] + 1 if left_token == right_token else 0
            current.append(matched)
            longest = max(longest, matched)
        previous = current
    return longest


def candidate_relevance(query: str, title: str, content: str) -> float:
    ordered_query_tokens = _informative_tokens(query)
    ordered_content_tokens = _informative_tokens(content)
    query_tokens = set(ordered_query_tokens)
    if not query_tokens:
        return 0.0
    title_tokens = set(_informative_tokens(title))
    content_tokens = set(ordered_content_tokens)
    title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
    content_overlap = len(query_tokens & content_tokens) / len(query_tokens)
    shared = len(query_tokens & (title_tokens | content_tokens))
    if shared < 2:
        return 0.0
    phrase_length = _longest_shared_phrase(ordered_query_tokens, ordered_content_tokens)
    phrase_signal = min(1.0, phrase_length / 6)
    return min(1.0, content_overlap * 0.65 + title_overlap * 0.20 + phrase_signal * 0.35)


def _normalized_url_set(urls: set[str] | None = None) -> set[str]:
    return {normalized for url in urls or set() if (normalized := normalize_candidate_url(url))}


class WebDiscovery:
    def __init__(self, settings: Any, storage: Any):
        self.settings = settings
        self.storage = storage
        self.crawler: Any | None = None
        self._enrichment_lock = threading.Lock()
        self._enrichment_remaining = 0
        self._active_deadline = 0.0

    def attach_crawler(self, crawler: Any) -> None:
        self.crawler = crawler

    def status(self) -> dict[str, bool]:
        return {
            "tavily": bool(self.settings.tavily_api_key),
            "exa": bool(self.settings.exa_api_key),
            "websearchapi": bool(self.settings.websearchapi_api_key),
            "linkup": bool(self.settings.linkup_api_key),
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
        self._active_deadline = time.monotonic() + self.settings.web_discovery_time_budget_seconds
        with self._enrichment_lock:
            self._enrichment_remaining = self.settings.web_discovery_enrichment_max_sources
        queries = build_queries(text, max_queries=self.settings.web_discovery_max_queries)
        if not queries:
            return DiscoveryResult(
                "none", False, False, [], 0, 0,
                "Không tạo được truy vấn tìm kiếm từ tài liệu.", [],
            ).to_dict()
        result_limit = max_results or self.settings.web_discovery_max_results
        result_limit = max(1, min(20, int(result_limit)))
        result: DiscoveryResult | None = None
        if self.settings.serper_api_key and self._time_available():
            result = self._serper(
                queries[: self.settings.web_discovery_serper_max_queries],
                organization_id,
                min(3, result_limit),
                progress_callback,
            )
        if (
            self.settings.tavily_api_key
            and (result is None or self._time_available())
            and self._remaining_result_limit(result_limit, result) > 0
        ):
            primary = self._tavily(
                queries,
                organization_id,
                self._remaining_result_limit(result_limit, result),
                progress_callback,
            )
            result = primary if result is None else self._merge_results(result, primary)
        if (
            self.settings.exa_api_key
            and self._time_available()
            and (result is None or result.indexed < self.settings.web_discovery_fallback_min_sources)
            and self._remaining_result_limit(result_limit, result) > 0
        ):
            fallback = self._exa(
                queries[: self.settings.web_discovery_exa_max_queries],
                organization_id,
                self._remaining_result_limit(result_limit, result),
                progress_callback,
                initial_seen_urls={source["url"] for source in result.sources} if result else None,
            )
            result = fallback if result is None else self._merge_results(result, fallback)
        if (
            self.settings.websearchapi_api_key
            and self._time_available()
            and (result is None or result.indexed < self.settings.web_discovery_fallback_min_sources)
            and self._remaining_result_limit(result_limit, result) > 0
        ):
            fallback = self._websearchapi(
                queries[: self.settings.web_discovery_websearchapi_max_queries],
                organization_id,
                self._remaining_result_limit(result_limit, result),
                progress_callback,
                initial_seen_urls={source["url"] for source in result.sources} if result else None,
            )
            result = fallback if result is None else self._merge_results(result, fallback)
        if (
            self.settings.linkup_api_key
            and self._time_available()
            and (result is None or result.indexed < self.settings.web_discovery_fallback_min_sources)
            and self._remaining_result_limit(result_limit, result) > 0
        ):
            fallback = self._linkup(
                queries[: self.settings.web_discovery_linkup_max_queries],
                organization_id,
                self._remaining_result_limit(result_limit, result),
                progress_callback,
                initial_seen_urls={source["url"] for source in result.sources} if result else None,
            )
            result = fallback if result is None else self._merge_results(result, fallback)
        if result is not None:
            return result.to_dict()
        if self.settings.brave_search_api_key and self._time_available():
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
            "Chưa cấu hình Tavily, Exa, WebSearchAPI.ai, Linkup, Serper hoặc Brave nên hệ thống chỉ đối chiếu kho nguồn đã có.",
            [],
        ).to_dict()

    @staticmethod
    def _remaining_result_limit(result_limit: int, result: DiscoveryResult | None) -> int:
        return max(0, min(10, result_limit - (result.indexed if result else 0)))

    @staticmethod
    def _merge_results(primary: DiscoveryResult, fallback: DiscoveryResult) -> DiscoveryResult:
        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for source in [*primary.sources, *fallback.sources]:
            canonical_url = normalize_candidate_url(source["url"])
            if canonical_url and canonical_url not in seen_urls:
                sources.append(source)
                seen_urls.add(canonical_url)
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
                as_completed(pending, timeout=self._phase_timeout()),
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
                    if len(sources) >= max_results or not self._time_available(0.25):
                        break
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
                as_completed(pending, timeout=self._phase_timeout()),
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
                    if len(sources) >= max_results or not self._time_available(0.25):
                        break
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
        seen_urls = _normalized_url_set(initial_seen_urls)
        errors: list[str] = []
        workers = min(len(queries), self.settings.web_discovery_parallel_workers)
        timed_out = 0
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            pending = {executor.submit(self._fetch_exa, query, max_results): query for query in queries}
            for completed, future in enumerate(
                as_completed(pending, timeout=self._phase_timeout()),
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
                    if len(sources) >= max_results or not self._time_available(0.25):
                        break
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
        seen_urls = _normalized_url_set(initial_seen_urls)
        errors: list[str] = []
        workers = min(len(queries), self.settings.web_discovery_parallel_workers)
        timed_out = 0
        executor = ThreadPoolExecutor(max_workers=max(1, workers))
        try:
            pending = {executor.submit(self._fetch_serper, query, max_results): query for query in queries}
            for completed, future in enumerate(
                as_completed(pending, timeout=self._phase_timeout()),
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
                    if len(sources) >= max_results or not self._time_available(0.25):
                        break
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

    def _websearchapi(
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
        seen_urls = _normalized_url_set(initial_seen_urls)
        errors: list[str] = []
        for completed, query in enumerate(queries, start=1):
            if not self._time_available():
                break
            try:
                data = self._fetch_websearchapi(query, max_results)
            except Exception as error:
                errors.append(str(error))
                if progress_callback:
                    progress_callback(completed, len(queries), len(sources))
                continue
            for item in data.get("organic", []):
                if len(sources) >= max_results or not self._time_available(0.25):
                    break
                indexed = self._index_candidate(
                    provider="websearchapi",
                    query=query,
                    canonical_url=str(item.get("url") or ""),
                    title=str(item.get("title") or ""),
                    content=str(item.get("description") or item.get("content") or ""),
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
        message = (
            f"Đã bổ sung {len(sources)} nguồn web công khai qua WebSearchAPI.ai fallback."
            if sources else "WebSearchAPI.ai fallback không trả về nguồn mới đủ nội dung để lập chỉ mục."
        )
        if errors:
            message += f" Có {len(errors)} truy vấn gặp lỗi."
        return DiscoveryResult("websearchapi", True, True, queries, len(sources), skipped, message, sources)

    def _linkup(
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
        seen_urls = _normalized_url_set(initial_seen_urls)
        errors: list[str] = []
        for completed, query in enumerate(queries, start=1):
            if not self._time_available():
                break
            try:
                data = self._fetch_linkup(query, max_results)
            except Exception as error:
                errors.append(str(error))
                if progress_callback:
                    progress_callback(completed, len(queries), len(sources))
                continue
            for item in data.get("results", []):
                if len(sources) >= max_results or not self._time_available(0.25):
                    break
                indexed = self._index_candidate(
                    provider="linkup",
                    query=query,
                    canonical_url=str(item.get("url") or ""),
                    title=str(item.get("name") or ""),
                    content=str(item.get("content") or ""),
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
        message = (
            f"Đã bổ sung {len(sources)} nguồn web công khai qua Linkup fallback."
            if sources else "Linkup fallback không trả về nguồn mới đủ nội dung để lập chỉ mục."
        )
        if errors:
            message += f" Có {len(errors)} truy vấn gặp lỗi."
        return DiscoveryResult("linkup", True, True, queries, len(sources), skipped, message, sources)

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
            timeout=self._request_timeout(),
        )

    def _fetch_brave(self, query: str, max_results: int) -> dict[str, Any]:
        return self._get_json(
            f"https://api.search.brave.com/res/v1/web/search?q={quote_plus(query)}&count={max_results}",
            headers={"X-Subscription-Token": self.settings.brave_search_api_key},
            timeout=self._request_timeout(),
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
            timeout=self._request_timeout(),
        )

    def _fetch_serper(self, query: str, max_results: int) -> dict[str, Any]:
        return self._json_request(
            "https://google.serper.dev/search",
            {"q": query, "num": max_results},
            headers={"X-API-KEY": self.settings.serper_api_key},
            timeout=self._request_timeout(),
        )

    def _fetch_websearchapi(self, query: str, max_results: int) -> dict[str, Any]:
        return self._json_request(
            "https://api.websearchapi.ai/ai-search",
            {
                "query": query,
                "maxResults": max_results,
                "includeContent": False,
                "includeAnswer": False,
                "safeSearch": True,
            },
            headers={"Authorization": f"Bearer {self.settings.websearchapi_api_key}"},
            timeout=self._request_timeout(),
        )

    def _fetch_linkup(self, query: str, max_results: int) -> dict[str, Any]:
        return self._json_request(
            "https://api.linkup.so/v1/search",
            {
                "q": query,
                "depth": self.settings.web_discovery_linkup_depth,
                "outputType": "searchResults",
                "includeImages": False,
                "maxResults": max_results,
            },
            headers={"Authorization": f"Bearer {self.settings.linkup_api_key}"},
            timeout=self._request_timeout(),
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
        canonical_url = normalize_candidate_url(canonical_url)
        if not canonical_url or canonical_url in seen_urls:
            return None
        title = normalize_display_text(title)
        content = normalize_display_text(content).strip()[: self.settings.web_discovery_max_content_chars]
        if count_words(content) < minimum_words:
            return None
        relevance = candidate_relevance(query, title, content)
        if relevance < 0.18:
            return None
        content, enriched = self._enrich_content(canonical_url, content, relevance=relevance)
        relevance = candidate_relevance(query, title, content)
        seen_urls.add(canonical_url)
        namespace = str(organization_id) if organization_id is not None else "public"
        digest = hashlib.sha256(f"{namespace}:{canonical_url}".encode("utf-8")).hexdigest()[:32]
        source_id = self.storage.upsert_source(
            url=f"web-discovery://{namespace}/{digest}",
            canonical_url=canonical_url,
            title=(title.strip() or canonical_url)[:220],
            text_content=content,
            source_type=f"web-{provider}",
            metadata={
                "provider": provider,
                "query": query,
                "canonicalUrl": canonical_url,
                "relevanceScore": round(relevance, 3),
                "enrichedFromPublicPage": enriched,
            },
            organization_id=organization_id,
        )
        return {
            "id": source_id,
            "title": (title.strip() or canonical_url)[:220],
            "url": canonical_url,
            "relevanceScore": round(relevance, 3),
        }

    def _enrich_content(self, canonical_url: str, content: str, *, relevance: float = 1.0) -> tuple[str, bool]:
        if relevance < 0.72 or not self.crawler or count_words(content) >= 140 or not self._time_available(4.0):
            return content, False
        with self._enrichment_lock:
            if self._enrichment_remaining <= 0:
                return content, False
            self._enrichment_remaining -= 1
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._fetch_enriched_content, canonical_url)
            enriched = future.result(timeout=min(3.0, max(0.5, self._time_remaining() - 1.0)))
            if count_words(enriched) > count_words(content):
                return enriched, True
        except Exception:
            return content, False
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return content, False

    def _fetch_enriched_content(self, canonical_url: str) -> str:
        try:
            normalized = self.crawler.url_policy.validate(canonical_url)
            if not self.crawler.robots.allowed(normalized):
                return ""
            result = self.crawler._fetch(normalized)
            return normalize_display_text(result.text).strip()[: self.settings.web_discovery_max_content_chars]
        except Exception:
            return ""

    def _time_remaining(self) -> float:
        if not self._active_deadline:
            return self.settings.web_discovery_time_budget_seconds
        return max(0.0, self._active_deadline - time.monotonic())

    def _time_available(self, minimum_seconds: float = 0.75) -> bool:
        return self._time_remaining() >= minimum_seconds

    def _phase_timeout(self) -> float:
        return max(0.001, min(self.settings.web_discovery_time_budget_seconds, self._time_remaining()))

    def _request_timeout(self) -> float:
        return max(0.5, min(self.settings.web_discovery_request_timeout_seconds, self._time_remaining()))

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

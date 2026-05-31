from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .text import count_words, split_sentences


VI_STOPWORDS = {
    "và", "của", "là", "các", "một", "những", "trong", "cho", "được", "với", "khi", "này",
    "đó", "để", "từ", "the", "and", "that", "this", "with", "from", "are", "was", "were", "have"
}


@dataclass
class DiscoveryResult:
    provider: str
    enabled: bool
    queries: list[str]
    indexed: int
    skipped: int
    message: str
    sources: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "queries": self.queries,
            "indexed": self.indexed,
            "skipped": self.skipped,
            "message": self.message,
            "sources": self.sources,
        }


def build_queries(text: str, *, max_queries: int = 3) -> list[str]:
    sentences = []
    for sentence in split_sentences(text):
        clean = re.sub(r"\s+", " ", sentence).strip(" \t\n\r\"'“”‘’.:,;()[]{}")
        words = re.findall(r"[\wÀ-ỹ]+", clean, flags=re.UNICODE)
        if 10 <= len(words) <= 32:
            distinct = len({word.lower() for word in words if word.lower() not in VI_STOPWORDS})
            sentences.append((distinct, clean))
    sentences.sort(reverse=True, key=lambda item: (item[0], len(item[1])))
    queries = []
    for _score, sentence in sentences:
        if sentence not in queries:
            queries.append(sentence)
        if len(queries) >= max_queries:
            break
    if queries:
        return queries
    tokens = [token.lower() for token in re.findall(r"[\wÀ-ỹ]+", text, flags=re.UNICODE) if token.lower() not in VI_STOPWORDS]
    return [" ".join(tokens[:14])] if tokens else []


class WebDiscovery:
    def __init__(self, settings: Any, storage: Any):
        self.settings = settings
        self.storage = storage

    def discover_and_index(self, text: str, *, organization_id: int | None = None, max_results: int = 5) -> dict[str, Any]:
        queries = build_queries(text)
        if not queries:
            return DiscoveryResult("none", False, [], 0, 0, "Không tạo được truy vấn tìm kiếm từ tài liệu.", []).to_dict()
        if self.settings.tavily_api_key:
            return self._tavily(queries, organization_id=organization_id, max_results=max_results).to_dict()
        if self.settings.brave_search_api_key:
            return self._brave(queries, organization_id=organization_id, max_results=max_results).to_dict()
        return DiscoveryResult(
            "not-configured",
            False,
            queries,
            0,
            0,
            "Chưa cấu hình TAVILY_API_KEY hoặc BRAVE_SEARCH_API_KEY nên hệ thống chỉ đối chiếu kho đã có.",
            [],
        ).to_dict()

    def _tavily(self, queries: list[str], *, organization_id: int | None, max_results: int) -> DiscoveryResult:
        indexed = 0
        skipped = 0
        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for query in queries:
            payload = {
                "query": query,
                "search_depth": "basic",
                "max_results": max(1, min(8, max_results)),
                "include_raw_content": True,
                "include_answer": False,
            }
            try:
                data = self._json_request(
                    "https://api.tavily.com/search",
                    payload,
                    headers={"Authorization": f"Bearer {self.settings.tavily_api_key}"},
                    timeout=20,
                )
            except Exception as error:
                return DiscoveryResult("tavily", True, queries, indexed, skipped, f"Tavily lỗi: {error}", sources)
            for item in data.get("results", []):
                url = str(item.get("url") or "").strip()
                if not url or url in seen_urls:
                    skipped += 1
                    continue
                seen_urls.add(url)
                title = str(item.get("title") or url).strip()[:220]
                content = str(item.get("raw_content") or item.get("content") or "").strip()
                if count_words(content) < 40:
                    skipped += 1
                    continue
                try:
                    source_id = self.storage.upsert_source(
                        url=url,
                        canonical_url=url,
                        title=title,
                        text_content=content,
                        source_type="web-auto",
                        metadata={"provider": "tavily", "query": query},
                        organization_id=organization_id,
                    )
                    indexed += 1
                    sources.append({"id": source_id, "title": title, "url": url})
                except Exception:
                    skipped += 1
        message = f"Đã tìm và lập chỉ mục {indexed} nguồn web công khai qua Tavily." if indexed else "Tavily không trả về nguồn đủ nội dung để lập chỉ mục."
        return DiscoveryResult("tavily", True, queries, indexed, skipped, message, sources)

    def _brave(self, queries: list[str], *, organization_id: int | None, max_results: int) -> DiscoveryResult:
        indexed = 0
        skipped = 0
        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for query in queries:
            url = f"https://api.search.brave.com/res/v1/web/search?q={self._quote(query)}&count={max(1, min(10, max_results))}"
            try:
                data = self._get_json(url, headers={"X-Subscription-Token": self.settings.brave_search_api_key}, timeout=15)
            except Exception as error:
                return DiscoveryResult("brave", True, queries, indexed, skipped, f"Brave lỗi: {error}", sources)
            for item in (data.get("web") or {}).get("results", []):
                page_url = str(item.get("url") or "").strip()
                if not page_url or page_url in seen_urls:
                    skipped += 1
                    continue
                seen_urls.add(page_url)
                title = str(item.get("title") or page_url).strip()[:220]
                content = " ".join([str(item.get("description") or ""), str(item.get("extra_snippets") or "")]).strip()
                if count_words(content) < 18:
                    skipped += 1
                    continue
                source_id = self.storage.upsert_source(
                    url=page_url,
                    canonical_url=page_url,
                    title=title,
                    text_content=content,
                    source_type="web-search-snippet",
                    metadata={"provider": "brave", "query": query},
                    organization_id=organization_id,
                )
                indexed += 1
                sources.append({"id": source_id, "title": title, "url": page_url})
        message = f"Đã lập chỉ mục {indexed} kết quả/tóm tắt từ Brave. Nên dùng Tavily nếu muốn trích xuất nội dung đầy đủ hơn."
        return DiscoveryResult("brave", True, queries, indexed, skipped, message, sources)

    @staticmethod
    def _quote(value: str) -> str:
        from urllib.parse import quote_plus
        return quote_plus(value)

    @staticmethod
    def _json_request(url: str, payload: dict[str, Any], *, headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request = Request(url, method="POST", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json", **headers})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    @staticmethod
    def _get_json(url: str, *, headers: dict[str, str], timeout: float) -> dict[str, Any]:
        request = Request(url, headers=headers)
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .text import search_terms


class SearchBackend(Protocol):
    name: str

    def search_chunks(
        self,
        text: str,
        limit: int = 100,
        organization_id: int | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def replace_source(self, source_id: int, documents: list[dict[str, Any]]) -> None:
        ...

    def delete_source(self, source_id: int) -> None:
        ...

    def rebuild(self, storage: Any) -> dict[str, int]:
        ...

    def status(self) -> dict[str, Any]:
        ...


@dataclass
class SQLiteFtsSearchBackend:
    storage: Any
    name: str = "sqlite-fts5"

    def search_chunks(
        self,
        text: str,
        limit: int = 100,
        organization_id: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.storage.search_chunks(text, limit, organization_id)

    def replace_source(self, source_id: int, documents: list[dict[str, Any]]) -> None:
        return

    def delete_source(self, source_id: int) -> None:
        return

    def rebuild(self, storage: Any) -> dict[str, int]:
        return {"sources": int(storage.stats()["sources"]), "chunks": int(storage.stats()["chunks"])}

    def status(self) -> dict[str, Any]:
        return {"backend": self.name, "ok": True}


class OpenSearchBackend:
    name = "opensearch"

    def __init__(self, base_url: str, index_name: str, timeout_seconds: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.index_name = index_name
        self.timeout_seconds = timeout_seconds
        self.ensure_index()

    def ensure_index(self) -> None:
        payload = {
            "mappings": {
                "properties": {
                    "source_id": {"type": "long"},
                    "organization_id": {"type": "long"},
                    "chunk_id": {"type": "long"},
                    "title": {"type": "text"},
                    "url": {"type": "keyword"},
                    "source_type": {"type": "keyword"},
                    "text_content": {"type": "text"},
                    "normalized_text": {"type": "text"},
                    "folded_text": {"type": "text"},
                    "token_count": {"type": "integer"},
                }
            }
        }
        try:
            self._request("PUT", f"/{quote(self.index_name)}", payload)
        except HTTPError as error:
            if error.code != 400:
                raise

    def search_chunks(
        self,
        text: str,
        limit: int = 100,
        organization_id: int | None = None,
    ) -> list[dict[str, Any]]:
        terms = search_terms(text)
        if not terms:
            return []
        response = self._request(
            "POST",
            f"/{quote(self.index_name)}/_search",
            {
                "size": limit,
                "_source": [
                    "chunk_id",
                    "text_content",
                    "token_count",
                    "source_id",
                    "url",
                    "title",
                    "source_type",
                ],
                "query": self._search_query(terms, organization_id),
            },
        )
        return [hit["_source"] for hit in response.get("hits", {}).get("hits", [])]

    @staticmethod
    def _search_query(terms: list[str], organization_id: int | None) -> dict[str, Any]:
        text_query = {
            "multi_match": {
                "query": " ".join(terms),
                "fields": ["normalized_text", "folded_text"],
                "operator": "or",
            }
        }
        if organization_id is None:
            return {"bool": {"must": [text_query], "must_not": [{"exists": {"field": "organization_id"}}]}}
        return {
            "bool": {
                "must": [text_query],
                "filter": [
                    {
                        "bool": {
                            "should": [
                                {"bool": {"must_not": [{"exists": {"field": "organization_id"}}]}},
                                {"term": {"organization_id": organization_id}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ],
            }
        }

    def replace_source(self, source_id: int, documents: list[dict[str, Any]]) -> None:
        self.delete_source(source_id)
        if not documents:
            return
        lines = []
        for document in documents:
            document_id = f"{source_id}-{document['chunk_id']}"
            lines.append(json.dumps({"index": {"_index": self.index_name, "_id": document_id}}))
            lines.append(json.dumps(document, ensure_ascii=False))
        self._request_raw("POST", "/_bulk", ("\n".join(lines) + "\n").encode("utf-8"), "application/x-ndjson")

    def delete_source(self, source_id: int) -> None:
        self._request(
            "POST",
            f"/{quote(self.index_name)}/_delete_by_query?conflicts=proceed&refresh=true",
            {"query": {"term": {"source_id": source_id}}},
        )

    def rebuild(self, storage: Any) -> dict[str, int]:
        source_ids = storage.list_search_source_ids()
        chunks = 0
        for source_id in source_ids:
            documents = storage.get_source_search_documents(source_id)
            self.replace_source(source_id, documents)
            chunks += len(documents)
        return {"sources": len(source_ids), "chunks": chunks}

    def status(self) -> dict[str, Any]:
        response = self._request("GET", "/")
        return {
            "backend": self.name,
            "ok": True,
            "clusterName": response.get("cluster_name"),
            "index": self.index_name,
        }

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        raw = self._request_raw(method, path, body, "application/json")
        return json.loads(raw.decode("utf-8") or "{}")

    def _request_raw(self, method: str, path: str, body: bytes | None, content_type: str) -> bytes:
        request = Request(
            f"{self.base_url}{path}",
            method=method,
            data=body,
            headers={"Content-Type": content_type},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read()


def create_search_backend(settings: Any, storage: Any) -> SearchBackend:
    if settings.search_backend == "sqlite":
        return SQLiteFtsSearchBackend(storage, name=getattr(storage, "search_backend_name", "sqlite-fts5"))
    if settings.search_backend == "opensearch":
        return OpenSearchBackend(
            settings.opensearch_url,
            settings.opensearch_index,
            settings.opensearch_timeout_seconds,
        )
    raise ValueError(f"Bộ máy tìm kiếm chưa được hỗ trợ: {settings.search_backend}")

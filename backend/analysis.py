from __future__ import annotations

from collections import defaultdict
from typing import Any

from .integrity import scan_text
from .search import SearchBackend
from .text import (
    count_words,
    fold_text,
    has_citation,
    is_bibliography_heading,
    is_quoted,
    similarity,
    split_sentences,
)


class SimilarityAnalyzer:
    def __init__(self, search_backend: SearchBackend):
        self.search_backend = search_backend

    def analyze(
        self,
        text: str,
        *,
        minimum_words: int = 8,
        exclude_quotes: bool = True,
        exclude_bibliography: bool = True,
        threshold: float = 0.70,
        organization_id: int | None = None,
    ) -> dict[str, Any]:
        bibliography = False
        segments: list[dict[str, Any]] = []
        matched_sources: dict[int, dict[str, Any]] = {}
        matched_words = 0
        match_number = 0
        document_candidates = self.search_backend.search_chunks(text, limit=500, organization_id=organization_id)

        def score_candidates(segment: str, candidates: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
            folded_segment = fold_text(segment)
            exact = [
                (1.0, candidate)
                for candidate in candidates
                if folded_segment and folded_segment in fold_text(candidate["text_content"])
            ]
            if exact:
                return exact
            scored = []
            for candidate in candidates:
                score = similarity(segment, candidate["text_content"])
                if score >= threshold:
                    scored.append((score, candidate))
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored

        for raw_segment in split_sentences(text):
            words = count_words(raw_segment)
            if raw_segment == "\n":
                segments.append({"text": raw_segment, "kind": "plain", "words": 0})
                continue

            if is_bibliography_heading(raw_segment):
                bibliography = True

            quoted = is_quoted(raw_segment)
            cited = has_citation(raw_segment)
            excluded_reason = None
            if exclude_quotes and quoted:
                excluded_reason = "Trích dẫn"
            elif exclude_bibliography and bibliography:
                excluded_reason = "Tài liệu tham khảo"

            if excluded_reason:
                segments.append(
                    {
                        "text": raw_segment,
                        "kind": "excluded",
                        "words": words,
                        "reason": excluded_reason,
                    }
                )
                continue

            if words < minimum_words:
                segments.append({"text": raw_segment, "kind": "plain", "words": words})
                continue

            scored = score_candidates(raw_segment, document_candidates)
            if not scored:
                scored = score_candidates(
                    raw_segment,
                    self.search_backend.search_chunks(raw_segment, organization_id=organization_id),
                )

            if not scored:
                segments.append({"text": raw_segment, "kind": "plain", "words": words})
                continue

            best_score, best = scored[0]
            match_number += 1
            matched_words += words
            source = {
                "id": best["source_id"],
                "title": best["title"],
                "url": best["url"],
                "type": best["source_type"],
            }
            category = self._category(quoted=quoted, cited=cited)
            alternatives = []
            seen_source_ids = {best["source_id"]}
            for alternative_score, alternative in scored[1:]:
                if alternative["source_id"] in seen_source_ids:
                    continue
                seen_source_ids.add(alternative["source_id"])
                alternatives.append(
                    {
                        "id": alternative["source_id"],
                        "title": alternative["title"],
                        "url": alternative["url"],
                        "confidence": round(alternative_score * 100),
                    }
                )
                if len(alternatives) == 3:
                    break

            segments.append(
                {
                    "text": raw_segment,
                    "kind": "match",
                    "words": words,
                    "number": match_number,
                    "confidence": round(best_score * 100),
                    "category": category,
                    "source": source,
                    "alternative_sources": alternatives,
                }
            )

            aggregate = matched_sources.setdefault(
                int(best["source_id"]),
                {
                    **source,
                    "matchedWords": 0,
                    "matches": 0,
                    "numbers": [],
                    "categories": defaultdict(int),
                },
            )
            aggregate["matchedWords"] += words
            aggregate["matches"] += 1
            aggregate["numbers"].append(match_number)
            aggregate["categories"][category] += 1

        total_words = count_words(text)
        percent = min(100, round((matched_words / total_words) * 100)) if total_words else 0
        sources = []
        for source in matched_sources.values():
            source["categories"] = dict(source["categories"])
            sources.append(source)
        sources.sort(key=lambda item: item["matchedWords"], reverse=True)

        return {
            "text": text,
            "totalWords": total_words,
            "matchedWords": matched_words,
            "percent": percent,
            "segments": segments,
            "sources": sources,
            "matchedSegments": [segment for segment in segments if segment["kind"] == "match"],
            "integrityFlags": scan_text(text),
            "settings": {
                "minimumWords": minimum_words,
                "excludeQuotes": exclude_quotes,
                "excludeBibliography": exclude_bibliography,
                "threshold": threshold,
            },
        }

    @staticmethod
    def _category(*, quoted: bool, cited: bool) -> str:
        if quoted and cited:
            return "cited_and_quoted"
        if quoted:
            return "missing_citation"
        if cited:
            return "missing_quotation"
        return "not_cited_or_quoted"

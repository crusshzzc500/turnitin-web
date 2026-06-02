from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .text import count_words, normalize_display_text


class CitationWritingAssistant:
    def __init__(self, settings: Any):
        self.settings = settings

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.settings.gemini_api_key),
            "model": self.settings.gemini_model,
            "mode": "citation-guided-revision",
        }

    def revise(self, text: str, report: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.gemini_api_key:
            raise ValueError("Chưa cấu hình Gemini API key cho trợ lý chỉnh sửa.")
        clean_text = normalize_display_text(text).strip()
        if count_words(clean_text) < 20:
            raise ValueError("Tài liệu cần có ít nhất 20 từ để tạo bản đề xuất.")
        if len(clean_text) > self.settings.gemini_revision_max_input_chars:
            raise ValueError(
                "Tài liệu quá dài cho một lượt chỉnh sửa AI. "
                f"Hãy chia thành phần nhỏ dưới {self.settings.gemini_revision_max_input_chars:,} ký tự."
            )

        source_context = self._source_context(report)
        prompt = (
            "You are a citation-aware academic writing coach. Improve clarity and citation hygiene for the "
            "submitted draft. Do not help evade plagiarism detection, conceal copying, imitate a human to bypass "
            "AI detectors, or claim the result is original. Preserve the author's meaning. For any borrowed idea "
            "supported by a listed source, add an inline marker such as [Nguồn 1]. Keep direct quotations in "
            "quotation marks with a marker. If a passage appears borrowed but no reliable source is listed, mark "
            "it [Cần trích dẫn nguồn] instead of disguising it. Return a complete revised draft plus concise notes. "
            "Do not invent sources or URLs.\n\n"
            f"AVAILABLE VERIFIED SOURCES AND MATCHED EXCERPTS:\n{source_context}\n\n"
            f"SUBMITTED DRAFT:\n{clean_text}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": {
                    "type": "object",
                    "properties": {
                        "revision": {
                            "type": "string",
                            "description": "Complete citation-aware revised draft.",
                        },
                        "editorNotes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 8,
                        },
                        "citationNotes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "marker": {"type": "string"},
                                    "sourceTitle": {"type": "string"},
                                    "sourceUrl": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                                "required": ["marker", "sourceTitle", "sourceUrl", "reason"],
                                "additionalProperties": False,
                            },
                            "maxItems": 12,
                        },
                    },
                    "required": ["revision", "editorNotes", "citationNotes"],
                    "additionalProperties": False,
                },
                "thinkingConfig": {"thinkingLevel": "high"},
                "maxOutputTokens": 8192,
                "temperature": 0.3,
            },
        }
        try:
            response = self._json_request(
                (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{quote(self.settings.gemini_model, safe='')}:generateContent"
                ),
                payload,
                headers={"x-goog-api-key": self.settings.gemini_api_key},
                timeout=self.settings.gemini_revision_timeout_seconds,
            )
        except Exception as error:
            raise ValueError(
                "Gemini chưa thể tạo bản đề xuất. Hãy kiểm tra API key, hạn mức miễn phí hoặc thử lại sau."
            ) from error
        try:
            result = json.loads(self._output_text(response))
        except json.JSONDecodeError as error:
            raise ValueError("Gemini không trả về bản chỉnh sửa đúng định dạng.") from error
        revision = normalize_display_text(str(result.get("revision", ""))).strip()
        if count_words(revision) < 20:
            raise ValueError("Gemini chưa tạo được bản đề xuất đủ nội dung.")
        return {
            "revision": revision,
            "editorNotes": self._clean_string_list(result.get("editorNotes"), maximum=8),
            "citationNotes": self._clean_citation_notes(result.get("citationNotes")),
            "model": self.settings.gemini_model,
            "mode": "citation-guided-revision",
            "notice": (
                "Đây là bản đề xuất hỗ trợ dẫn nguồn, không phải chứng nhận nguyên gốc. "
                "Hãy đọc lại, kiểm tra nguồn và tuân thủ quy định của nơi bạn nộp bài."
            ),
        }

    @staticmethod
    def _source_context(report: dict[str, Any]) -> str:
        sources = report.get("sources") or []
        matched_segments = report.get("matchedSegments") or []
        coverage = (report.get("webDiscovery") or {}).get("regionalCoverage") or {}
        coverage_note = ""
        if coverage:
            coverage_note = (
                "PUBLIC-WEB REGIONAL EVIDENCE: "
                f"searched {coverage.get('searchedRegions', 0)}/{coverage.get('totalRegions', 0)} regions; "
                f"verified URL evidence {coverage.get('evidenceRegions', 0)}/{coverage.get('totalRegions', 0)} regions. "
                "Missing public-web evidence does not prove originality. Keep [Cần trích dẫn nguồn] markers "
                "where attribution still needs manual review."
            )
        if not sources and not matched_segments:
            return "\n".join(
                note
                for note in [
                    coverage_note,
                    "No verified source was found. Use [Cần trích dẫn nguồn] for any passage that still needs attribution.",
                ]
                if note
            )
        lines = [coverage_note] if coverage_note else []
        source_numbers: dict[int, int] = {}
        for number, source in enumerate(sources[:12], start=1):
            source_id = int(source.get("id") or 0)
            source_numbers[source_id] = number
            lines.append(
                f"[Nguồn {number}] {str(source.get('title') or 'Nguồn chưa đặt tên')[:220]} | "
                f"{str(source.get('url') or 'Không có URL')[:500]}"
            )
        for segment in matched_segments[:16]:
            source = segment.get("source") or {}
            number = source_numbers.get(int(source.get("id") or 0))
            marker = f"[Nguồn {number}]" if number else "[Cần trích dẫn nguồn]"
            lines.append(f"{marker} Matched excerpt: {str(segment.get('text') or '')[:800]}")
        return "\n".join(lines)[:14_000]

    @staticmethod
    def _clean_string_list(value: Any, *, maximum: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:500] for item in value if str(item).strip()][:maximum]

    @staticmethod
    def _clean_citation_notes(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        notes = []
        for item in value[:12]:
            if not isinstance(item, dict):
                continue
            notes.append(
                {
                    "marker": str(item.get("marker") or "").strip()[:80],
                    "sourceTitle": str(item.get("sourceTitle") or "").strip()[:220],
                    "sourceUrl": str(item.get("sourceUrl") or "").strip()[:500],
                    "reason": str(item.get("reason") or "").strip()[:500],
                }
            )
        return notes

    @staticmethod
    def _output_text(response: dict[str, Any]) -> str:
        for candidate in response.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                if isinstance(part.get("text"), str):
                    return str(part["text"])
        return "{}"

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

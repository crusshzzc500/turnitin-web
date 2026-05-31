from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from difflib import SequenceMatcher

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?|\n", re.UNICODE)
CITATION_RE = re.compile(
    r"(\[[0-9,\-\s]+\]|\([A-ZÀ-Ỹ][^)]*,\s*(?:19|20)\d{2}[a-z]?\))",
    re.UNICODE,
)
BIBLIOGRAPHY_RE = re.compile(
    r"^(tài liệu tham khảo|tham khảo|references|bibliography)\s*:?\s*$",
    re.IGNORECASE | re.UNICODE,
)

VIETNAMESE_STOPWORDS = {
    "bị",
    "bởi",
    "các",
    "cái",
    "cần",
    "cho",
    "có",
    "của",
    "đã",
    "đang",
    "để",
    "đến",
    "được",
    "hay",
    "khi",
    "không",
    "là",
    "một",
    "này",
    "những",
    "nên",
    "như",
    "phải",
    "sẽ",
    "theo",
    "thì",
    "trong",
    "từ",
    "và",
    "về",
    "với",
}

MOJIBAKE_MARKERS = ("Ã", "Â", "Ä", "áº", "á»", "â€", "ðŸ")


def _mojibake_score(value: str) -> int:
    return sum(value.count(marker) for marker in MOJIBAKE_MARKERS) + (value.count("\ufffd") * 4)


def normalize_display_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    baseline_score = _mojibake_score(normalized)
    if not baseline_score:
        return normalized
    for encoding in ("latin-1", "cp1252"):
        try:
            candidate = normalized.encode(encoding).decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        candidate = unicodedata.normalize("NFC", candidate)
        score = _mojibake_score(candidate)
        if score < baseline_score:
            normalized = candidate
            baseline_score = score
    return normalized


def normalize_text(value: str) -> str:
    return " ".join(tokenize(value))


def fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", normalize_text(value))
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def tokenize(value: str) -> list[str]:
    return [word.lower() for word in WORD_RE.findall(unicodedata.normalize("NFC", value))]


def count_words(value: str) -> int:
    return len(tokenize(value))


def split_sentences(value: str) -> list[str]:
    return SENTENCE_RE.findall(value)


def chunk_document(value: str, minimum_words: int = 5) -> list[str]:
    sentences = [
        sentence.strip()
        for sentence in split_sentences(value)
        if sentence != "\n" and count_words(sentence) >= minimum_words
    ]
    chunks: list[str] = []
    seen: set[str] = set()

    for sentence in sentences:
        key = normalize_text(sentence)
        if key and key not in seen:
            chunks.append(sentence)
            seen.add(key)

    for index in range(len(sentences) - 1):
        pair = f"{sentences[index]} {sentences[index + 1]}"
        key = normalize_text(pair)
        if key and key not in seen:
            chunks.append(pair)
            seen.add(key)

    return chunks


def search_terms(value: str, maximum: int = 12) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in tokenize(value):
        if len(token) < 3 or token in VIETNAMESE_STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    terms.sort(key=lambda token: (-len(token), token))
    return terms[:maximum]


def similarity(left: str, right: str) -> float:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    shared = len(left_set & right_set)
    union = len(left_set | right_set)
    jaccard = shared / union if union else 0.0
    containment = shared / min(len(left_set), len(right_set))
    sequence = SequenceMatcher(None, fold_text(left), fold_text(right)).ratio()

    return max(jaccard, containment * 0.92, sequence * 0.94)


def is_bibliography_heading(value: str) -> bool:
    return bool(BIBLIOGRAPHY_RE.match(value.strip()))


def is_quoted(value: str) -> bool:
    text = value.strip()
    return (
        (text.startswith(('"', "'", "“", "‘", "«")) and text.rstrip(".!?").endswith(('"', "'", "”", "’", "»")))
        or (text.count('"') >= 2)
        or (text.count("“") >= 1 and text.count("”") >= 1)
    )


def has_citation(value: str) -> bool:
    return bool(CITATION_RE.search(value))


def fts_query(terms: Iterable[str]) -> str:
    safe_terms = [term.replace('"', '""') for term in terms if term]
    return " OR ".join(f'"{term}"' for term in safe_terms)


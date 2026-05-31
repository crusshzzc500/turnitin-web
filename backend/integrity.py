from __future__ import annotations

import re
import unicodedata
from collections import Counter

ZERO_WIDTH = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u2060": "word joiner",
    "\ufeff": "zero-width no-break space",
}

CONFUSABLES = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "і": "i",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Χ": "X",
}

WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _script(char: str) -> str:
    name = unicodedata.name(char, "")
    if "CYRILLIC" in name:
        return "Cyrillic"
    if "GREEK" in name:
        return "Greek"
    if "LATIN" in name:
        return "Latin"
    return "Other"


def scan_text(text: str) -> list[dict]:
    flags: list[dict] = []
    zero_width = Counter(char for char in text if char in ZERO_WIDTH)
    if zero_width:
        flags.append(
            {
                "kind": "zero_width_characters",
                "severity": "high",
                "count": sum(zero_width.values()),
                "message": "Phát hiện ký tự vô hình có thể làm sai lệch việc đối chiếu.",
                "details": [ZERO_WIDTH[char] for char in zero_width],
            }
        )

    suspicious_words: list[str] = []
    for word in WORD_RE.findall(text):
        scripts = {_script(char) for char in word}
        if "Latin" in scripts and ({"Cyrillic", "Greek"} & scripts):
            suspicious_words.append(word)
        elif any(char in CONFUSABLES for char in word):
            suspicious_words.append(word)

    if suspicious_words:
        flags.append(
            {
                "kind": "mixed_alphabet_characters",
                "severity": "high",
                "count": len(suspicious_words),
                "message": "Phát hiện từ có ký tự giống hình từ bảng chữ cái khác.",
                "details": suspicious_words[:12],
            }
        )

    long_space_runs = re.findall(r"[ \t]{8,}", text)
    if long_space_runs:
        flags.append(
            {
                "kind": "unusual_spacing",
                "severity": "medium",
                "count": len(long_space_runs),
                "message": "Phát hiện khoảng trắng bất thường cần rà soát.",
                "details": [],
            }
        )

    return flags


from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _find_tesseract() -> Path | None:
    configured = os.getenv("MINH_CHUNG_TESSERACT_PATH")
    candidates = [
        configured,
        shutil.which("tesseract"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def ocr_status() -> dict[str, Any]:
    tesseract = _find_tesseract()
    try:
        import pdf2image  # noqa: F401

        renderer_available = True
    except ImportError:
        renderer_available = False

    if not tesseract:
        reason = "Chưa tìm thấy Tesseract OCR trên máy chủ."
    elif not renderer_available:
        reason = "Chưa cài thư viện pdf2image để chuyển trang PDF thành ảnh."
    else:
        reason = None
    return {
        "available": bool(tesseract and renderer_available),
        "engine": "tesseract" if tesseract else None,
        "pdfRenderer": "pdf2image" if renderer_available else None,
        "languages": os.getenv("MINH_CHUNG_OCR_LANGUAGES", "vie+eng"),
        "reason": reason,
    }


def extract_pdf_text_with_ocr(content: bytes) -> dict[str, Any]:
    status = ocr_status()
    metadata = {"attempted": True, **status}
    if not status["available"]:
        return {"text": "", "metadata": metadata}

    from pdf2image import convert_from_bytes

    tesseract = _find_tesseract()
    if not tesseract:  # pragma: no cover - guarded by ocr_status
        return {"text": "", "metadata": metadata}

    try:
        images = convert_from_bytes(content)
    except Exception as error:
        metadata.update({"available": False, "reason": f"Không thể dựng ảnh từ PDF: {error}"})
        return {"text": "", "metadata": metadata}

    pages: list[str] = []
    for image in images:
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        completed = subprocess.run(
            [str(tesseract), "stdin", "stdout", "-l", str(status["languages"]), "--psm", "6"],
            input=stream.getvalue(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
        if completed.returncode:
            details = completed.stderr.decode("utf-8", errors="replace").strip()
            metadata.update({"available": False, "reason": f"Tesseract OCR không xử lý được PDF: {details}"})
            return {"text": "", "metadata": metadata}
        pages.append(completed.stdout.decode("utf-8", errors="replace"))

    metadata.update({"pages": len(images), "extractedWords": len(" ".join(pages).split())})
    return {"text": "\n\n".join(pages), "metadata": metadata}

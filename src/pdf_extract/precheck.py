from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .config import (
    TEXT_LAYER_MIN_CHARS,
    TEXT_LAYER_MIN_CHARS_PER_PAGE,
    TEXT_LAYER_MIN_WORDS,
    TEXT_LAYER_MIN_WORDS_PER_PAGE,
)
from .errors import UnsupportedInputError


@dataclass(slots=True)
class PrecheckResult:
    page_count: int
    total_words: int
    total_chars: int


def validate_supported_pdf(
    pdf_path: str | Path,
    *,
    min_words: int = TEXT_LAYER_MIN_WORDS,
    min_chars: int = TEXT_LAYER_MIN_CHARS,
    min_words_per_page: float = TEXT_LAYER_MIN_WORDS_PER_PAGE,
    min_chars_per_page: float = TEXT_LAYER_MIN_CHARS_PER_PAGE,
) -> PrecheckResult:
    document = pymupdf.open(str(pdf_path))
    try:
        total_words = 0
        total_chars = 0
        for page in document:
            text = page.get_text("text") or ""
            words = page.get_text("words") or []
            total_chars += len(text.strip())
            total_words += len(words)

        result = PrecheckResult(page_count=document.page_count, total_words=total_words, total_chars=total_chars)
        if result.page_count <= 0:
            raise UnsupportedInputError(
                "当前版本仅支持数字原生或具备文本层的 PDF，不支持 OCR 场景。"
            )

        avg_words = result.total_words / result.page_count
        avg_chars = result.total_chars / result.page_count
        lacks_total_text = result.total_words < min_words and result.total_chars < min_chars
        lacks_average_text = avg_words < min_words_per_page and avg_chars < min_chars_per_page
        if lacks_total_text or lacks_average_text:
            raise UnsupportedInputError(
                "当前版本仅支持数字原生或具备文本层的 PDF，不支持 OCR 场景。"
            )
        return result
    finally:
        document.close()

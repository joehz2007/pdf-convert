from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm

from .config import DEFAULT_TABLE_STRATEGY
from .errors import EmptyExtractionError

TABLE_SEPARATOR_RE = re.compile(r"\|\s*---")


def extract_markdown_chunks(
    pdf_path: str | Path,
    *,
    table_strategy: str = DEFAULT_TABLE_STRATEGY,
    pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    document = pymupdf.open(str(pdf_path))
    try:
        chunks = _to_markdown(document, table_strategy=table_strategy, pages=pages)
        fallback_pages = detect_table_retry_pages(document, chunks)
        for page_index in fallback_pages:
            retry_chunks = _to_markdown(document, table_strategy="lines", pages=[page_index])
            if retry_chunks:
                retry_chunk = retry_chunks[0]
                retry_chunk["table_strategy_used"] = "lines"
                retry_chunk["table_fallback_used"] = True
                retry_chunk["table_retry_pages"] = [page_index + 1]
                chunks[page_index] = retry_chunk
        for chunk in chunks:
            chunk.setdefault("table_strategy_used", table_strategy)
            chunk.setdefault("table_fallback_used", False)
            chunk.setdefault("table_retry_pages", [])
    finally:
        document.close()

    if not isinstance(chunks, list) or not chunks:
        raise EmptyExtractionError(f"No Markdown chunks were produced for: {pdf_path}")
    return chunks


def _to_markdown(document: pymupdf.Document, *, table_strategy: str, pages: list[int] | None) -> list[dict[str, Any]]:
    chunks = pymupdf4llm.to_markdown(
        document,
        pages=pages,
        page_chunks=True,
        write_images=False,
        table_strategy=table_strategy,
    )
    if not isinstance(chunks, list) or not chunks:
        raise EmptyExtractionError("PyMuPDF4LLM returned no page chunks.")
    return chunks


def detect_table_retry_pages(document: pymupdf.Document, chunks: list[dict[str, Any]]) -> list[int]:
    retry_pages: list[int] = []
    for page_index, chunk in enumerate(chunks):
        page = document[page_index]
        finder = page.find_tables()
        has_tables = bool(getattr(finder, "tables", []))
        if has_tables and not chunk_has_markdown_table(chunk):
            retry_pages.append(page_index)
    return retry_pages


def chunk_has_markdown_table(chunk: dict[str, Any]) -> bool:
    if chunk.get("tables"):
        return True
    text = str(chunk.get("text", ""))
    return bool(TABLE_SEPARATOR_RE.search(text))

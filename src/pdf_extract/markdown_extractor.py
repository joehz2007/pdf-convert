from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pymupdf
import pymupdf4llm

from .config import DEFAULT_TABLE_STRATEGY
from .errors import EmptyExtractionError

LOGGER = logging.getLogger("pdf_extract.markdown_extractor")

TABLE_SEPARATOR_RE = re.compile(r"\|\s*---")
TABLE_LINE_RE = re.compile(r"^\|.*\|\s*$")
BROKEN_WORD_BREAK_RE = re.compile(r"[A-Za-z]{2,}<br>[A-Za-z]{1,}")
NESTED_TABLE_SIGNAL_RE = re.compile(r"Objects of|Supported Types:|Limits?:|description\s*\(", re.IGNORECASE)
TABLE_FALLBACK_PLACEHOLDER = "[复杂表格 Markdown 已回退，请以 content.json / fallback_html 为准]"

# Cross-page table detection thresholds
CROSS_PAGE_BOTTOM_RATIO = 0.88
CROSS_PAGE_TOP_RATIO = 0.12
CROSS_PAGE_WIDTH_TOLERANCE = 0.15
SPURIOUS_TABLE_MIN_AREA = 3000
SPURIOUS_TABLE_MAX_HEADER_COLS = 12


def extract_markdown_chunks(
    pdf_path: str | Path,
    *,
    table_strategy: str = DEFAULT_TABLE_STRATEGY,
    pages: list[int] | None = None,
) -> list[dict[str, Any]]:
    document = pymupdf.open(str(pdf_path))
    try:
        page_numbers = resolve_page_numbers(document, pages)
        chunks = _to_markdown(document, table_strategy=table_strategy, pages=pages)
        annotate_table_snapshots(document, chunks, page_numbers)
        postprocess_cross_page_tables(document, chunks, page_numbers)
        index_by_doc_page = {doc_page_index: offset for offset, doc_page_index in enumerate(page_numbers)}
        fallback_pages = detect_table_retry_pages(chunks, page_numbers)
        for doc_page_index in fallback_pages:
            retry_chunks = _to_markdown(document, table_strategy="lines", pages=[doc_page_index])
            annotate_table_snapshots(document, retry_chunks, [doc_page_index])
            if retry_chunks:
                retry_chunk = retry_chunks[0]
                retry_chunk["table_strategy_used"] = "lines"
                retry_chunk["table_fallback_used"] = True
                retry_chunk["table_retry_pages"] = [doc_page_index + 1]
                chunks[index_by_doc_page[doc_page_index]] = retry_chunk
        for chunk in chunks:
            chunk.setdefault("table_strategy_used", table_strategy)
            chunk.setdefault("table_fallback_used", False)
            chunk.setdefault("table_retry_pages", [])
            sanitize_broken_table_markdown(chunk)
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
        use_ocr=False,
        table_strategy=table_strategy,
    )
    if not isinstance(chunks, list) or not chunks:
        raise EmptyExtractionError("PyMuPDF4LLM returned no page chunks.")
    return chunks


def resolve_page_numbers(document: pymupdf.Document, pages: list[int] | None) -> list[int]:
    if pages is not None:
        return list(pages)
    return list(range(document.page_count))


def annotate_table_snapshots(document: pymupdf.Document, chunks: list[dict[str, Any]], page_numbers: list[int]) -> None:
    for offset, chunk in enumerate(chunks):
        doc_page_index = page_numbers[offset]
        table_snapshots = collect_table_snapshots(document[doc_page_index])
        chunk["table_snapshots"] = table_snapshots
        metadata = chunk.setdefault("metadata", {})
        metadata["table_count_hint"] = len(table_snapshots)


def collect_table_snapshots(page: pymupdf.Page) -> list[dict[str, Any]]:
    finder = page.find_tables()
    snapshots: list[dict[str, Any]] = []
    for table in getattr(finder, "tables", []):
        snapshots.append(
            {
                "bbox": [round(float(value), 3) for value in table.bbox],
                "headers": list(getattr(getattr(table, "header", None), "names", []) or []),
                "rows": table.extract() or [],
                "markdown": str(table.to_markdown() or "").strip(),
            }
        )
    return snapshots


def detect_table_retry_pages(chunks: list[dict[str, Any]], page_numbers: list[int]) -> list[int]:
    retry_pages: list[int] = []
    for offset, chunk in enumerate(chunks):
        has_tables = bool(chunk.get("table_snapshots"))
        if has_tables and not chunk_has_markdown_table(chunk):
            retry_pages.append(page_numbers[offset])
    return retry_pages


def chunk_has_markdown_table(chunk: dict[str, Any]) -> bool:
    if chunk.get("tables"):
        return True
    text = str(chunk.get("text", ""))
    return bool(TABLE_SEPARATOR_RE.search(text))


def sanitize_broken_table_markdown(chunk: dict[str, Any]) -> None:
    text = str(chunk.get("text", "") or "")
    if not text or not chunk_has_markdown_table(chunk):
        chunk.setdefault("suppressed_table_markdown", 0)
        return

    suppressed_count = 0
    lines = text.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if is_table_line(line):
            table_lines: list[str] = []
            while index < len(lines) and is_table_line(lines[index]):
                table_lines.append(lines[index])
                index += 1
            if is_suspicious_table_block(table_lines):
                suppressed_count += 1
                if output and output[-1] != "":
                    output.append("")
                output.append(TABLE_FALLBACK_PLACEHOLDER)
                if index < len(lines) and lines[index:index + 1] != [""]:
                    output.append("")
                continue
            output.extend(table_lines)
            continue

        output.append(line)
        index += 1

    chunk["text"] = "\n".join(output).strip()
    chunk["suppressed_table_markdown"] = suppressed_count


def is_table_line(line: str) -> bool:
    return bool(TABLE_LINE_RE.match(line.strip()))


def is_suspicious_table_block(table_lines: list[str]) -> bool:
    if len(table_lines) < 2 or not any(TABLE_SEPARATOR_RE.search(line) for line in table_lines):
        return False

    block_text = "\n".join(table_lines)
    broken_word_count = len(BROKEN_WORD_BREAK_RE.findall(block_text))
    br_count = block_text.count("<br>")
    header_line = table_lines[0] if table_lines else ""
    if BROKEN_WORD_BREAK_RE.search(header_line):
        return True
    if NESTED_TABLE_SIGNAL_RE.search(block_text) and br_count >= 2:
        return True
    if broken_word_count == 0:
        return False

    fragment_like_cells = sum(1 for line in table_lines if "<br>" in line and average_fragment_length(line) < 8)
    return broken_word_count >= 2 or br_count >= 6 or fragment_like_cells >= 2


def average_fragment_length(line: str) -> float:
    fragments = [fragment.strip(" *`)_(") for fragment in line.split("<br>") if fragment.strip()]
    if not fragments:
        return 0.0
    return sum(len(fragment) for fragment in fragments) / len(fragments)


# ---------------------------------------------------------------------------
# Cross-page table merging & spurious table filtering
# ---------------------------------------------------------------------------


def postprocess_cross_page_tables(
    document: pymupdf.Document,
    chunks: list[dict[str, Any]],
    page_numbers: list[int],
) -> None:
    """Filter spurious tables, then detect and merge cross-page table continuations.

    Runs iteratively because merging can expose new chains (e.g. a page whose
    first table was consumed by one chain may still have a *last* table that
    starts a second chain to the following page).
    """
    _filter_spurious_snapshots(chunks, document, page_numbers)
    while True:
        chains = _detect_continuation_chains(document, chunks, page_numbers)
        if not chains:
            break
        for chain in chains:
            _merge_table_chain(chunks, chain)


def _filter_spurious_snapshots(
    chunks: list[dict[str, Any]],
    document: pymupdf.Document,
    page_numbers: list[int],
) -> None:
    """Remove tiny noise tables (punctuation artifacts etc.) from each chunk."""
    for offset, chunk in enumerate(chunks):
        snapshots = chunk.get("table_snapshots", [])
        if not snapshots:
            continue
        page = document[page_numbers[offset]]
        page_height = float(page.rect.height)
        page_width = float(page.rect.width)
        filtered = [s for s in snapshots if not _is_spurious_table(s, page_width, page_height)]
        if len(filtered) < len(snapshots):
            removed = len(snapshots) - len(filtered)
            LOGGER.debug("Filtered %d spurious table(s) on page %d", removed, page_numbers[offset] + 1)
            chunk["table_snapshots"] = filtered
            chunk.setdefault("metadata", {})["table_count_hint"] = len(filtered)


def _is_spurious_table(snapshot: dict[str, Any], page_width: float, page_height: float) -> bool:
    bbox = snapshot.get("bbox", [0, 0, 0, 0])
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    area = width * height

    if area < SPURIOUS_TABLE_MIN_AREA:
        headers = snapshot.get("headers", [])
        rows = snapshot.get("rows", [])
        all_text = " ".join(str(h or "") for h in headers) + " ".join(str(c or "") for r in rows for c in r)
        if sum(1 for c in all_text if c.isalnum()) < 10:
            return True

    headers = snapshot.get("headers", [])
    if len(headers) > SPURIOUS_TABLE_MAX_HEADER_COLS:
        return True

    if headers and all(len(str(h or "").strip()) <= 1 for h in headers):
        rows = snapshot.get("rows", [])
        has_real_data = any(
            any(len(str(c or "").strip()) > 2 for c in row) for row in rows
        )
        if not has_real_data:
            return True

    return False


def _detect_continuation_chains(
    document: pymupdf.Document,
    chunks: list[dict[str, Any]],
    page_numbers: list[int],
) -> list[list[tuple[int, int]]]:
    """Find chains of cross-page table continuations.

    Returns a list of chains.  Each chain is a list of
    ``(chunk_offset, table_snapshot_index)`` tuples – the first element is
    the *base* table, subsequent elements are continuations.
    """
    chains: list[list[tuple[int, int]]] = []
    consumed: set[int] = set()

    for i in range(len(chunks) - 1):
        if i in consumed:
            continue
        prev_snapshots = chunks[i].get("table_snapshots", [])
        if not prev_snapshots:
            continue

        prev_page = document[page_numbers[i]]
        prev_height = float(prev_page.rect.height)
        prev_last = prev_snapshots[-1]
        prev_bbox = prev_last.get("bbox", [0, 0, 0, 0])

        if prev_bbox[3] < prev_height * CROSS_PAGE_BOTTOM_RATIO:
            continue

        chain: list[tuple[int, int]] = [(i, len(prev_snapshots) - 1)]
        current_last_snapshot = prev_last
        j = i + 1
        while j < len(chunks):
            next_snapshots = chunks[j].get("table_snapshots", [])
            if not next_snapshots:
                break
            next_page = document[page_numbers[j]]
            next_height = float(next_page.rect.height)
            next_first = next_snapshots[0]

            if not _is_continuation(current_last_snapshot, next_first, prev_height, next_height):
                break

            chain.append((j, 0))
            consumed.add(j)

            next_bbox = next_first.get("bbox", [0, 0, 0, 0])
            if next_bbox[3] < next_height * CROSS_PAGE_BOTTOM_RATIO:
                break
            current_last_snapshot = next_first
            prev_height = next_height
            j += 1

        if len(chain) > 1:
            LOGGER.info(
                "Detected cross-page table chain spanning %d pages (offsets %s)",
                len(chain),
                [c[0] for c in chain],
            )
            chains.append(chain)

    return chains


def _is_continuation(
    prev_table: dict[str, Any],
    curr_table: dict[str, Any],
    prev_page_height: float,
    curr_page_height: float,
) -> bool:
    """Heuristic: *curr_table* is a continuation of *prev_table* across a page break."""
    curr_bbox = curr_table.get("bbox", [0, 0, 0, 0])
    if curr_bbox[1] > curr_page_height * CROSS_PAGE_TOP_RATIO:
        return False

    prev_bbox = prev_table.get("bbox", [0, 0, 0, 0])
    prev_width = prev_bbox[2] - prev_bbox[0]
    curr_width = curr_bbox[2] - curr_bbox[0]
    if prev_width <= 0 or curr_width <= 0:
        return False
    if min(prev_width, curr_width) / max(prev_width, curr_width) < (1 - CROSS_PAGE_WIDTH_TOLERANCE):
        return False

    prev_rows = prev_table.get("rows", [])
    curr_rows = curr_table.get("rows", [])
    if prev_rows and curr_rows:
        if len(prev_rows[0]) != len(curr_rows[0]):
            return False

    return True


def _merge_table_chain(
    chunks: list[dict[str, Any]],
    chain: list[tuple[int, int]],
) -> None:
    """Merge a chain of continuation tables into the base (first) table snapshot."""
    if len(chain) < 2:
        return

    base_offset, base_idx = chain[0]
    base_snapshot = chunks[base_offset]["table_snapshots"][base_idx]
    merged_rows: list[list] = list(base_snapshot.get("rows", []))

    for cont_offset, cont_idx in chain[1:]:
        cont_snapshots = chunks[cont_offset].get("table_snapshots", [])
        if cont_idx >= len(cont_snapshots):
            continue
        cont_snapshot = cont_snapshots[cont_idx]
        cont_rows = list(cont_snapshot.get("rows", []))
        if not cont_rows:
            cont_snapshots.pop(cont_idx)
            continue

        first_row = cont_rows[0]
        if _is_overflow_row(first_row):
            _merge_overflow_into_last_row(merged_rows, first_row)
            data_rows = cont_rows[1:]
        else:
            data_rows = cont_rows

        merged_rows.extend(data_rows)

        cont_snapshots.pop(cont_idx)
        chunks[cont_offset].setdefault("metadata", {})["table_count_hint"] = len(cont_snapshots)

    base_snapshot["rows"] = merged_rows
    base_snapshot["cross_page"] = True
    base_snapshot["cross_page_count"] = len(chain)
    base_snapshot["markdown"] = ""


def _is_overflow_row(row: list) -> bool:
    """A row is overflow when most cells are empty and the non-empty cell is NOT in the first column."""
    if not row:
        return False
    non_empty = [(i, str(cell).strip()) for i, cell in enumerate(row) if cell and str(cell).strip()]
    if len(non_empty) == 0:
        return True
    if len(non_empty) == 1:
        idx, _text = non_empty[0]
        return idx > 0
    return False


def _merge_overflow_into_last_row(rows: list[list], overflow_row: list) -> None:
    """Append overflow cell content to the matching cell of the last accumulated row."""
    if not rows:
        return
    last_row = rows[-1]
    for i, cell in enumerate(overflow_row):
        cell_text = str(cell).strip() if cell else ""
        if not cell_text or i >= len(last_row):
            continue
        existing = str(last_row[i]).strip() if last_row[i] else ""
        last_row[i] = f"{existing}\n{cell_text}" if existing else cell_text

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pymupdf

from .assets_exporter import export_page_images, export_table_clip
from .config import IMAGE_CAPTION_LEFT_TOLERANCE_RATIO, IMAGE_CAPTION_VERTICAL_GAP_RATIO
from .contracts import BlockNode, ContentResult, ImageNode, PageContent, SliceTask, TableNode
from .errors import EmptyExtractionError, PageMappingError

NUMBERED_LIST_RE = re.compile(r"^\d+[.)]\s")
SECTION_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+){0,5}|[A-Za-z]\d+(?:\.\d+){0,5}|第[一二三四五六七八九十百千万]+[章节篇]|附录[A-Za-z0-9一二三四五六七八九十]*)[\s.:：、)）\-].+"
)
HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)")
HEADING_ALPHA_NUM_RE = re.compile(r"^[A-Za-z](\d+(?:\.\d+)*)")
HEADING_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千万]+[章篇]")
HEADING_SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千万]+节")
HEADING_APPENDIX_RE = re.compile(r"^附录")
CODE_KEYWORD_RE = re.compile(r"^(def|class|for|if|while|return|import|from|try|except|with)\b", re.IGNORECASE)
CODE_MARKER_RE = re.compile(r"[:=(){}\[\].,]|->|=>")
NESTED_SECTION_RE = re.compile(
    r"(Objects of|Params of|Fields of|Items of|List\s*\(|description\s*\(|Supported Types:?|Limits?:)",
    re.IGNORECASE,
)
WORDISH_CHAR_RE = re.compile(r"[A-Za-z0-9<>/]")
BULLET_OR_NUMBERED_LINE_RE = re.compile(r"^(?:[-*•]|\d+[.)]|\d+\s*-\s*|[A-Z]\d+\s*-\s)\s*")
INLINE_CONNECTORS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with"}
# Common English words that should NOT be PascalCase-joined.  When BOTH tokens
# are in this set the join is almost certainly a false positive
# (e.g. "Request" + "Example" → NOT an identifier).
_PASCAL_COMMON_WORDS = frozenset({
    # articles / prepositions / conjunctions (overlap with INLINE_CONNECTORS)
    "a", "an", "the", "this", "that", "these", "those",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "not", "no", "or", "and", "but", "if", "of", "at", "by",
    "for", "in", "on", "to", "with", "from", "as",
    # common nouns / adjectives frequent in API docs & table headers
    "request", "response", "account", "example", "parameters", "parameter",
    "statement", "description", "information", "details", "detail",
    "message", "method", "header", "headers", "body", "field", "fields",
    "value", "values", "name", "type", "types", "code", "status",
    "result", "results", "error", "errors", "data", "list", "object",
    "number", "string", "query", "path", "table", "format",
    "required", "optional", "default", "maximum", "minimum",
    "length", "limit", "size", "total", "count", "amount",
    "order", "payment", "transaction", "currency", "address",
    "create", "update", "delete", "get", "set", "add", "remove",
    "input", "output", "source", "target", "key", "id",
})
CLAUSE_BREAK_RE = re.compile(
    r"^(?:Format|For example|Example|Allowed:?|Character limit:?|Mandatory|Optional|Unsupported\b|Supported Types:?|MSB Limits:?|SaintPay Limits:?|Limit(?:s)?:|Limit \d|ISO\b)",
    re.IGNORECASE,
)
SECTION_TITLE_SUFFIX_RE = re.compile(
    r"\b(?:Character limit:|Allowed:|Format\b|Supported Types:|MSB Limits:|SaintPay Limits:|Mandatory\b|Optional\b|For example\b|Unsupported\b|Limit(?:s)?:)",
    re.IGNORECASE,
)
STRUCTURED_SECTION_TITLE_RE = re.compile(r"\((?:Objects|Params|Fields|Items) of .*\)", re.IGNORECASE)
TYPE_TOKEN_RE = re.compile(
    r"^(?:string|int|integer|long|number|decimal|boolean|bool|object|array|list(?:<.*>)?|multipartfile|file|date|datetime|timestamp)(?:\b|[<\s])",
    re.IGNORECASE,
)
PARAMETER_TABLE_HEADERS = ["Field", "Required", "Type", "Description"]


def build_content_result(task: SliceTask, page_chunks: list[dict], *, slice_dir: Path | None = None) -> ContentResult:
    if len(page_chunks) != task.actual_pages:
        raise PageMappingError(
            f"Slice '{task.slice_file}' expected {task.actual_pages} page chunks but got {len(page_chunks)}."
        )

    assets_dir = slice_dir / "assets" if slice_dir is not None else None
    document = pymupdf.open(str(task.source_path))
    try:
        source_pages: list[PageContent] = []
        warnings: list[str] = []
        assets: list[dict] = []
        char_count = 0
        table_count = 0
        image_count = 0
        block_count = 0

        for expected_slice_page, chunk in enumerate(page_chunks, start=1):
            metadata = chunk.get("metadata", {})
            chunk_page = int(metadata.get("page", expected_slice_page))
            if chunk_page != expected_slice_page:
                raise PageMappingError(
                    f"Slice '{task.slice_file}' returned page chunk {chunk_page}, expected {expected_slice_page}."
                )

            source_page = task.start_page + expected_slice_page - 1
            markdown = str(chunk.get("text", "")).strip()
            is_overlap = source_page in task.overlap_pages

            page = document[expected_slice_page - 1]
            blocks = extract_text_blocks(
                page,
                source_page=source_page,
                display_title=task.display_title,
                is_overlap=is_overlap,
                first_page=(expected_slice_page == 1),
            )
            suppressed_table_markdown = int(chunk.get("suppressed_table_markdown", 0) or 0)
            if suppressed_table_markdown > 0:
                warnings.append(f"suppressed_broken_table_markdown:{source_page}:{suppressed_table_markdown}")

            tables = extract_tables(
                page,
                chunk,
                source_page=source_page,
                blocks=blocks,
                assets_dir=assets_dir,
                warnings=warnings,
            )
            images = export_page_images(document, page, assets_dir, source_page=source_page, warnings=warnings) if assets_dir else []
            bind_captions(
                blocks,
                images,
                page_width=float(page.rect.width),
                page_height=float(page.rect.height),
                warnings=warnings,
            )
            warnings.extend(
                warning
                for warning in collect_page_review_flags(
                    source_page=source_page,
                    markdown=markdown,
                    blocks=blocks,
                    tables=tables,
                    images=images,
                    is_overlap=is_overlap,
                )
                if warning not in warnings
            )

            assets.extend({"asset_path": image.asset_path, "source_page": source_page, "type": "image"} for image in images)
            assets.extend(
                {"asset_path": table.fallback_image, "source_page": source_page, "type": "table_fallback_image"}
                for table in tables
                if table.fallback_image
            )
            char_count += len(markdown)
            table_count += len(tables)
            image_count += len(images)
            block_count += len(blocks)
            source_pages.append(
                PageContent(
                    slice_page=expected_slice_page,
                    source_page=source_page,
                    is_overlap=is_overlap,
                    markdown=markdown,
                    blocks=blocks,
                    tables=tables,
                    images=images,
                )
            )
    finally:
        document.close()

    if char_count == 0 and table_count == 0 and image_count == 0 and block_count == 0:
        raise EmptyExtractionError(f"Slice '{task.slice_file}' produced empty Markdown content.")

    return ContentResult(
        slice_file=task.slice_file,
        display_title=task.display_title,
        start_page=task.start_page,
        end_page=task.end_page,
        source_pages=source_pages,
        assets=assets,
        stats={
            "char_count": char_count,
            "table_count": table_count,
            "image_count": image_count,
        },
        warnings=warnings,
        manual_review_required=task.manual_review_required or bool(warnings),
    )

def collect_page_review_flags(
    *,
    source_page: int,
    markdown: str,
    blocks: list[BlockNode],
    tables: list[TableNode],
    images: list[ImageNode],
    is_overlap: bool,
) -> list[str]:
    warnings: list[str] = []
    normalized_markdown = normalize_text(markdown)
    body_blocks = [block for block in blocks if block.type not in {"header", "footer"}]

    if not normalized_markdown:
        warnings.append(f"empty_markdown_page:{source_page}")
    if normalized_markdown and not body_blocks and not tables and not images:
        warnings.append(f"no_blocks_page:{source_page}")
    if not normalized_markdown and (body_blocks or tables or images):
        warnings.append(f"page_content_mismatch:{source_page}")

    structured_chars = sum(len(normalize_text(block.text)) for block in body_blocks)
    if normalized_markdown and structured_chars >= 80 and len(normalized_markdown) < max(20, int(structured_chars * 0.2)):
        warnings.append(f"page_content_mismatch:{source_page}")

    fallback_tables = [table for table in tables if table.fallback_html or table.fallback_image]
    if fallback_tables:
        warnings.append(f"table_render_fallback:{source_page}:{len(fallback_tables)}")

    if is_overlap and any(not block.dedupe_key for block in body_blocks):
        warnings.append(f"overlap_missing_dedupe_key:{source_page}")

    return warnings


def extract_text_blocks(
    page: pymupdf.Page,
    *,
    source_page: int,
    display_title: str,
    is_overlap: bool,
    first_page: bool,
) -> list[BlockNode]:
    page_dict = page.get_text("dict", sort=True)
    text_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]
    max_font_size = max((_max_font_size(block) for block in text_blocks), default=0.0)
    page_height = float(page.rect.height)

    results: list[BlockNode] = []
    for reading_order, block in enumerate(text_blocks, start=1):
        text = extract_block_text(block)
        if not text:
            continue
        bbox = round_bbox(block.get("bbox", (0, 0, 0, 0)))
        font_size = _max_font_size(block)
        block_type = classify_block(
            text,
            block,
            display_title=display_title,
            first_page=first_page,
            max_font_size=max_font_size,
            page_height=page_height,
            reading_order=reading_order,
        )
        heading_level = None
        if block_type == "heading":
            heading_level = detect_heading_level(text, font_size=font_size, max_font_size=max_font_size)
        bbox_hash = build_bbox_hash(bbox)
        results.append(
            BlockNode(
                type=block_type,
                text=text,
                source_page=source_page,
                bbox=bbox,
                reading_order=reading_order,
                is_overlap=is_overlap,
                dedupe_key=build_dedupe_key(source_page, text, bbox_hash),
                heading_level=heading_level,
            )
        )
    return results


def extract_tables(
    page: pymupdf.Page,
    chunk: dict,
    *,
    source_page: int,
    blocks: list[BlockNode],
    assets_dir: Path | None,
    warnings: list[str],
) -> list[TableNode]:
    table_snapshots = list(chunk.get("table_snapshots", []))
    tables: list[TableNode] = []
    retry_pages = list(chunk.get("table_retry_pages", []))
    strategy_used = str(chunk.get("table_strategy_used", "lines_strict"))
    fallback_used = bool(chunk.get("table_fallback_used", False))
    for index, snapshot in enumerate(table_snapshots, start=1):
        bbox = round_bbox(snapshot.get("bbox", (0, 0, 0, 0)))
        rows = snapshot.get("rows") or []
        headers = list(snapshot.get("headers") or [])
        markdown = str(snapshot.get("markdown") or "").strip()
        complex_table = is_complex_table(headers, rows, markdown)
        if complex_table:
            warnings.append(f"complex_table:{source_page}:{index}")
        tables.extend(
            build_table_nodes(
                page,
                source_page=source_page,
                snapshot_index=index,
                bbox=bbox,
                headers=headers,
                rows=rows,
                markdown=markdown,
                strategy_used=strategy_used,
                fallback_used=fallback_used,
                retry_pages=retry_pages,
                complex_table=complex_table,
                blocks=blocks,
                assets_dir=assets_dir,
            )
        )
    return tables


def build_table_nodes(
    page: pymupdf.Page,
    *,
    source_page: int,
    snapshot_index: int,
    bbox: list[float],
    headers: list[str],
    rows: list[list],
    markdown: str,
    strategy_used: str,
    fallback_used: bool,
    retry_pages: list[int],
    complex_table: bool,
    blocks: list[BlockNode],
    assets_dir: Path | None,
) -> list[TableNode]:
    table_id = build_table_id(source_page, snapshot_index)
    headers, rows = normalize_table_structure(headers, rows, blocks)
    display_headers = normalize_table_headers(headers, rows)
    parent_rows, child_sections = split_nested_table_sections(rows)
    if complex_table and child_sections:
        child_ids = [f"{table_id}-c{child_index:02d}" for child_index in range(1, len(child_sections) + 1)]
        cleaned_parent_rows = clean_table_rows(display_headers, parent_rows)
        parent_fallback_html = render_table_html(
            headers=display_headers,
            rows=cleaned_parent_rows,
            table_id=table_id,
            table_role="parent",
            child_table_ids=child_ids,
        )
        parent_fallback_image = None
        if parent_fallback_html is None and assets_dir is not None:
            parent_fallback_image = export_table_clip(page, bbox, assets_dir, source_page=source_page, table_index=snapshot_index)

        nodes = [
            TableNode(
                type="table",
                source_page=source_page,
                bbox=bbox,
                table_strategy_used=strategy_used,
                table_fallback_used=fallback_used,
                table_retry_pages=retry_pages,
                headers=display_headers,
                rows=cleaned_parent_rows,
                markdown=None,
                fallback_html=parent_fallback_html,
                fallback_image=parent_fallback_image,
                table_id=table_id,
                table_role="parent",
                child_table_ids=child_ids,
            )
        ]
        # Extract first-column field names from parent for section title repair
        parent_field_names = [
            str(row[0]).strip() for row in cleaned_parent_rows
            if row and str(row[0]).strip()
        ]
        for child_index, section in enumerate(child_sections, start=1):
            child_id = f"{table_id}-c{child_index:02d}"
            cleaned_child_rows = clean_table_rows(display_headers, list(section["rows"]))
            raw_title = normalize_section_title(str(section["title"]))
            repaired_title = _repair_section_title_from_fields(raw_title, parent_field_names)
            child_fallback_html = render_table_html(
                headers=display_headers,
                rows=cleaned_child_rows,
                table_id=child_id,
                table_role="child",
                parent_table_id=table_id,
                section_title=repaired_title,
            )
            child_fallback_image = None
            if child_fallback_html is None and assets_dir is not None:
                child_fallback_image = export_table_clip(page, bbox, assets_dir, source_page=source_page, table_index=snapshot_index)
            nodes.append(
                TableNode(
                    type="table",
                    source_page=source_page,
                    bbox=bbox,
                    table_strategy_used=strategy_used,
                    table_fallback_used=fallback_used,
                    table_retry_pages=retry_pages,
                    headers=display_headers,
                    rows=cleaned_child_rows,
                    markdown=None,
                    fallback_html=child_fallback_html,
                    fallback_image=child_fallback_image,
                    table_id=child_id,
                    parent_table_id=table_id,
                    table_role="child",
                    section_title=repaired_title,
                )
            )
        return nodes

    cleaned_rows = clean_table_rows(display_headers, rows)
    fallback_html = (
        render_table_html(
            headers=display_headers,
            rows=cleaned_rows,
            table_id=table_id,
            table_role="standalone",
        )
        if complex_table
        else None
    )
    fallback_image = None
    if complex_table and fallback_html is None and assets_dir is not None:
        fallback_image = export_table_clip(page, bbox, assets_dir, source_page=source_page, table_index=snapshot_index)

    return [
        TableNode(
            type="table",
            source_page=source_page,
            bbox=bbox,
            table_strategy_used=strategy_used,
            table_fallback_used=fallback_used,
            table_retry_pages=retry_pages,
            headers=display_headers,
            rows=cleaned_rows,
            markdown=markdown,
            fallback_html=fallback_html,
            fallback_image=fallback_image,
            table_id=table_id,
        )
    ]

def split_nested_table_sections(rows: list[list]) -> tuple[list[list], list[dict[str, list[list] | str]]]:
    parent_rows: list[list] = []
    sections: list[dict[str, list[list] | str]] = []
    current_section: dict[str, list[list] | str] | None = None

    for row in rows:
        title = extract_section_title(row)
        if title:
            if current_section is not None and current_section.get("rows"):
                sections.append(current_section)
            current_section = {"title": title, "rows": []}
            continue
        if current_section is None:
            parent_rows.append(row)
        else:
            current_section["rows"].append(row)

    if current_section is not None and current_section.get("rows"):
        sections.append(current_section)

    return parent_rows, sections


def extract_section_title(row: list) -> str | None:
    all_cells = [str(cell or "") for cell in row]
    non_empty = [normalize_text(cell) for cell in all_cells if normalize_text(cell)]
    if not non_empty:
        return None

    total = len(all_cells)
    filled = len(non_empty)
    primary = max(non_empty, key=len)

    # Case 1: spanning section title — all non-empty cells carry the same text
    if len(set(non_empty)) == 1 and filled >= 2 and len(primary) >= 12:
        return primary

    # Case 2: section title in one cell, other cells empty.
    # A proper data row (most cells filled) is never a section title.
    if filled > max(1, total // 2):
        return None

    if NESTED_SECTION_RE.search(primary):
        return primary
    return None


def _repair_section_title_from_fields(title: str, parent_field_names: list[str]) -> str:
    """Fix truncated field names in section titles by matching against parent fields.

    Example: title = "sAccountList Details (...)" with parent field "subAccountList"
    → returns "subAccountList Details (...)".
    Uses longest common suffix matching.  Only replaces when the common suffix
    covers ≥ 60% of the field name AND ≥ 60% of the title word (high confidence).
    """
    if not title or not parent_field_names:
        return title
    m = re.match(r"([A-Za-z][\w]*)", title)
    if not m:
        return title
    title_word = m.group(1)
    title_word_lower = title_word.lower()
    best_field: str | None = None
    best_suffix_len = 0
    for field in parent_field_names:
        field_lower = field.lower()
        if field_lower == title_word_lower:
            return title  # exact match, no repair needed
        # Find longest common suffix between title_word and field
        max_check = min(len(title_word_lower), len(field_lower))
        suffix_len = 0
        for k in range(1, max_check + 1):
            if title_word_lower[-k] == field_lower[-k]:
                suffix_len = k
            else:
                break
        # Title word must be strictly shorter (truncation removes prefix chars)
        if (len(title_word) < len(field)
                and suffix_len >= len(field) * 0.6
                and suffix_len >= len(title_word) * 0.6
                and suffix_len > best_suffix_len):
            best_field = field
            best_suffix_len = suffix_len
    if best_field:
        return best_field + title[len(title_word):]
    return title


def normalize_section_title(value: str) -> str:
    title = normalize_cell_text(value).replace("\n", " ").strip()
    if not title:
        return title
    if STRUCTURED_SECTION_TITLE_RE.search(title):
        return title
    match = SECTION_TITLE_SUFFIX_RE.search(title)
    if match:
        title = title[: match.start()].rstrip(" -:;,.")
    return title.strip()


def render_table_html(
    *,
    headers: list[str],
    rows: list[list],
    table_id: str,
    table_role: str,
    parent_table_id: str | None = None,
    section_title: str | None = None,
    child_table_ids: list[str] | None = None,
) -> str | None:
    if not headers and not rows and not section_title:
        return None

    attrs = [
        ("class", "complex-table-block"),
        ("data-table-id", table_id),
        ("data-table-role", table_role),
    ]
    if parent_table_id:
        attrs.append(("data-parent-table-id", parent_table_id))
    if child_table_ids:
        attrs.append(("data-child-table-ids", ",".join(child_table_ids)))

    attr_text = " ".join(f'{name}="{escape_html_attr(value)}"' for name, value in attrs if value)
    lines = [f"<div {attr_text}>"]
    if section_title:
        lines.append(f"  <p class=\"complex-table-title\"><strong>{escape_html(section_title)}</strong></p>")
    lines.append("  <table>")
    if headers:
        lines.append("    <thead>")
        header_cells = "".join(f"<th>{escape_html(str(header or ''))}</th>" for header in headers)
        lines.append(f"      <tr>{header_cells}</tr>")
        lines.append("    </thead>")
    lines.append("    <tbody>")
    for row in rows:
        cells = "".join(f"<td>{escape_html(str(cell or ''))}</td>" for cell in row)
        lines.append(f"      <tr>{cells}</tr>")
    lines.append("    </tbody>")
    lines.append("  </table>")
    lines.append("</div>")
    return "\n".join(lines)


def normalize_table_headers(headers: list[str], rows: list[list]) -> list[str]:
    cleaned_headers = [normalize_cell_text(str(header or "")) for header in headers]
    if len(cleaned_headers) == 4 and looks_like_semantic_headers(cleaned_headers):
        return PARAMETER_TABLE_HEADERS.copy()
    if looks_like_field_descriptor_row(cleaned_headers):
        return PARAMETER_TABLE_HEADERS.copy()
    if rows:
        first_row = [normalize_cell_text(str(cell or "")) for cell in rows[0]]
        if looks_like_field_descriptor_row(first_row):
            return PARAMETER_TABLE_HEADERS.copy()
    return cleaned_headers


def normalize_table_structure(headers: list[str], rows: list[list], blocks: list[BlockNode]) -> tuple[list[str], list[list]]:
    cleaned_headers = [normalize_cell_text(str(header or "")) for header in headers]
    cleaned_rows = [[normalize_cell_text(str(cell or "")) for cell in row] for row in rows]
    if not cleaned_headers:
        return cleaned_headers, cleaned_rows
    if should_demote_headers_to_first_row(cleaned_headers, cleaned_rows):
        if cleaned_rows and row_matches_headers(cleaned_headers, cleaned_rows[0]):
            return [], cleaned_rows
        return [], [cleaned_headers, *cleaned_rows]
    if should_drop_duplicate_headers(cleaned_headers, blocks):
        return [], cleaned_rows
    return cleaned_headers, cleaned_rows


def should_demote_headers_to_first_row(headers: list[str], rows: list[list[str]]) -> bool:
    if len(headers) < 2 or not rows:
        return False
    if looks_like_semantic_headers(headers) or looks_like_field_descriptor_row(headers):
        return False

    candidate_rows = rows[1:] if rows and row_matches_headers(headers, rows[0]) else rows
    if not candidate_rows:
        return False

    header_label = parse_enumerated_row_label(headers[0])
    first_row_label = parse_enumerated_row_label(candidate_rows[0][0] if candidate_rows[0] else "")
    if header_label is None or first_row_label is None:
        return False
    if header_label[0] != first_row_label[0] or first_row_label[1] != header_label[1] + 1:
        return False

    if len(candidate_rows) >= 2:
        second_row_label = parse_enumerated_row_label(candidate_rows[1][0] if candidate_rows[1] else "")
        if second_row_label is None or second_row_label[0] != header_label[0] or second_row_label[1] != first_row_label[1] + 1:
            return False

    return len(normalize_text(headers[1])) >= 8


def should_drop_duplicate_headers(headers: list[str], blocks: list[BlockNode]) -> bool:
    if not headers or looks_like_semantic_headers(headers) or looks_like_field_descriptor_row(headers):
        return False
    header_text = normalize_text(" ".join(header for header in headers if header)).lower()
    if len(header_text) < 12:
        return False
    body_texts = {
        normalize_text(block.text).lower()
        for block in blocks
        if block.type not in {"header", "footer"} and normalize_text(block.text)
    }
    return header_text in body_texts


def parse_enumerated_row_label(value: str) -> tuple[str, int] | None:
    match = re.match(r"^([A-Za-z][A-Za-z _/-]{0,20}?)\s*(\d{1,3})\b", normalize_text(value))
    if not match:
        return None
    prefix = normalize_text(match.group(1)).lower()
    return prefix, int(match.group(2))

def clean_table_rows(headers: list[str], rows: list[list]) -> list[list[str]]:
    cleaned_rows: list[list[str]] = []
    for row in rows:
        cleaned_row: list[str] = []
        for index, cell in enumerate(row):
            header = headers[index] if index < len(headers) else ""
            cleaned_row.append(normalize_table_cell(str(cell or ""), header))
        cleaned_rows.append(cleaned_row)
    if cleaned_rows and row_matches_headers(headers, cleaned_rows[0]):
        cleaned_rows = cleaned_rows[1:]
    return cleaned_rows


def normalize_table_cell(value: str, header: str) -> str:
    normalized = normalize_cell_text(value)
    if normalize_text(header).lower() == "description":
        return format_description_text(normalized)
    return normalized


def looks_like_semantic_headers(headers: list[str]) -> bool:
    if len(headers) != 4:
        return False
    normalized = [normalize_text(header).lower() for header in headers]
    return (
        normalized[0] in {"field", "fields", "parameter", "parameters", "param", "params"}
        and normalized[1] in {"required", "require", "mandatory", "optional"}
        and normalized[2] in {"type", "data type", "datatype"}
        and normalized[3] in {"description", "desc", "remark", "remarks", "meaning", "notes"}
    )


def looks_like_field_descriptor_row(values: list[str]) -> bool:
    if len(values) != 4:
        return False
    second = normalize_text(values[1]).upper()
    third = normalize_text(values[2])
    return second in {"Y", "N", "YES", "NO", "M", "O", "REQUIRED", "OPTIONAL"} and bool(TYPE_TOKEN_RE.match(third))


def row_matches_headers(headers: list[str], row: list[str]) -> bool:
    if len(headers) != len(row):
        return False
    return [normalize_text(cell).lower() for cell in headers] == [normalize_text(cell).lower() for cell in row]


def build_table_id(source_page: int, snapshot_index: int) -> str:
    return f"p{source_page:04d}-t{snapshot_index:02d}"


def bind_captions(
    blocks: list[BlockNode],
    images: list[ImageNode],
    *,
    page_width: float,
    page_height: float,
    warnings: list[str],
) -> None:
    left_tolerance = page_width * IMAGE_CAPTION_LEFT_TOLERANCE_RATIO
    vertical_gap = page_height * IMAGE_CAPTION_VERTICAL_GAP_RATIO
    paragraph_like = [block for block in blocks if block.type in {"paragraph", "quote", "list_item"}]
    for image in images:
        image_bottom = float(image.bbox[3])
        image_left = float(image.bbox[0])
        candidate = None
        candidate_distance = None
        for block in paragraph_like:
            block_top = float(block.bbox[1])
            block_left = float(block.bbox[0])
            if block_top < image_bottom:
                continue
            if abs(block_left - image_left) > left_tolerance:
                continue
            distance = block_top - image_bottom
            if distance > vertical_gap:
                continue
            if candidate is None or distance < candidate_distance:
                candidate = block
                candidate_distance = distance
        if candidate is not None:
            image.caption = candidate.text
        else:
            warnings.append(f"image_caption_unbound:{image.source_page}:{image.asset_path}")


def extract_block_text(block: dict) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = [str(span.get("text", "")) for span in line.get("spans", []) if span.get("text")]
        line_text = "".join(spans).strip()
        if line_text:
            lines.append(line_text)
    return "\n".join(lines).strip()


def classify_block(
    text: str,
    block: dict,
    *,
    display_title: str,
    first_page: bool,
    max_font_size: float,
    page_height: float,
    reading_order: int,
) -> str:
    normalized_text = normalize_text(text)
    normalized_title = normalize_text(display_title)
    font_names = {str(span.get("font", "")).lower() for line in block.get("lines", []) for span in line.get("spans", [])}
    font_size = _max_font_size(block)
    bbox = block.get("bbox", (0, 0, 0, 0))
    top = float(bbox[1]) if len(bbox) >= 2 else 0.0
    bottom = float(bbox[3]) if len(bbox) >= 4 else 0.0

    if first_page and normalized_text == normalized_title:
        return "heading"
    if first_page and reading_order == 1 and max_font_size > 0 and font_size >= max(14.0, max_font_size * 0.95) and len(text) <= 120:
        return "heading"
    if looks_like_heading(text, font_size=font_size, max_font_size=max_font_size):
        return "heading"
    if is_code_block(text, block):
        return "code"
    if is_list_item(text):
        return "list_item"
    if text.lstrip().startswith(">"):
        return "quote"
    if top <= page_height * 0.08 and len(text) <= 80:
        return "header"
    if bottom >= page_height * 0.92 and len(text) <= 80:
        return "footer"
    # footnote is a reserved contract type. Keep paragraph until a dedicated detector is added.
    return "paragraph"


def detect_heading_level(text: str, *, font_size: float = 0, max_font_size: float = 0) -> int:
    """Detect heading level (1-6) from section numbering patterns and font size."""
    stripped = text.strip()

    # Chinese chapter/appendix → H1
    if HEADING_CHAPTER_RE.match(stripped) or HEADING_APPENDIX_RE.match(stripped):
        return 1
    # Chinese section → H2
    if HEADING_SECTION_RE.match(stripped):
        return 2

    # Numbered sections: count dots → depth
    m = HEADING_NUM_RE.match(stripped)
    if m:
        return min(m.group(1).count(".") + 1, 6)

    # Letter-prefixed numbered sections (e.g. A1.2.3)
    m = HEADING_ALPHA_NUM_RE.match(stripped)
    if m:
        return min(m.group(1).count(".") + 1, 6)

    # Font-size ratio fallback
    if max_font_size > 0 and font_size > 0:
        ratio = font_size / max_font_size
        if ratio >= 0.95:
            return 1
        if ratio >= 0.80:
            return 2
        if ratio >= 0.65:
            return 3

    return 2  # safe default


def looks_like_heading(text: str, *, font_size: float, max_font_size: float) -> bool:
    if max_font_size <= 0 or font_size < 14 or font_size < max_font_size * 0.85 or len(text) > 120:
        return False
    stripped = text.strip()
    return bool(SECTION_HEADING_RE.match(stripped))


CODE_FONT_TOKENS = (
    "courier", "mono", "consolas", "code", "menlo", "source code",
    "fira", "hack", "inconsolata", "dejavu", "liberation mono",
    "roboto mono", "ubuntu mono", "cascadia", "jetbrains",
    "lucida console", "andale mono", "noto mono",
)


_TOC_LINE_RE = re.compile(r"\.{3,}\s*\d+\s*$")
# Unicode bullets may directly precede text; ASCII - and * require a space
# to distinguish from shell flags (-X, -H) and glob patterns (*).
_BULLET_PROSE_RE = re.compile(r"^(?:[•￮▪]\s*|[-*]\s+)[A-Z]")


def _code_font_char_ratio(block: dict) -> tuple[int, int]:
    """Return (code_font_chars, total_chars) from span-level font data."""
    code_chars = 0
    total_chars = 0
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            span_text = str(span.get("text", "")).strip()
            char_count = len(span_text)
            if not char_count:
                continue
            total_chars += char_count
            font_name = str(span.get("font", "")).lower()
            if any(token in font_name for token in CODE_FONT_TOKENS):
                code_chars += char_count
    return code_chars, total_chars


def is_code_block(text: str, block: dict) -> bool:
    """Multi-signal code block detection.

    Scoring system:
      - Font ratio signal:     0-3 points
      - Structural signal:     0-3 points
      - Negative pre-circuit:  immediately returns False

    Threshold: total >= 3 to classify as code.
    """
    lines = [line for line in text.splitlines() if line.strip()]

    # --- Negative pre-circuit: TOC / bullet prose ---
    if lines:
        toc_count = sum(1 for line in lines if _TOC_LINE_RE.search(line))
        if toc_count >= max(1, len(lines) * 0.4):
            return False
        bullet_count = sum(1 for line in lines if _BULLET_PROSE_RE.match(line.strip()))
        if bullet_count >= max(1, len(lines) * 0.5):
            return False

    # --- Signal 1: Font-based (span-level ratio + tiered minimum count) ---
    # High ratio needs fewer absolute chars (short code line, fully monospace).
    # Low ratio needs more chars to avoid noise from small Courier spans.
    code_chars, total_chars = _code_font_char_ratio(block)
    font_score = 0
    if total_chars > 0:
        ratio = code_chars / total_chars
        if ratio >= 0.8 and code_chars >= 8:
            font_score = 3
        elif ratio >= 0.6 and code_chars >= 20:
            font_score = 2
        elif ratio >= 0.4 and code_chars >= 30:
            font_score = 1

    # --- Signal 2: Structural code patterns ---
    structure_score = 0
    if len(lines) >= 2:
        indented_count = sum(1 for line in lines if line.startswith(("    ", "\t")))
        if indented_count >= max(2, len(lines) * 0.6):
            structure_score = 3

        keyword_lines = sum(1 for line in lines if CODE_KEYWORD_RE.match(line.strip()))
        marker_lines = sum(1 for line in lines if CODE_MARKER_RE.search(line))
        if keyword_lines > 0 and marker_lines > 0:
            structure_score = max(structure_score, 3)
        elif len(lines) >= 3 and marker_lines >= len(lines) * 0.7:
            structure_score = max(structure_score, 2)

    # --- Combined scoring ---
    return (font_score + structure_score) >= 3


def is_list_item(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("- ", "* ", "• ")) or bool(NUMBERED_LIST_RE.match(stripped))


def is_complex_table(headers: list[str], rows: list[list], markdown: str) -> bool:
    if not rows or not markdown:
        return True
    row_lengths = {len(row) for row in rows}
    if len(row_lengths) > 1:
        return True
    if re.search(r"[A-Za-z]{2,}<br>[A-Za-z]{1,}", markdown):
        return True
    if has_nested_table_signals(headers, rows, markdown):
        return True
    return False


def has_nested_table_signals(headers: list[str], rows: list[list], markdown: str) -> bool:
    normalized_headers = [normalize_text(str(header)) for header in headers if str(header).strip()]
    if any(re.fullmatch(r"Col\d+", header) for header in normalized_headers) and len(rows) > 2:
        return True
    if re.search(r"Objects of|Supported Types:|Limits?:|description\s*\(", markdown, re.IGNORECASE):
        return True
    for row in rows:
        normalized_cells = [normalize_text(str(cell)) for cell in row if normalize_text(str(cell))]
        if not normalized_cells:
            continue
        if len(set(normalized_cells)) == 1 and len(normalized_cells) >= 2 and len(normalized_cells[0]) >= 12:
            return True
        if any((str(cell).count("\n") >= 2) or (len(str(cell)) >= 80 and ":" in str(cell)) for cell in row if cell):
            return True
    return False


def escape_html(value: str) -> str:
    normalized = normalize_cell_text(value)
    escaped = normalized.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return escaped.replace("\r\n", "<br/>").replace("\n", "<br/>")


def normalize_cell_text(value: str) -> str:
    raw_lines = value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.strip() for line in raw_lines if line.strip()]
    if not lines:
        return ""

    merged = [lines[0]]
    for line in lines[1:]:
        previous = merged[-1]
        if should_join_without_space(previous, line):
            merged[-1] = f"{previous}{line}"
        elif should_join_with_space(previous, line):
            merged[-1] = f"{previous} {line}"
        else:
            merged.append(line)
    return "\n".join(merged)


def should_join_without_space(previous: str, current: str) -> bool:
    prev_token = last_token(previous)
    current_token = first_token(current)
    if not prev_token or not current_token:
        return False
    if prev_token.lower() in INLINE_CONNECTORS:
        return False
    if not WORDISH_CHAR_RE.fullmatch(prev_token[-1]) or not WORDISH_CHAR_RE.fullmatch(current_token[0]):
        return False
    if any(marker in f"{prev_token}{current_token}" for marker in ("<", ">")):
        return True

    # Detect camelCase identifier continuation:
    # e.g. "cryptoAd" + "dressInfo" → join produces "cryptoAddressInfo" (has [a-z][A-Z])
    # Guard: the camelCase boundary must be NEAR the join point.  If both
    # tokens already have their own internal camelCase (e.g. "cryptoMethod" +
    # "cryptoAddressInfo"), they are separate identifiers, not fragments.
    if current_token[0].islower():
        join_pos = len(prev_token)
        joined = prev_token + current_token
        neighborhood = joined[max(0, join_pos - 3):join_pos + 3]
        if re.search(r"[a-z][A-Z]", neighborhood):
            return True

    # Detect PascalCase split when both lines are single-word tokens:
    # e.g. "complete" + "Time" → join produces "completeTime"
    # Guard: if BOTH tokens are common English words, it is almost certainly
    # a normal phrase ("Request Example"), not a split identifier.
    if (current_token[0].isupper() and prev_token[-1].islower()
            and previous.strip() == prev_token and current.strip() == current_token
            and current_token.lower() not in INLINE_CONNECTORS
            and len(prev_token) + len(current_token) <= 35):
        both_common = (prev_token.lower() in _PASCAL_COMMON_WORDS
                       and current_token.lower() in _PASCAL_COMMON_WORDS)
        if not both_common:
            joined = prev_token + current_token
            if re.search(r"[a-z][A-Z]", joined):
                return True

    # Short-fragment fallback: e.g. "respons" + "e", "lis" + "t"
    # Exclude common English words (prepositions, conjunctions) to prevent
    # "used"+"for" → "usedfor" or "Array"+"of" → "Arrayof".
    return (current_token[0].islower()
            and current_token.lower() not in INLINE_CONNECTORS
            and ((len(prev_token) >= 3 and len(current_token) <= 3)
                 or (len(prev_token) == 1 and prev_token.isalpha())))


def should_join_with_space(previous: str, current: str) -> bool:
    if previous.endswith((":", ";", "?")):
        return False
    if CLAUSE_BREAK_RE.match(current):
        return False
    if BULLET_OR_NUMBERED_LINE_RE.match(current):
        return False
    if previous.rstrip().endswith(tuple("0123456789")) and current[:1].isupper():
        return False
    if normalize_text(previous).endswith(("Format", "Limits", "Limit", "Allowed", "Supported Types", "Character limit")):
        return False
    prev_token = last_token(previous)
    current_token = first_token(current)
    if not prev_token or not current_token:
        return False
    if not WORDISH_CHAR_RE.fullmatch(prev_token[-1]) or not WORDISH_CHAR_RE.fullmatch(current_token[0]):
        return False
    return True


def apply_inline_clause_breaks(value: str) -> str:
    text = value
    text = re.sub(
        r"(?<=[A-Za-z]) (?=(?:Format\b|For example\b|ISO\b|Allowed:|Supported Types:|MSB Limits:|SaintPay Limits:|Character limit:|Unsupported\b|Limit \d))",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    # Break before numbered items: "frequency 1-Less" → "frequency\n1-Less"
    text = re.sub(r"(?<=[a-z\"]) (?=\d+\s*-\s*[A-Za-z])", "\n", text)
    # Break before letter-prefixed numbered items: "day V1- Lower" → "day\nV1- Lower"
    # Only after lowercase/digit to avoid splitting "USD V1-"
    text = re.sub(r"(?<=[a-z0-9)\"]) (?=[A-Z]\d+\s*-)", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def format_description_text(value: str) -> str:
    value = apply_inline_clause_breaks(value)
    lines = [line.strip() for line in value.split("\n") if line.strip()]
    if not lines:
        return ""

    formatted: list[str] = []
    for line in lines:
        current = normalize_description_line(line)
        if formatted and formatted[-1] == "Format:" and not current.startswith(("•", "For example:")):
            current = f"• {current}"
        formatted.append(current)
    return "\n".join(formatted)


def normalize_description_line(line: str) -> str:
    if line == "Format":
        return "Format:"
    if line.startswith("For example ") and not line.startswith("For example:"):
        return f"For example: {line[len('For example '):].strip()}"
    if line.startswith("Example ") and not line.startswith("Example:"):
        return f"Example: {line[len('Example '):].strip()}"
    if line.startswith("Allowed ") and not line.startswith("Allowed:"):
        return f"Allowed: {line[len('Allowed '):].strip()}"
    if line.startswith("Supported Types ") and not line.startswith("Supported Types:"):
        return f"Supported Types: {line[len('Supported Types '):].strip()}"
    return line



def last_token(value: str) -> str:
    parts = value.split()
    return parts[-1] if parts else ""


def first_token(value: str) -> str:
    parts = value.split()
    return parts[0] if parts else ""


def escape_html_attr(value: str) -> str:
    return escape_html(value).replace('"', "&quot;")


def round_bbox(bbox: tuple | list) -> list[float]:
    return [round(float(value), 3) for value in bbox]


def build_bbox_hash(bbox: list[float]) -> str:
    payload = json.dumps(bbox, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split()).strip()


def build_dedupe_key(source_page: int, text: str, bbox_hash: str = "") -> str:
    normalized = normalize_text(text)
    text_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{source_page}:{text_hash}:{bbox_hash}"


def _max_font_size(block: dict) -> float:
    sizes = [float(span.get("size", 0.0)) for line in block.get("lines", []) for span in line.get("spans", [])]
    return max(sizes, default=0.0)










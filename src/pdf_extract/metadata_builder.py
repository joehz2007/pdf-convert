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
            if not markdown:
                warnings.append(f"empty_markdown_page:{source_page}")

            page = document[expected_slice_page - 1]
            blocks = extract_text_blocks(
                page,
                source_page=source_page,
                display_title=task.display_title,
                is_overlap=source_page in task.overlap_pages,
                first_page=(expected_slice_page == 1),
            )
            if markdown and not blocks:
                warnings.append(f"no_blocks_page:{source_page}")
            suppressed_table_markdown = int(chunk.get("suppressed_table_markdown", 0) or 0)
            if suppressed_table_markdown > 0:
                warnings.append(f"suppressed_broken_table_markdown:{source_page}:{suppressed_table_markdown}")

            tables = extract_tables(
                page,
                chunk,
                source_page=source_page,
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
                    is_overlap=source_page in task.overlap_pages,
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
    assets_dir: Path | None,
) -> list[TableNode]:
    table_id = build_table_id(source_page, snapshot_index)
    fallback_image = None
    if complex_table and assets_dir is not None:
        fallback_image = export_table_clip(page, bbox, assets_dir, source_page=source_page, table_index=snapshot_index)

    display_headers = normalize_table_headers(headers, rows)
    parent_rows, child_sections = split_nested_table_sections(rows)
    if complex_table and child_sections:
        child_ids = [f"{table_id}-c{child_index:02d}" for child_index in range(1, len(child_sections) + 1)]
        cleaned_parent_rows = clean_table_rows(display_headers, parent_rows)
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
                fallback_html=render_table_html(
                    headers=display_headers,
                    rows=cleaned_parent_rows,
                    table_id=table_id,
                    table_role="parent",
                    child_table_ids=child_ids,
                ),
                fallback_image=fallback_image,
                table_id=table_id,
                table_role="parent",
                child_table_ids=child_ids,
            )
        ]
        for child_index, section in enumerate(child_sections, start=1):
            child_id = f"{table_id}-c{child_index:02d}"
            cleaned_child_rows = clean_table_rows(display_headers, list(section["rows"]))
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
                    fallback_html=render_table_html(
                        headers=display_headers,
                        rows=cleaned_child_rows,
                        table_id=child_id,
                        table_role="child",
                        parent_table_id=table_id,
                        section_title=normalize_section_title(str(section["title"])),
                    ),
                    fallback_image=fallback_image,
                    table_id=child_id,
                    parent_table_id=table_id,
                    table_role="child",
                    section_title=normalize_section_title(str(section["title"])),
                )
            )
        return nodes

    cleaned_rows = clean_table_rows(display_headers, rows)
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
            fallback_html=render_table_html(
                headers=display_headers,
                rows=cleaned_rows,
                table_id=table_id,
                table_role="standalone",
            )
            if complex_table
            else None,
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
    if is_code_block(text, font_names):
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


def is_code_block(text: str, font_names: set[str]) -> bool:
    # Font check with expanded patterns
    if any(name for name in font_names if any(token in name for token in CODE_FONT_TOKENS)):
        return True

    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False

    # Consistent indentation (>= 60% of lines)
    indented_count = sum(1 for line in lines if line.startswith(("    ", "\t")))
    if indented_count >= max(2, len(lines) * 0.6):
        return True

    # Keywords + markers both present (original logic)
    keyword_lines = sum(1 for line in lines if CODE_KEYWORD_RE.match(line.strip()))
    marker_lines = sum(1 for line in lines if CODE_MARKER_RE.search(line))
    if keyword_lines > 0 and marker_lines > 0:
        return True

    # High density of code markers alone (brackets, operators, etc.)
    if len(lines) >= 3 and marker_lines >= len(lines) * 0.7:
        return True

    return False


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
    return current_token[0].islower() and ((len(prev_token) >= 3 and len(current_token) <= 4) or (len(prev_token) == 1 and prev_token.isalpha()))


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

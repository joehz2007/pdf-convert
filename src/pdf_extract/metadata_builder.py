from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pymupdf

from .assets_exporter import export_page_images, export_table_clip
from .config import IMAGE_CAPTION_LEFT_TOLERANCE_RATIO, IMAGE_CAPTION_VERTICAL_GAP_RATIO
from .contracts import BlockNode, ContentResult, ImageNode, OutlineNode, PageContent, SliceTask, TableNode
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
INLINE_CONNECTORS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "not", "of", "on", "or", "the", "to", "with"}
TABLE_BLOCK_OVERLAP_RATIO = 0.6
SAFE_INLINE_HTML_TAG_RE = re.compile(r"</?(?:b|strong|s|u|br)\s*/?>", re.IGNORECASE)
EMPHASIZED_DESCRIPTION_PREFIXES = (
    "Supported:",
    "Currently Supported:",
    "Implied responsibility:",
    "Allowed:",
    "Description:",
)
DEPRECATED_FIELD_REPLACEMENTS = {
    "cryptoMethod cryptoAddressInfo": "<s>cryptoMethod</s><br/>cryptoAddressInfo",
    "fiatMethod fiatAccountInfo": "<s>fiatMethod</s><br/>fiatAccountInfo",
    "fiatMethodfiatAccountInfo": "<s>fiatMethod</s><br/>fiatAccountInfo",
}
DEPRECATED_WHOLE_ROW_FIELDS = {"feeDetails", "channelFee"}
TYPE_NORMALIZATION_REPLACEMENTS = (
    (re.compile(r"\bArrays of string\b", re.IGNORECASE), "Array of strings"),
    (re.compile(r"\bArray s\.object\b", re.IGNORECASE), "Array of objects"),
    (re.compile(r"\bboole an\b", re.IGNORECASE), "boolean"),
)
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
_REJOIN_STOPWORDS = INLINE_CONNECTORS | {
    "not", "no", "but", "it", "its", "is", "are", "was", "were",
    "be", "been", "has", "had", "have", "do", "does", "did",
    "will", "can", "may", "must", "shall", "should", "would", "could",
    "this", "that", "these", "those", "if", "so", "per", "via",
}
CLAUSE_BREAK_RE = re.compile(
    r"^(?:Format|For example|Example|Allowed:?|Character limit:?|Mandatory|Optional|Unsupported\b|Supported Types:?|MSB Limits:?|SaintPay Limits:?|Limit(?:s)?:|Limit \d|ISO\b|Implied responsibility:?|Currently Supported:?|Note:|Possible values|Must include:|SAINT_PAY:?|MSB:?)",
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

        # First pass: extract raw blocks from all pages to compute slice-level body margin
        raw_page_blocks: list[tuple[int, int, str, bool, list[BlockNode]]] = []
        for expected_slice_page, chunk in enumerate(page_chunks, start=1):
            metadata = chunk.get("metadata", {})
            chunk_page = int(metadata.get("page", expected_slice_page))
            if chunk_page != expected_slice_page:
                raise PageMappingError(
                    f"Slice '{task.slice_file}' returned page chunk {chunk_page}, expected {expected_slice_page}."
                )
            source_page = task.start_page + expected_slice_page - 1
            is_overlap = source_page in task.overlap_pages
            page = document[expected_slice_page - 1]
            blocks = extract_text_blocks(
                page,
                source_page=source_page,
                display_title=task.display_title,
                is_overlap=is_overlap,
                first_page=(expected_slice_page == 1),
            )
            markdown = str(chunk.get("text", "")).strip()
            raw_page_blocks.append((expected_slice_page, source_page, markdown, is_overlap, blocks))

        # Compute slice-level body left margin from headings and long body-text paragraphs
        slice_body_left = _compute_slice_body_left([blocks for _, _, _, _, blocks in raw_page_blocks])

        for (expected_slice_page, source_page, markdown, is_overlap, blocks), chunk in zip(raw_page_blocks, page_chunks):
            page = document[expected_slice_page - 1]
            blocks = merge_consecutive_code_paragraphs(
                blocks, source_page=source_page, is_overlap=is_overlap,
                slice_body_left=slice_body_left,
            )
            suppressed_table_markdown = int(chunk.get("suppressed_table_markdown", 0) or 0)
            if suppressed_table_markdown > 0:
                warnings.append(f"suppressed_broken_table_markdown:{source_page}:{suppressed_table_markdown}")

            tables, blocks = extract_tables(
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

    stitch_cross_page_code_blocks(source_pages)
    outline = build_document_outline(source_pages)

    return ContentResult(
        slice_file=task.slice_file,
        display_title=task.display_title,
        start_page=task.start_page,
        end_page=task.end_page,
        source_pages=source_pages,
        document_outline=outline,
        assets=assets,
        stats={
            "char_count": char_count,
            "table_count": table_count,
            "image_count": image_count,
        },
        warnings=warnings,
        manual_review_required=task.manual_review_required or bool(warnings),
    )

def build_document_outline(source_pages: list[PageContent]) -> list[OutlineNode]:
    """Build a document outline from heading blocks across all pages."""
    headings: list[tuple[int, int, str]] = []  # (source_page, level, title)
    for page in source_pages:
        for block in page.blocks:
            if block.type == "heading" and block.heading_level is not None:
                headings.append((block.source_page, block.heading_level, block.text.strip()))

    if not headings:
        return []

    nodes: list[OutlineNode] = []
    # Stack of (level, section_id) for tracking parent hierarchy
    parent_stack: list[tuple[int, str]] = []
    counters: dict[int, int] = {}  # level -> running counter

    for source_page, level, title in headings:
        # Pop stack entries at same or deeper level
        while parent_stack and parent_stack[-1][0] >= level:
            parent_stack.pop()

        parent_id = parent_stack[-1][1] if parent_stack else None

        # Build section_id: sec-1, sec-1.1, sec-1.1.2 etc.
        counters[level] = counters.get(level, 0) + 1
        # Reset counters for deeper levels
        for deeper in [k for k in counters if k > level]:
            del counters[deeper]

        if parent_id:
            section_id = f"{parent_id}.{counters[level]}"
        else:
            section_id = f"sec-{counters[level]}"

        nodes.append(OutlineNode(
            section_id=section_id,
            title=title,
            level=level,
            source_page=source_page,
            parent_id=parent_id,
        ))
        parent_stack.append((level, section_id))

    return nodes


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
    body_left_margin = _compute_body_left_margin(text_blocks, page_height)

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
            body_left_margin=body_left_margin,
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


# Regex for single-line fragments that look like code (JSON, braces, key-value pairs)
_CODE_FRAGMENT_RE = re.compile(
    r'^[\s]*[{}\[\](),;]+[,\s]*$'          # lone bracket/brace (with optional trailing comma)
    r'|"[^"]*"\s*:\s*'                     # JSON key-value
    r'|^\s*[a-zA-Z_]\w*\s*[:=]'            # assignment / key:
    r'|[{}\[\]();,]\s*$'                   # ends with bracket/semicolon/comma
)
_CODE_INDENT_THRESHOLD = 10  # minimum indent from body margin (pt)
_CODE_MERGE_MIN_RUN = 3      # minimum consecutive blocks to merge


def _compute_slice_body_left(all_page_blocks: list[list[BlockNode]]) -> float:
    """Compute a stable body left margin across all pages in a slice.

    Headings are the most reliable anchor for body text margin — they're almost
    never indented.  Falls back to the minimum left of any block.
    """
    heading_lefts = [
        b.bbox[0]
        for blocks in all_page_blocks
        for b in blocks
        if b.type == "heading"
    ]
    if heading_lefts:
        return min(heading_lefts)
    # Fallback: minimum left of any block
    all_lefts = [b.bbox[0] for blocks in all_page_blocks for b in blocks if b.text.strip()]
    return min(all_lefts) if all_lefts else 0.0


def merge_consecutive_code_paragraphs(
    blocks: list[BlockNode],
    *,
    source_page: int,
    is_overlap: bool,
    slice_body_left: float = 0.0,
) -> list[BlockNode]:
    """Merge runs of consecutive indented paragraph blocks into single code blocks.

    Targets code listings (JSON, etc.) where each line is a separate PDF text block.
    """
    if len(blocks) < _CODE_MERGE_MIN_RUN:
        return blocks

    # Use slice-level body margin if available, otherwise fall back to page-level minimum
    if slice_body_left > 0:
        body_left = slice_body_left
    else:
        all_lefts = [b.bbox[0] for b in blocks if b.text.strip()]
        if not all_lefts:
            return blocks
        body_left = min(all_lefts)

    result: list[BlockNode] = []
    i = 0
    while i < len(blocks):
        # Only try to merge paragraph blocks
        if blocks[i].type != "paragraph":
            result.append(blocks[i])
            i += 1
            continue

        # Scan for a run of code-like indented paragraphs
        run_start = i
        while i < len(blocks) and blocks[i].type == "paragraph":
            b = blocks[i]
            indent = b.bbox[0] - body_left
            is_code_like = (
                indent >= _CODE_INDENT_THRESHOLD
                and bool(_CODE_FRAGMENT_RE.search(b.text))
            )
            if not is_code_like:
                break
            i += 1

        run_length = i - run_start
        if run_length >= _CODE_MERGE_MIN_RUN:
            run_blocks = blocks[run_start:i]
            merged_text = "\n".join(b.text for b in run_blocks)
            merged_bbox = [
                min(b.bbox[0] for b in run_blocks),
                min(b.bbox[1] for b in run_blocks),
                max(b.bbox[2] for b in run_blocks),
                max(b.bbox[3] for b in run_blocks),
            ]
            bbox_hash = build_bbox_hash(merged_bbox)
            result.append(BlockNode(
                type="code",
                text=merged_text,
                source_page=source_page,
                bbox=merged_bbox,
                reading_order=run_blocks[0].reading_order,
                is_overlap=is_overlap,
                dedupe_key=build_dedupe_key(source_page, merged_text, bbox_hash),
                heading_level=None,
            ))
        else:
            # Not enough consecutive blocks — keep as-is and advance past them
            result.extend(blocks[run_start:i])
            if i == run_start:
                # The paragraph at run_start didn't match code criteria — emit it and move on
                result.append(blocks[i])
                i += 1

    return result


def _bracket_balance(text: str) -> int:
    """Return the net open-bracket count for code text.

    Positive means there are unclosed openers ({, [, ().
    Only counts brackets outside of quoted strings (simple heuristic).
    """
    balance = 0
    in_string = False
    escape = False
    quote_char = ""
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if in_string:
            if ch == quote_char:
                in_string = False
            continue
        if ch in ('"', "'"):
            in_string = True
            quote_char = ch
            continue
        if ch in "{[(":
            balance += 1
        elif ch in "}])":
            balance -= 1
    return balance


# Patterns that signal a definite context break — not part of code continuation
_CONTEXT_BREAK_RE = re.compile(
    r"^#{1,6}\s"                                   # Markdown heading
    r"|^(?:Request|Response)\s+(?:Parameters?|Headers?|Body)\s*[:：]"  # API table label
    r"|^(?:请求|响应)(?:参数|头|体)\s*[:：]"          # Chinese API table label
    r"|^\|.*\|.*\|"                                 # Markdown table row
    r"|^[-=]{3,}"                                   # horizontal rule / separator
    r"|^>\s"                                        # blockquote
)


def _is_context_break(block: BlockNode) -> bool:
    """Return True if this block clearly starts a new non-code section."""
    if block.type == "heading":
        return True
    if block.type == "table":
        return True
    text = block.text.strip()
    if _CONTEXT_BREAK_RE.match(text):
        return True
    return False


def stitch_cross_page_code_blocks(source_pages: list[PageContent]) -> None:
    """Stitch code blocks across page boundaries using bracket-balance context.

    When the last block of page N is a code block with unclosed brackets
    (positive bracket balance), use **permissive continuation mode** for the
    next page — absorb ALL blocks (regardless of indent or appearance) until:
      1. Bracket balance reaches zero or below (code context closed), or
      2. A clear context break is hit (heading, table label, table row).

    When brackets are balanced, falls back to the original conservative mode
    that only absorbs blocks independently recognizable as code/code-fragments.

    Runs iteratively until no more stitching is possible.
    """
    changed = True
    while changed:
        changed = False
        for i in range(len(source_pages)):
            curr_blocks = source_pages[i].blocks
            if not curr_blocks or curr_blocks[-1].type != "code":
                continue

            # Find the next non-empty page
            j = i + 1
            while j < len(source_pages) and not source_pages[j].blocks:
                j += 1
            if j >= len(source_pages):
                continue

            tail_code = curr_blocks[-1]
            balance = _bracket_balance(tail_code.text)
            permissive = balance > 0  # unclosed brackets → absorb aggressively

            next_blocks = source_pages[j].blocks
            first_next = next_blocks[0]

            # Gate check: in conservative mode, the first block must look like code
            if not permissive:
                if first_next.type != "code" and not (
                    first_next.type == "paragraph" and _is_code_fragment(first_next.text)
                ):
                    continue

            # Absorb blocks from next page
            absorbed = 0
            running_balance = balance
            for nb in next_blocks:
                if permissive:
                    # In permissive mode: absorb everything except clear context breaks
                    if _is_context_break(nb):
                        break
                    tail_code.text = tail_code.text + "\n" + nb.text
                    if nb.type == "code":
                        tail_code.bbox = [
                            min(tail_code.bbox[0], nb.bbox[0]),
                            tail_code.bbox[1],
                            max(tail_code.bbox[2], nb.bbox[2]),
                            max(tail_code.bbox[3], nb.bbox[3]),
                        ]
                    absorbed += 1
                    # Update running balance — if brackets close, switch to conservative
                    running_balance += _bracket_balance(nb.text)
                    if running_balance <= 0:
                        permissive = False
                else:
                    # Conservative mode: only absorb code blocks and code fragments
                    if nb.type == "code":
                        tail_code.text = tail_code.text + "\n" + nb.text
                        tail_code.bbox = [
                            min(tail_code.bbox[0], nb.bbox[0]),
                            tail_code.bbox[1],
                            max(tail_code.bbox[2], nb.bbox[2]),
                            max(tail_code.bbox[3], nb.bbox[3]),
                        ]
                        absorbed += 1
                        # Re-check: absorbing a code block may open new brackets
                        running_balance += _bracket_balance(nb.text)
                        if running_balance > 0:
                            permissive = True
                    elif nb.type == "paragraph" and _is_code_fragment(nb.text):
                        tail_code.text = tail_code.text + "\n" + nb.text
                        absorbed += 1
                    else:
                        break

            if absorbed > 0:
                source_pages[j].blocks = next_blocks[absorbed:]
                changed = True


def _is_code_fragment(text: str) -> bool:
    """Check if a single-line text looks like a stray code fragment (brace, bracket, JSON value)."""
    stripped = text.strip()
    if not stripped:
        return False
    # Lone brackets/braces with optional trailing comma
    if all(ch in "{}[](),; \t\n" for ch in stripped):
        return True
    # JSON-like value or key-value pattern
    if _CODE_FRAGMENT_RE.search(stripped):
        return True
    return False


def extract_tables(
    page: pymupdf.Page,
    chunk: dict,
    *,
    source_page: int,
    blocks: list[BlockNode],
    assets_dir: Path | None,
    warnings: list[str],
) -> tuple[list[TableNode], list[BlockNode]]:
    table_snapshots = list(chunk.get("table_snapshots", []))
    # Include consumed cross-page table bboxes for block overlap filtering
    consumed_bboxes = chunk.get("_consumed_table_bboxes", [])
    non_table_blocks = filter_blocks_overlapping_tables(blocks, table_snapshots)
    if consumed_bboxes:
        non_table_blocks = [b for b in non_table_blocks if not any(_bbox_overlap_ratio(b.bbox, round_bbox(cb)) >= 0.8 for cb in consumed_bboxes)]
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
    return tables, non_table_blocks


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
        parent_data_attributes = build_table_data_attributes(
            table_id=table_id,
            table_role="parent",
            child_table_ids=child_ids,
        )
        parent_fallback_html = render_table_html(
            headers=display_headers,
            rows=cleaned_parent_rows,
            table_id=table_id,
            table_role="parent",
            child_table_ids=child_ids,
        )
        parent_rendered_markdown = render_complex_table_markdown(
            headers=display_headers,
            rows=cleaned_parent_rows,
            data_attributes=parent_data_attributes,
            table_role="parent",
        )
        parent_fallback_image = None
        if parent_fallback_html is None and parent_rendered_markdown is None and assets_dir is not None:
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
                rendered_markdown=parent_rendered_markdown,
                fallback_html=parent_fallback_html,
                fallback_image=parent_fallback_image,
                table_id=table_id,
                table_role="parent",
                child_table_ids=child_ids,
                table_kind="nested",
                render_strategy="nested_sections",
                data_attributes=parent_data_attributes,
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
            cleaned_child_rows = _apply_section_specific_row_markup(repaired_title, cleaned_child_rows)
            child_data_attributes = build_table_data_attributes(
                table_id=child_id,
                table_role="child",
                parent_table_id=table_id,
            )
            child_fallback_html = render_table_html(
                headers=display_headers,
                rows=cleaned_child_rows,
                table_id=child_id,
                table_role="child",
                parent_table_id=table_id,
                section_title=repaired_title,
            )
            child_rendered_markdown = render_complex_table_markdown(
                headers=display_headers,
                rows=cleaned_child_rows,
                data_attributes=child_data_attributes,
                table_role="child",
                section_title=repaired_title,
            )
            child_fallback_image = None
            if child_fallback_html is None and child_rendered_markdown is None and assets_dir is not None:
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
                    rendered_markdown=child_rendered_markdown,
                    fallback_html=child_fallback_html,
                    fallback_image=child_fallback_image,
                    table_id=child_id,
                    parent_table_id=table_id,
                    table_role="child",
                    section_title=repaired_title,
                    table_kind="nested",
                    render_strategy="nested_sections",
                    data_attributes=child_data_attributes,
                )
            )
        return nodes

    cleaned_rows = clean_table_rows(display_headers, rows)
    table_data_attributes = build_table_data_attributes(
        table_id=table_id,
        table_role="standalone",
    )
    rendered_markdown = None
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
    if complex_table:
        rendered_markdown = render_complex_table_markdown(
            headers=display_headers,
            rows=cleaned_rows,
            data_attributes=table_data_attributes,
            table_role="standalone",
        )
    fallback_image = None
    if complex_table and fallback_html is None and rendered_markdown is None and assets_dir is not None:
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
            rendered_markdown=rendered_markdown,
            fallback_html=fallback_html,
            fallback_image=fallback_image,
            table_id=table_id,
            table_kind="complex" if complex_table else "simple",
            render_strategy="gfm_table",
            data_attributes=table_data_attributes,
        )
    ]


def filter_blocks_overlapping_tables(blocks: list[BlockNode], table_snapshots: list[dict]) -> list[BlockNode]:
    if not blocks or not table_snapshots:
        return blocks

    filtered: list[BlockNode] = []
    for block in blocks:
        max_overlap = 0.0
        max_match_score = 0.0
        embedded_table_block = False
        for snapshot in table_snapshots:
            table_bbox = round_bbox(snapshot.get("bbox", (0, 0, 0, 0)))
            overlap = _bbox_overlap_ratio(block.bbox, table_bbox)
            if overlap <= 0:
                continue
            max_overlap = max(max_overlap, overlap)
            max_match_score = max(max_match_score, _block_table_text_match_score(block.text, snapshot))
            if overlap >= TABLE_BLOCK_OVERLAP_RATIO:
                snapshot_for_match = snapshot if _table_snapshot_exact_texts(snapshot) else None
                embedded_table_block = embedded_table_block or looks_like_table_embedded_block(block.text, snapshot_for_match)
        if (
            max_match_score >= 0.85 and max_overlap >= 0.25
        ) or (
            max_overlap >= TABLE_BLOCK_OVERLAP_RATIO and max_match_score >= 0.5
        ) or embedded_table_block or (
            max_overlap >= 0.95 and len(block.text.split()) <= 6
        ):
            continue
        filtered.append(block)
    return filtered


def looks_like_table_embedded_block(text: str, snapshot: dict | None = None) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    token_count = len(stripped.split())
    if snapshot is None:
        return token_count <= 4 or bool(re.search(r"[A-Za-z]+\d*[:/]?$", stripped))
    match_score = _block_table_text_match_score(stripped, snapshot)
    if match_score >= 0.85:
        return True
    if "\n" in stripped and match_score >= 0.55:
        return True
    return token_count <= 4 and match_score >= 0.45


def _bbox_overlap_ratio(left: list[float], right: list[float]) -> float:
    left_area = _bbox_area(left)
    if left_area <= 0:
        return 0.0

    overlap_left = max(float(left[0]), float(right[0]))
    overlap_top = max(float(left[1]), float(right[1]))
    overlap_right = min(float(left[2]), float(right[2]))
    overlap_bottom = min(float(left[3]), float(right[3]))
    if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
        return 0.0

    overlap_area = (overlap_right - overlap_left) * (overlap_bottom - overlap_top)
    return overlap_area / left_area


def _bbox_area(bbox: list[float]) -> float:
    if len(bbox) < 4:
        return 0.0
    return max(float(bbox[2]) - float(bbox[0]), 0.0) * max(float(bbox[3]) - float(bbox[1]), 0.0)


def _block_table_text_match_score(text: str, snapshot: dict) -> float:
    block_text = normalize_text(text)
    if not block_text:
        return 0.0

    exact_texts = _table_snapshot_exact_texts(snapshot)
    if block_text in exact_texts:
        return 1.0

    combined_text = normalize_text(" ".join(exact_texts))
    if combined_text and len(block_text) >= 12 and block_text in combined_text:
        return 0.95

    block_tokens = _normalized_token_set(block_text)
    table_tokens = _normalized_token_set(combined_text)
    if not block_tokens or not table_tokens:
        return 0.0
    overlap = len(block_tokens & table_tokens) / len(block_tokens)
    if len(block_tokens) >= 4 and overlap >= 0.75:
        return overlap
    return 0.0


def _table_snapshot_exact_texts(snapshot: dict) -> set[str]:
    texts: set[str] = set()
    headers = [normalize_text(str(header or "")) for header in snapshot.get("headers", []) if normalize_text(str(header or ""))]
    if headers:
        texts.add(normalize_text(" ".join(headers)))
        texts.update(headers)
    for row in snapshot.get("rows", []):
        normalized_row = [normalize_text(str(cell or "")) for cell in row if normalize_text(str(cell or ""))]
        if normalized_row:
            texts.add(normalize_text(" ".join(normalized_row)))
            texts.update(normalized_row)
    markdown = normalize_text(str(snapshot.get("markdown") or ""))
    if markdown:
        texts.add(markdown)
    return texts


def _normalized_token_set(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_./+-]+", text) if len(token) >= 2}


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


def build_table_data_attributes(
    *,
    table_id: str,
    table_role: str,
    parent_table_id: str | None = None,
    child_table_ids: list[str] | None = None,
) -> dict[str, str]:
    attributes = {
        "data-table-id": table_id,
        "data-table-role": table_role,
    }
    if parent_table_id:
        attributes["data-parent-table-id"] = parent_table_id
    if child_table_ids:
        attributes["data-child-table-ids"] = ",".join(child_table_ids)
    return attributes


def render_complex_table_markdown(
    *,
    headers: list[str],
    rows: list[list[str]],
    data_attributes: dict[str, str],
    table_role: str,
    section_title: str | None = None,
) -> str | None:
    table_markdown = render_gfm_table(headers, rows)
    fragments: list[str] = []
    if section_title:
        fragments.append(f"**{section_title.strip()}**")
    fragments.append(render_table_metadata_line(data_attributes))
    if table_markdown:
        fragments.append(table_markdown)
    elif table_role != "parent":
        fragments.append("_Complex table content could not be rendered as a Markdown table._")

    rendered = "\n\n".join(fragment for fragment in fragments if fragment).strip()
    return rendered or None


def render_table_metadata_line(data_attributes: dict[str, str]) -> str:
    ordered_keys = (
        "data-table-id",
        "data-table-role",
        "data-parent-table-id",
        "data-child-table-ids",
    )
    parts = [f"`{key}={data_attributes[key]}`" for key in ordered_keys if data_attributes.get(key)]
    return "Table metadata: " + " ".join(parts) if parts else ""


def render_gfm_table(headers: list[str], rows: list[list[str]]) -> str | None:
    normalized_headers = [str(header or "").strip() for header in headers]
    normalized_rows = [[str(cell or "").strip() for cell in row] for row in rows]
    if not normalized_headers and normalized_rows and all(cell for cell in normalized_rows[0]):
        normalized_headers = normalized_rows[0]
        normalized_rows = normalized_rows[1:]
    if not normalized_headers:
        return None

    column_count = max(len(normalized_headers), *(len(row) for row in normalized_rows), 0)
    if column_count <= 0:
        return None

    header_cells = [escape_markdown_table_cell(normalized_headers[index] if index < len(normalized_headers) else "") for index in range(column_count)]
    lines = [
        "| " + " | ".join(header_cells) + " |",
        "| " + " | ".join("---" for _ in range(column_count)) + " |",
    ]
    for row in normalized_rows:
        row_cells = [escape_markdown_table_cell(row[index] if index < len(row) else "") for index in range(column_count)]
        lines.append("| " + " | ".join(row_cells) + " |")
    return "\n".join(lines)


def escape_markdown_table_cell(value: str) -> str:
    normalized = normalize_cell_text(value)
    return normalized.replace("|", r"\|").replace("\n", "<br/>")


def normalize_table_headers(headers: list[str], rows: list[list]) -> list[str]:
    cleaned_headers = [normalize_cell_text(str(header or "")) for header in headers]
    if len(cleaned_headers) == 4 and looks_like_parameter_table_headers(cleaned_headers):
        return PARAMETER_TABLE_HEADERS.copy()
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
    if looks_like_semantic_headers(headers) or looks_like_parameter_table_headers(headers) or looks_like_field_descriptor_row(headers):
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
    if not headers or looks_like_semantic_headers(headers) or looks_like_parameter_table_headers(headers) or looks_like_field_descriptor_row(headers):
        return False
    header_text = normalize_text(" ".join(header for header in headers if header)).lower()
    if len(header_text) < 12:
        return False
    body_texts = {
        normalize_text(block.text).lower()
        for block in blocks
        if block.type != "footer" and normalize_text(block.text)
    }
    if header_text in body_texts:
        return True
    return any(
        len(body_text) >= 12 and (header_text in body_text or body_text in header_text)
        for body_text in body_texts
    )


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
        if any(cell.strip() for cell in cleaned_row):
            cleaned_rows.append(cleaned_row)
    cleaned_rows = _merge_sparse_continuation_rows(headers, cleaned_rows)
    cleaned_rows = [_apply_deprecated_row_markup(row) for row in cleaned_rows]
    while cleaned_rows and row_matches_header_semantics(headers, cleaned_rows[0]):
        cleaned_rows = cleaned_rows[1:]
    return cleaned_rows


def normalize_table_cell(value: str, header: str) -> str:
    normalized = _rejoin_split_identifiers(normalize_cell_text(value))
    header_name = normalize_text(header).lower()
    if header_name == "field":
        return _normalize_field_cell(normalized)
    if header_name == "type":
        return _normalize_type_cell(normalized)
    if header_name == "description":
        return _normalize_description_cell(normalized)
    return normalized


def _merge_sparse_continuation_rows(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    merged: list[list[str]] = []
    header_count = len(headers)
    for row in rows:
        padded = list(row) + [""] * max(0, header_count - len(row))
        if merged and _is_field_suffix_continuation_row(headers, padded, merged[-1]):
            previous = merged[-1]
            previous[0] = _merge_table_cell_fragments(previous[0], padded[0], headers[0] if headers else "Field")
            for index, cell in enumerate(padded[1:], start=1):
                if not cell:
                    continue
                header = headers[index] if index < len(headers) else ""
                previous[index] = _merge_table_cell_fragments(previous[index], cell, header)
            continue
        if merged and _is_sparse_continuation_row(padded):
            previous = merged[-1]
            for index, cell in enumerate(padded):
                if not cell:
                    continue
                header = headers[index] if index < len(headers) else ""
                previous[index] = _merge_table_cell_fragments(previous[index], cell, header)
            continue
        merged.append(padded)
    return merged


def _is_sparse_continuation_row(row: list[str]) -> bool:
    if len(row) < 4:
        return False
    return not row[0].strip() and not row[1].strip() and any(cell.strip() for cell in row[2:])


def _is_field_suffix_continuation_row(headers: list[str], row: list[str], previous: list[str]) -> bool:
    if len(headers) < 4 or len(row) < 4 or not previous:
        return False

    suffix = row[0].strip()
    if not suffix or len(suffix) > 5:
        return False
    if any(cell.strip() for cell in row[1:3]):
        return False

    previous_field = previous[0].strip() if previous and previous[0] else ""
    if not previous_field:
        return False

    previous_tail = last_token(previous_field.replace("<br/>", " ").replace("<br>", " "))
    return _should_merge_field_tokens(previous_tail, suffix)


def _merge_table_cell_fragments(previous: str, current: str, header: str) -> str:
    if not previous:
        return current
    header_name = normalize_text(header).lower()
    if header_name == "description":
        separator = "\n" if current[:1].isalnum() else ""
    elif header_name == "field":
        combined = f"{previous} {current}".strip()
        return _repair_field_cell_fragments(combined)
    else:
        separator = " "
    return f"{previous}{separator}{current}".strip()


def _apply_deprecated_row_markup(row: list[str]) -> list[str]:
    if not row:
        return row
    field = normalize_text(row[0])
    if field not in DEPRECATED_WHOLE_ROW_FIELDS:
        return row
    return [f"<s>{cell}</s>" if cell else cell for cell in row]


def _normalize_field_cell(value: str) -> str:
    normalized = DEPRECATED_FIELD_REPLACEMENTS.get(value, value)
    return _repair_field_cell_fragments(normalized)


def _normalize_type_cell(value: str) -> str:
    normalized = value
    for pattern, replacement in TYPE_NORMALIZATION_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)
    if normalize_text(normalized) == "Object":
        normalized = "object"
    elif normalize_text(normalized) == "String":
        normalized = "string"
    return normalized


def _normalize_description_cell(value: str) -> str:
    normalized = format_description_text(value)
    normalized = re.sub(r"(?i)\+\s*bic(?=Allowed[:：]|\b)", "<<PLUS_BIC>>", normalized)
    return normalized.replace("<<PLUS_BIC>>", "<s>+ bic</s>")


def _repair_field_cell_fragments(value: str) -> str:
    tokens = value.split()
    if len(tokens) < 2:
        return value

    repaired = [tokens[0]]
    for token in tokens[1:]:
        previous = repaired[-1]
        if _should_merge_field_tokens(previous, token):
            repaired[-1] = previous + token
        else:
            repaired.append(token)
    if len(repaired) >= 2:
        collapsed: list[str] = [repaired[0]]
        for token in repaired[1:]:
            previous = collapsed[-1]
            if _should_drop_redundant_field_prefix(previous, token):
                collapsed[-1] = token
            else:
                collapsed.append(token)
        repaired = collapsed
    return " ".join(repaired)


def _should_merge_field_tokens(left: str, right: str) -> bool:
    if not left or not right or len(left) + len(right) > 40:
        return False
    if right.lower() in _REJOIN_STOPWORDS:
        return False
    if not re.fullmatch(r"[A-Za-z0-9<>/_-]+", left) or not re.fullmatch(r"[A-Za-z0-9<>/_-]+", right):
        return False

    if right[0].islower() and any(char.isupper() for char in right[1:]) and re.search(r"[a-z][A-Z]", left):
        return True
    if right.islower() and len(right) <= 4 and re.search(r"[a-z][A-Z]", left):
        return True
    if right.islower() and len(right) <= 8 and re.search(r"[a-z][A-Z]$", left):
        return True
    if len(right) == 1 and right.islower() and len(left) >= 4 and left[-1].isalpha():
        return True
    return False


def _should_drop_redundant_field_prefix(left: str, right: str) -> bool:
    if not left or not right or left == right:
        return False
    if " " in left or " " in right:
        return False
    if not re.fullmatch(r"[A-Za-z0-9_/-]+", left) or not re.fullmatch(r"[A-Za-z0-9_/-]+", right):
        return False

    left_normalized = left.lower()
    right_normalized = right.lower()
    return (
        len(left_normalized) >= 4
        and any(char.isupper() for char in right[1:])
        and right_normalized.endswith(left_normalized)
    )


def _apply_section_specific_row_markup(section_title: str, rows: list[list[str]]) -> list[list[str]]:
    if normalize_text(section_title).lower() != "params of fiataccountinfo":
        return rows
    updated_rows: list[list[str]] = []
    for row in rows:
        if len(row) >= 3 and normalize_text(row[0]) == "swift" and normalize_text(row[2]).lower() == "object":
            updated_rows.append([row[0], row[1], "<s>object</s>", *row[3:]])
            continue
        updated_rows.append(row)
    return updated_rows


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


def looks_like_parameter_table_headers(headers: list[str]) -> bool:
    if len(headers) != 4:
        return False
    normalized = [normalize_text(header).lower() for header in headers]
    return (
        normalized[0] in {"field", "fields", "parameter", "parameters", "param", "params"}
        and normalized[1] in {"req", "required", "require", "mandatory", "optional"}
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

def row_matches_header_semantics(headers: list[str], row: list[str]) -> bool:
    if row_matches_headers(headers, row):
        return True
    if len(headers) != len(row):
        return False

    normalized_headers = [normalize_cell_text(str(cell or '')) for cell in headers]
    normalized_row = [normalize_cell_text(str(cell or '')) for cell in row]

    if looks_like_parameter_table_headers(normalized_headers) and (
        looks_like_parameter_table_headers(normalized_row) or looks_like_semantic_headers(normalized_row)
    ):
        return True

    if looks_like_semantic_headers(normalized_headers) and (
        looks_like_parameter_table_headers(normalized_row) or looks_like_semantic_headers(normalized_row)
    ):
        return True

    return False


def build_table_id(source_page: int, snapshot_index: int) -> str:
    return f"p{source_page:04d}-t{snapshot_index:02d}"


CAPTION_PATTERN_RE = re.compile(
    r"^(?:图\s*\d|Figure\s*\d|Fig\.\s*\d|表\s*\d|Table\s*\d)", re.IGNORECASE
)


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
        image_top = float(image.bbox[1])
        image_left = float(image.bbox[0])
        pattern_candidate = None
        pattern_distance = None
        nearest_candidate = None
        nearest_distance = None
        for block in paragraph_like:
            block_top = float(block.bbox[1])
            block_bottom = float(block.bbox[3])
            block_left = float(block.bbox[0])
            if abs(block_left - image_left) > left_tolerance:
                continue
            # Check below image
            if block_top >= image_bottom:
                distance = block_top - image_bottom
            # Check above image (caption sometimes precedes the figure)
            elif block_bottom <= image_top:
                distance = image_top - block_bottom
            else:
                continue
            if distance > vertical_gap:
                continue
            is_caption_pattern = bool(CAPTION_PATTERN_RE.match(block.text.strip()))
            if is_caption_pattern and (pattern_candidate is None or distance < pattern_distance):
                pattern_candidate = block
                pattern_distance = distance
            if nearest_candidate is None or distance < nearest_distance:
                nearest_candidate = block
                nearest_distance = distance
        # Prefer blocks with figure-number patterns over plain nearest
        chosen = pattern_candidate or nearest_candidate
        if chosen is not None:
            image.caption = chosen.text
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
    body_left_margin: float = 0.0,
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
    if is_code_block(text, block, body_left_margin=body_left_margin):
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


def is_code_block(text: str, block: dict, *, body_left_margin: float = 0.0) -> bool:
    """Multi-signal code block detection.

    Scoring system:
      - Font ratio signal:     0-3 points
      - Structural signal:     0-3 points
      - Bbox indent signal:    0-2 points  (Word-exported code with visual indent)
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

    # --- Signal 3: Bbox left-indent (Word-exported code blocks) ---
    # Word code paragraphs often have a uniform left indent ≥30pt from body margin,
    # with consistent line-level left coordinates.
    bbox_score = 0
    if body_left_margin > 0 and len(lines) >= 2:
        block_left = float(block.get("bbox", (0,))[0]) if block.get("bbox") else 0.0
        indent = block_left - body_left_margin
        if indent >= 30:
            line_lefts = [
                float(ln.get("bbox", (0,))[0])
                for ln in block.get("lines", [])
                if ln.get("bbox")
            ]
            if line_lefts:
                spread = max(line_lefts) - min(line_lefts)
                if spread <= 15:
                    bbox_score = 2

    # --- Combined scoring ---
    return (font_score + structure_score + bbox_score) >= 3


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
    escaped_parts: list[str] = []
    last_index = 0
    for match in SAFE_INLINE_HTML_TAG_RE.finditer(normalized):
        part = normalized[last_index:match.start()]
        escaped_parts.append(part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        tag = match.group(0).lower()
        escaped_parts.append("<br/>" if tag.startswith("<br") else tag)
        last_index = match.end()
    escaped_parts.append(normalized[last_index:].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    escaped = "".join(escaped_parts)
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
    if previous.endswith(("</b>", "</strong>", "</s>", "</u>")):
        return False
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
    if current_token[0].islower() and current_token.lower() not in _REJOIN_STOPWORDS:
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
            and not current_token.endswith(":")
            and not CLAUSE_BREAK_RE.match(current_token)
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
            and current_token.lower() not in _REJOIN_STOPWORDS
            and ((len(prev_token) >= 3 and len(current_token) <= 3)
                 or (len(prev_token) == 1 and prev_token.isalpha())))


def should_join_with_space(previous: str, current: str) -> bool:
    if previous.endswith((":", ";", "?", "</b>", "</strong>", "</s>", "</u>")):
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
        r"(?<=[A-Za-z]) (?=(?:Format\b|For example\b|ISO\b|Allowed:|Supported Types:|MSB Limits:|SaintPay Limits:|Character limit:|Unsupported\b|Limit \d|Implied responsibility:?|Currently Supported:?|Supported:|Note:|Possible values|Must include:|SAINT_PAY:?|MSB:?))",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<=[A-Z]) (?=\d+\s+[A-Z]{2,})", "\n", text)
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
        current = emphasize_description_prefix(current)
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


def emphasize_description_prefix(line: str) -> str:
    for prefix in EMPHASIZED_DESCRIPTION_PREFIXES:
        if line == prefix:
            return f"<b>{prefix}</b>"
        if line.startswith(prefix):
            remainder = line[len(prefix):].strip()
            if not remainder:
                return f"<b>{prefix}</b>"
            return f"<b>{prefix}</b> {remainder}"
    return line


def _rejoin_split_identifiers(text: str) -> str:
    words = text.split()
    if len(words) < 2:
        return text

    i = len(words) - 2
    while i >= 0:
        left, right = words[i], words[i + 1]
        if len(left) + len(right) > 35:
            i -= 1
            continue

        joined_pair = False
        if right[0].islower() and right.lower() not in _REJOIN_STOPWORDS:
            join_pos = len(left)
            joined = left + right
            # Only inspect the immediate join neighborhood so existing
            # camelCase inside ``left`` does not force false joins such as
            # "SubKey using" -> "SubKeyusing".
            neighborhood = joined[max(0, join_pos - 3):join_pos + 3]
            if re.search(r"[a-z][A-Z]", neighborhood):
                words[i] = joined
                words.pop(i + 1)
                joined_pair = True

        if not joined_pair and right[0].isupper() and left == left.lower() and left not in _PASCAL_COMMON_WORDS and right.lower() not in _REJOIN_STOPWORDS:
            joined = left + right
            if re.search(r"[a-z][A-Z]", joined):
                words[i] = joined
                words.pop(i + 1)
                joined_pair = True

        i -= 2 if joined_pair else 1

    return " ".join(words)
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


def _compute_body_left_margin(text_blocks: list[dict], page_height: float) -> float:
    """Compute the median left margin of body text blocks (excluding headers/footers)."""
    lefts: list[float] = []
    for block in text_blocks:
        bbox = block.get("bbox", (0, 0, 0, 0))
        top = float(bbox[1]) if len(bbox) >= 2 else 0.0
        bottom = float(bbox[3]) if len(bbox) >= 4 else 0.0
        # Skip header/footer regions
        if top <= page_height * 0.08 or bottom >= page_height * 0.92:
            continue
        text = extract_block_text(block)
        if text and len(text) >= 20:
            lefts.append(float(bbox[0]))
    if not lefts:
        return 0.0
    lefts.sort()
    return lefts[len(lefts) // 2]


def _max_font_size(block: dict) -> float:
    sizes = [float(span.get("size", 0.0)) for line in block.get("lines", []) for span in line.get("spans", [])]
    return max(sizes, default=0.0)
















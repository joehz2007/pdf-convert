"""Repair engine — deterministic fixes based on audit results.

Builds a ``NormalizedDocument`` from ``content.json`` and the draft
Markdown, then applies fixes for missing blocks, tables, images,
headings, and overlap content.

Repair priority order (per spec section 7.5):
  Phase A — Completeness fixes (restore missing content)
  Phase B — Structural fixes (fix malformed structures)
  Phase C — Style normalization (merge/clean)
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .block_aligner import AlignmentResult, normalize_text, table_node_ref, image_node_ref
from .contracts import (
    AuditIssue,
    AutoFix,
    NormalizedBlock,
    NormalizedDocument,
    NormalizedPage,
    FormatTask,
)
from .coverage_auditor import AuditResult

LOGGER = logging.getLogger("md_format.repair_engine")

# Block type priority for insertion ordering
_BLOCK_TYPE_PRIORITY = {
    "heading": 0,
    "paragraph": 1,
    "list_item": 2,
    "code": 3,
    "table": 4,
    "image": 5,
}

# Terminal punctuation for paragraph merge heuristic
_TERMINAL_PUNCT = set(".!?;:。！？；：…）)」】》")

# Pipe table header pattern
_PIPE_TABLE_SEP_RE = re.compile(r"^\|\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|$")

# Heading level detection from section numbering
_HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)")
_HEADING_ALPHA_NUM_RE = re.compile(r"^[A-Za-z](\d+(?:\.\d+)*)")
_HEADING_CHAPTER_RE = re.compile(r"^第[一二三四五六七八九十百千万]+[章篇]")
_HEADING_SECTION_RE = re.compile(r"^第[一二三四五六七八九十百千万]+节")
_HEADING_APPENDIX_RE = re.compile(r"^附录")

# Broken table detection
_BROKEN_TABLE_RE = re.compile(r"[A-Za-z]{2,}<br>[A-Za-z]{1,}")

# Common words that should NOT be joined with a following capitalized word
_COMMON_WORDS = frozenset({
    "a", "an", "the", "this", "that", "these", "those",
    "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "can", "could",
    "not", "no", "or", "and", "but", "if", "of", "at", "by",
    "for", "in", "on", "to", "with", "from", "as",
    "all", "each", "every", "any", "some", "its", "per",
})

# Code line detection
_CODE_STMT_RE = re.compile(
    r"(?:"
    r"[;{}]\s*$"                       # ends with ; or { or }
    r"|^\s*[{}]\s*$"                   # line is just a brace
    r"|\w+\.\w+\("                     # method call: obj.method(
    r"|\w+\([^)]*[,)]"                # function call with args
    r"|^\s*(?:public|private|protected|static|final|void|class|interface|def|function|const|let|var|import|from|return|try|catch|throw|new|if|else|for|while|switch|case)\b"
    r"|^\s*(?:byte|int|long|String|boolean|char|double|float)\s*[\[\]]*\s+\w"
    r"|^\s*@\w+"                       # annotations
    r"|^\s*//|/\*|\*/"                 # comments
    r"|=\s*(?:new|null|true|false|\"|\d)"  # assignments
    r"|^\s*\*\s+@"                     # javadoc params
    r")"
)


def repair(
    task: FormatTask,
    content_data: dict[str, Any],
    draft_markdown: str,
    audit_result: AuditResult,
    alignment: AlignmentResult,
) -> tuple[NormalizedDocument, list[AutoFix]]:
    """Build a NormalizedDocument with repairs applied.

    Returns (NormalizedDocument, list[AutoFix]).
    """
    auto_fixes: list[AutoFix] = []

    # Build heading level map from draft markdown for cross-reference
    draft_heading_levels = _build_heading_level_map(draft_markdown)

    # Build page-level structure from content.json
    pages: list[NormalizedPage] = []
    for page_data in content_data.get("source_pages", []):
        source_page = page_data.get("source_page", 0)
        slice_page = page_data.get("slice_page", 0)
        is_overlap = page_data.get("is_overlap", False)

        blocks: list[NormalizedBlock] = []

        # Add text blocks
        for block in page_data.get("blocks", []):
            block_type = block.get("type", "paragraph")
            text = block.get("text", "")
            reading_order = block.get("reading_order", 0)
            dedupe_key = block.get("dedupe_key", "")
            block_is_overlap = block.get("is_overlap", False)

            heading_level = None
            if block_type == "heading":
                # Priority: content.json > draft markdown > section numbering
                heading_level = block.get("heading_level")
                if not heading_level:
                    norm = normalize_text(text)
                    heading_level = draft_heading_levels.get(norm)
                if not heading_level:
                    heading_level = _detect_heading_level_from_text(text)

            md = _block_to_markdown(block_type, text, heading_level=heading_level)
            blocks.append(NormalizedBlock(
                block_type=block_type,
                source_page=source_page,
                reading_order=reading_order,
                node_ref=dedupe_key,
                markdown=md,
                is_overlap=block_is_overlap or is_overlap,
            ))

        # Add tables
        for idx, table in enumerate(page_data.get("tables", [])):
            node_ref = table_node_ref(source_page, idx)
            reading_order = _table_reading_order(table, page_data)
            table_md = _table_to_markdown(table, node_ref, auto_fixes, source_page)
            blocks.append(NormalizedBlock(
                block_type="table",
                source_page=source_page,
                reading_order=reading_order,
                node_ref=node_ref,
                markdown=table_md,
                is_overlap=is_overlap,
            ))

        # Add images
        for idx, image in enumerate(page_data.get("images", [])):
            node_ref = image_node_ref(source_page, idx)
            reading_order = _image_reading_order(image, page_data)
            image_md = _image_to_markdown(image, node_ref, auto_fixes, source_page)
            blocks.append(NormalizedBlock(
                block_type="image",
                source_page=source_page,
                reading_order=reading_order,
                node_ref=node_ref,
                markdown=image_md,
                is_overlap=is_overlap,
            ))

        # Sort blocks by reading_order
        blocks.sort(key=lambda b: (b.reading_order, _BLOCK_TYPE_PRIORITY.get(b.block_type, 99)))

        pages.append(NormalizedPage(
            source_page=source_page,
            slice_page=slice_page,
            is_overlap=is_overlap,
            blocks=blocks,
        ))

    # Sort pages by source_page
    pages.sort(key=lambda p: p.source_page)

    # Determine phase3 manual review
    has_errors = any(i.severity == "error" for i in audit_result.issues)
    phase3_manual_review = has_errors

    doc = NormalizedDocument(
        slice_file=task.slice_file,
        display_title=task.display_title,
        order_index=task.order_index,
        start_page=task.start_page,
        end_page=task.end_page,
        pages=pages,
        warnings=[i.message for i in audit_result.issues if i.severity == "warning"],
        phase2_manual_review_required=task.phase2_manual_review_required,
        phase3_manual_review_required=phase3_manual_review,
        metadata={
            "content_file": str(task.content_file),
            "draft_md_file": str(task.draft_md_file),
        },
    )

    # Pre-repair: recover code blocks from draft markdown + merge code-like paragraphs
    _recover_code_blocks_from_draft(doc, draft_markdown, auto_fixes)
    _merge_code_line_paragraphs(doc, auto_fixes)

    # Phase A: Completeness fixes
    _fix_missing_top_heading(doc, auto_fixes)
    _fix_missing_blocks(doc, audit_result, auto_fixes)
    _fix_overlap_blocks(doc, audit_result, auto_fixes)
    _fix_missing_images(doc, audit_result, auto_fixes)

    # Phase B: Structural fixes
    _fix_unclosed_code_fences(doc, auto_fixes)
    _fix_broken_lists(doc, auto_fixes)
    _fix_table_separators(doc, auto_fixes)
    _fix_image_captions(doc, content_data, auto_fixes)

    # Phase C: Style normalization
    _fix_heading_levels(doc, auto_fixes)
    _fix_broken_paragraphs(doc, auto_fixes)

    return doc, auto_fixes


def _block_to_markdown(block_type: str, text: str, heading_level: int | None = None) -> str:
    """Convert a content.json block to Markdown."""
    if not text:
        return ""
    if block_type == "heading":
        level = heading_level if heading_level and 1 <= heading_level <= 6 else 2
        prefix = "#" * level
        return f"{prefix} {text}"
    if block_type == "list_item":
        return f"- {text}"
    if block_type == "code":
        return f"```\n{text}\n```"
    # paragraph or other
    return text


def _table_to_markdown(
    table: dict,
    node_ref: str,
    auto_fixes: list[AutoFix],
    source_page: int,
) -> str:
    """Convert a table node to Markdown, with fallback chain."""
    # Try structured markdown first — but validate and repair it
    md = table.get("markdown", "")
    if md and md.strip() and not _is_corrupted_table_markdown(md):
        return _repair_table_markdown(md).strip()

    headers = table.get("headers", [])
    rows = table.get("rows", [])

    # If markdown was corrupted and image fallback exists, prefer image
    if md and _is_corrupted_table_markdown(md):
        fallback_image = table.get("fallback_image", "")
        if fallback_image:
            auto_fixes.append(AutoFix(
                fix_type="table_fallback_image_applied",
                source_page=source_page,
                node_ref=node_ref,
                message=f"Table markdown corrupted, using image fallback: {fallback_image}",
            ))
            return f"![Table]({fallback_image})"

    # Try rebuilding from headers + rows
    if headers:
        rebuilt = _rebuild_pipe_table(headers, rows)
        if rebuilt:
            auto_fixes.append(AutoFix(
                fix_type="table_rebuilt",
                source_page=source_page,
                node_ref=node_ref,
                message=f"Table rebuilt from structured data. Headers: {headers[:4]}",
            ))
            return rebuilt

    # Fallback to HTML
    fallback_html = table.get("fallback_html", "")
    if fallback_html and fallback_html.strip():
        auto_fixes.append(AutoFix(
            fix_type="table_fallback_html_applied",
            source_page=source_page,
            node_ref=node_ref,
            message="Table rendered as HTML fallback.",
        ))
        return fallback_html.strip()

    # Fallback to image
    fallback_image = table.get("fallback_image", "")
    if fallback_image:
        auto_fixes.append(AutoFix(
            fix_type="table_fallback_image_applied",
            source_page=source_page,
            node_ref=node_ref,
            message=f"Table rendered as image fallback: {fallback_image}",
        ))
        return f"![Table]({fallback_image})"

    # Nothing available — return empty placeholder
    return f"<!-- table {node_ref}: no content available -->"


def _rebuild_pipe_table(headers: list, rows: list[list]) -> str:
    """Rebuild a GFM pipe table from headers and rows."""
    if not headers:
        return ""

    col_count = len(headers)
    lines = []

    # Header row
    header_cells = [_sanitize_pipe_cell(h) for h in headers]
    lines.append("| " + " | ".join(header_cells) + " |")

    # Separator row
    lines.append("| " + " | ".join(["---"] * col_count) + " |")

    # Data rows
    for row in rows:
        cells = []
        for i in range(col_count):
            cell = _sanitize_pipe_cell(row[i]) if i < len(row) else ""
            cells.append(cell)
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def _image_to_markdown(
    image: dict,
    node_ref: str,
    auto_fixes: list[AutoFix],
    source_page: int,
) -> str:
    """Convert an image node to Markdown."""
    asset_path = image.get("asset_path", "")
    caption = image.get("caption", "")
    alt_text = caption or "image"

    if not asset_path:
        return f"<!-- image {node_ref}: no asset path -->"

    return f"![{alt_text}]({asset_path})"


def _table_reading_order(table: dict, page_data: dict) -> int:
    """Derive reading order for a table within a page."""
    # Use bbox y-coordinate as proxy for reading order
    bbox = table.get("bbox", [])
    if bbox and len(bbox) >= 2:
        return int(bbox[1])
    # Fallback: after all blocks
    blocks = page_data.get("blocks", [])
    max_ro = max((b.get("reading_order", 0) for b in blocks), default=0) if blocks else 0
    return max_ro + 1


def _image_reading_order(image: dict, page_data: dict) -> int:
    """Derive reading order for an image within a page."""
    bbox = image.get("bbox", [])
    if bbox and len(bbox) >= 2:
        return int(bbox[1])
    blocks = page_data.get("blocks", [])
    max_ro = max((b.get("reading_order", 0) for b in blocks), default=0) if blocks else 0
    tables = page_data.get("tables", [])
    return max_ro + len(tables) + 1


def _fix_missing_top_heading(doc: NormalizedDocument, auto_fixes: list[AutoFix]) -> None:
    """Insert ``# {display_title}`` if no H1 heading exists."""
    if not doc.display_title or not doc.pages:
        return

    for page in doc.pages:
        for block in page.blocks:
            if block.block_type == "heading" and block.markdown.startswith("# ") and not block.markdown.startswith("## "):
                return  # H1 already present

    # Try to promote an existing heading that matches display_title
    title_norm = normalize_text(doc.display_title)
    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "heading":
                continue
            heading_text = re.sub(r"^#{1,6}\s+", "", block.markdown)
            if normalize_text(heading_text) == title_norm:
                block.markdown = f"# {heading_text}"
                block.repaired = True
                block.repair_actions.append("heading_inserted")
                auto_fixes.append(AutoFix(
                    fix_type="heading_inserted",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message=f"Promoted matching heading to H1: # {heading_text}",
                ))
                LOGGER.debug("Promoted existing heading to H1: %s", heading_text)
                return

    # No matching heading found — insert new H1
    target_page = doc.pages[0]
    for page in doc.pages:
        if not page.is_overlap:
            target_page = page
            break

    min_ro = min((b.reading_order for b in target_page.blocks), default=1) - 1
    heading_block = NormalizedBlock(
        block_type="heading",
        source_page=target_page.source_page,
        reading_order=min_ro,
        node_ref=None,
        markdown=f"# {doc.display_title}",
        is_overlap=False,
        repaired=True,
        repair_actions=["heading_inserted"],
    )
    target_page.blocks.insert(0, heading_block)
    auto_fixes.append(AutoFix(
        fix_type="heading_inserted",
        source_page=target_page.source_page,
        node_ref=None,
        message=f"Inserted missing top-level heading: # {doc.display_title}",
    ))
    LOGGER.debug("Inserted missing H1: %s", doc.display_title)


def _fix_missing_blocks(doc: NormalizedDocument, audit_result: AuditResult, auto_fixes: list[AutoFix]) -> None:
    """Mark blocks restored from content.json that were missing in draft."""
    missing_refs = {
        i.node_ref for i in audit_result.issues
        if i.issue_type == "missing_block" and i.auto_fixable and i.node_ref
    }
    if not missing_refs:
        return

    for page in doc.pages:
        for block in page.blocks:
            if block.node_ref in missing_refs and block.markdown:
                block.repaired = True
                block.repair_actions.append("missing_block_restored")
                missing_refs.discard(block.node_ref)
                auto_fixes.append(AutoFix(
                    fix_type="missing_block_restored",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message=f"Block restored from content.json (type={block.block_type})",
                ))


def _fix_overlap_blocks(doc: NormalizedDocument, audit_result: AuditResult, auto_fixes: list[AutoFix]) -> None:
    """Mark overlap page blocks as restored when they were missing in draft."""
    overlap_issues = [
        i for i in audit_result.issues
        if i.issue_type == "overlap_lost" and i.auto_fixable
    ]
    if not overlap_issues:
        return

    affected_pages = {i.source_page for i in overlap_issues}
    for page in doc.pages:
        if page.source_page not in affected_pages:
            continue
        if not page.blocks:
            continue
        for block in page.blocks:
            if block.markdown:
                block.repaired = True
                block.repair_actions.append("overlap_block_restored")
        auto_fixes.append(AutoFix(
            fix_type="overlap_block_restored",
            source_page=page.source_page,
            node_ref=None,
            message=f"Overlap page {page.source_page} blocks restored from content.json",
        ))
        affected_pages.discard(page.source_page)


def _fix_missing_images(doc: NormalizedDocument, audit_result: AuditResult, auto_fixes: list[AutoFix]) -> None:
    """Mark image blocks restored from content.json that were missing in draft."""
    missing_refs = {
        i.node_ref for i in audit_result.issues
        if i.issue_type == "image_reference_missing" and i.auto_fixable and i.node_ref
    }
    if not missing_refs:
        return

    for page in doc.pages:
        for block in page.blocks:
            if block.block_type == "image" and block.node_ref in missing_refs and "<!--" not in block.markdown:
                block.repaired = True
                block.repair_actions.append("image_reference_restored")
                missing_refs.discard(block.node_ref)
                auto_fixes.append(AutoFix(
                    fix_type="image_reference_restored",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message=f"Image reference restored from content.json",
                ))


def _fix_unclosed_code_fences(doc: NormalizedDocument, auto_fixes: list[AutoFix]) -> None:
    """Close unclosed code fences in code blocks."""
    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "code" or not block.markdown:
                continue
            fence_count = sum(1 for line in block.markdown.splitlines() if line.strip().startswith("```"))
            if fence_count % 2 != 0:
                block.markdown = block.markdown.rstrip() + "\n```"
                block.repaired = True
                block.repair_actions.append("code_fence_closed")
                auto_fixes.append(AutoFix(
                    fix_type="code_fence_closed",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message="Closed unclosed code fence",
                ))


def _fix_broken_lists(doc: NormalizedDocument, auto_fixes: list[AutoFix]) -> None:
    """Ensure list_item blocks have proper ``- `` prefix."""
    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "list_item" or not block.markdown:
                continue
            md = block.markdown
            if not md.startswith("- ") and not md.startswith("* ") and not re.match(r"^\d+\.\s", md):
                block.markdown = f"- {md}"
                block.repaired = True
                block.repair_actions.append("list_rebuilt")
                auto_fixes.append(AutoFix(
                    fix_type="list_rebuilt",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message="List item prefix restored",
                ))


def _fix_table_separators(doc: NormalizedDocument, auto_fixes: list[AutoFix]) -> None:
    """Insert missing GFM separator row in pipe tables."""
    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "table" or not block.markdown:
                continue
            # Skip HTML tables
            md = block.markdown.strip()
            if md.startswith("<"):
                continue
            lines = md.splitlines()
            if len(lines) < 2:
                continue
            # Check: first line is a pipe row, second is NOT a separator
            if "|" not in lines[0]:
                continue
            if _PIPE_TABLE_SEP_RE.match(lines[1].strip()):
                continue
            # Insert separator row
            col_count = lines[0].count("|") - 1
            if col_count < 1:
                col_count = 1
            separator = "| " + " | ".join(["---"] * col_count) + " |"
            lines.insert(1, separator)
            block.markdown = "\n".join(lines)
            block.repaired = True
            block.repair_actions.append("table_separator_inserted")
            auto_fixes.append(AutoFix(
                fix_type="table_separator_inserted",
                source_page=block.source_page,
                node_ref=block.node_ref,
                message="Inserted missing GFM table separator row",
            ))


def _fix_image_captions(doc: NormalizedDocument, content_data: dict[str, Any], auto_fixes: list[AutoFix]) -> None:
    """Fill default ``![image]`` alt text with caption from content.json."""
    # Build caption lookup
    caption_map: dict[str, str] = {}
    for page_data in content_data.get("source_pages", []):
        source_page = page_data.get("source_page", 0)
        for idx, image in enumerate(page_data.get("images", [])):
            caption = image.get("caption", "")
            if caption:
                ref = image_node_ref(source_page, idx)
                caption_map[ref] = caption

    if not caption_map:
        return

    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "image" or not block.node_ref:
                continue
            caption = caption_map.get(block.node_ref, "")
            if not caption:
                continue
            # Only replace if using default alt text
            if "![image](" in block.markdown:
                block.markdown = block.markdown.replace("![image](", f"![{caption}](", 1)
                block.repaired = True
                block.repair_actions.append("image_caption_filled")
                auto_fixes.append(AutoFix(
                    fix_type="image_caption_filled",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message=f"Image caption filled: {caption}",
                ))


def _fix_heading_levels(doc: NormalizedDocument, auto_fixes: list[AutoFix]) -> None:
    """Ensure heading levels don't jump more than 1 level."""
    prev_level = 0
    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "heading":
                continue
            match = re.match(r"^(#{1,6})\s", block.markdown)
            if not match:
                continue
            current_level = len(match.group(1))
            if prev_level > 0 and current_level > prev_level + 1:
                new_level = prev_level + 1
                new_prefix = "#" * new_level
                block.markdown = re.sub(r"^#{1,6}", new_prefix, block.markdown)
                block.repaired = True
                block.repair_actions.append("heading_normalized")
                auto_fixes.append(AutoFix(
                    fix_type="heading_normalized",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message=f"Heading level adjusted from h{current_level} to h{new_level}",
                ))
                current_level = new_level
            prev_level = current_level


def _fix_broken_paragraphs(doc: NormalizedDocument, auto_fixes: list[AutoFix]) -> None:
    """Merge consecutive paragraph blocks that appear to be mid-sentence breaks."""
    for page in doc.pages:
        i = 0
        while i < len(page.blocks) - 1:
            current = page.blocks[i]
            nxt = page.blocks[i + 1]
            if (
                current.block_type == "paragraph"
                and nxt.block_type == "paragraph"
                and current.markdown
                and nxt.markdown
                and not current.markdown[-1] in _TERMINAL_PUNCT
                and (nxt.markdown[0].islower() or nxt.markdown[0] in "，、")
            ):
                current.markdown = current.markdown.rstrip() + " " + nxt.markdown.lstrip()
                nxt.markdown = ""
                current.repaired = True
                current.repair_actions.append("paragraph_merged")
                auto_fixes.append(AutoFix(
                    fix_type="paragraph_merged",
                    source_page=current.source_page,
                    node_ref=current.node_ref,
                    message="Merged broken paragraph continuation",
                ))
            i += 1


# ---------------------------------------------------------------------------
# Heading level helpers
# ---------------------------------------------------------------------------


def _build_heading_level_map(draft_markdown: str) -> dict[str, int]:
    """Extract heading levels from draft markdown, keyed by normalized text."""
    level_map: dict[str, int] = {}
    for line in draft_markdown.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)", line.strip())
        if m:
            level = len(m.group(1))
            text = m.group(2).strip()
            norm = normalize_text(text)
            if norm:
                level_map[norm] = level
    return level_map


def _detect_heading_level_from_text(text: str) -> int:
    """Infer heading level from section numbering patterns in the text."""
    stripped = text.strip()

    if _HEADING_CHAPTER_RE.match(stripped) or _HEADING_APPENDIX_RE.match(stripped):
        return 1
    if _HEADING_SECTION_RE.match(stripped):
        return 2

    m = _HEADING_NUM_RE.match(stripped)
    if m:
        return min(m.group(1).count(".") + 1, 6)

    m = _HEADING_ALPHA_NUM_RE.match(stripped)
    if m:
        return min(m.group(1).count(".") + 1, 6)

    return 2  # safe default


# ---------------------------------------------------------------------------
# Code block recovery from draft markdown
# ---------------------------------------------------------------------------


def _recover_code_blocks_from_draft(
    doc: NormalizedDocument,
    draft_markdown: str,
    auto_fixes: list[AutoFix],
) -> None:
    """Reclassify paragraph blocks as code when they match draft markdown fences."""
    code_texts = _extract_draft_code_texts(draft_markdown)
    if not code_texts:
        return

    normalized_codes = [normalize_text(ct) for ct in code_texts if ct.strip()]
    if not normalized_codes:
        return

    for page in doc.pages:
        for block in page.blocks:
            if block.block_type != "paragraph" or not block.markdown:
                continue
            block_norm = normalize_text(block.markdown)
            if len(block_norm) < 8:
                continue
            for code_norm in normalized_codes:
                if not code_norm:
                    continue
                if block_norm in code_norm:
                    block.block_type = "code"
                    block.markdown = f"```\n{block.markdown}\n```"
                    block.repaired = True
                    block.repair_actions.append("code_block_rebuilt")
                    auto_fixes.append(AutoFix(
                        fix_type="code_block_rebuilt",
                        source_page=block.source_page,
                        node_ref=block.node_ref,
                        message="Paragraph reclassified as code block (matched draft fence)",
                    ))
                    break


def _extract_draft_code_texts(draft_markdown: str) -> list[str]:
    """Extract text content from fenced code blocks in draft markdown."""
    results: list[str] = []
    lines = draft_markdown.splitlines()
    in_fence = False
    fence_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                results.append("\n".join(fence_lines))
                fence_lines = []
                in_fence = False
            else:
                in_fence = True
                fence_lines = []
        elif in_fence:
            fence_lines.append(line)
    if in_fence and fence_lines:
        results.append("\n".join(fence_lines))
    return results


# ---------------------------------------------------------------------------
# Consecutive code paragraph merging
# ---------------------------------------------------------------------------


def _merge_code_line_paragraphs(
    doc: NormalizedDocument,
    auto_fixes: list[AutoFix],
) -> None:
    """Merge sequences of single-line paragraph blocks that form source code.

    When Phase 2 extracts code from a PDF, each line of code often becomes
    a separate paragraph block.  This pass detects sequences of 3+ consecutive
    code-like paragraphs and merges them into a single fenced code block.
    """
    for page in doc.pages:
        i = 0
        while i < len(page.blocks):
            block = page.blocks[i]
            if block.block_type != "paragraph" or not block.markdown:
                i += 1
                continue
            if not _is_code_like(block.markdown):
                i += 1
                continue

            # Scan forward — collect consecutive code-like paragraphs,
            # stopping at non-paragraph or non-code-like blocks.
            j = i + 1
            while j < len(page.blocks):
                nxt = page.blocks[j]
                if nxt.block_type != "paragraph" or not nxt.markdown:
                    break
                if not _is_code_like(nxt.markdown):
                    break
                j += 1

            count = j - i
            if count >= 3:
                code_lines = [page.blocks[k].markdown for k in range(i, j)]
                block.block_type = "code"
                block.markdown = "```\n" + "\n".join(code_lines) + "\n```"
                block.repaired = True
                block.repair_actions.append("code_block_rebuilt")
                for k in range(i + 1, j):
                    page.blocks[k].markdown = ""
                auto_fixes.append(AutoFix(
                    fix_type="code_block_rebuilt",
                    source_page=block.source_page,
                    node_ref=block.node_ref,
                    message=f"Merged {count} code-like paragraphs into code block",
                ))
                i = j
            else:
                i += 1


def _is_code_like(text: str) -> bool:
    """Check if a single paragraph looks like a line of source code."""
    stripped = text.strip()
    if not stripped or len(stripped) > 200:
        return False
    # Must have some alpha characters (not just punctuation / numbers)
    if not re.search(r"[a-zA-Z]", stripped):
        return False
    return bool(_CODE_STMT_RE.search(stripped))


# ---------------------------------------------------------------------------
# Table quality helpers
# ---------------------------------------------------------------------------


def _repair_table_markdown(md: str) -> str:
    """Repair split identifiers within pipe table cells."""
    lines = md.strip().splitlines()
    repaired: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            repaired.append(line)
            continue
        # Skip separator rows
        if _PIPE_TABLE_SEP_RE.match(stripped):
            repaired.append(line)
            continue
        # Split into cells and repair each
        parts = stripped.split("|")
        fixed = [_rejoin_split_identifiers(p.strip()) for p in parts]
        repaired.append("| " + " | ".join(c for c in fixed[1:-1]) + " |")
    return "\n".join(repaired)


def _is_corrupted_table_markdown(md: str) -> bool:
    """Check if table markdown has broken word fragments."""
    if _BROKEN_TABLE_RE.search(md):
        return True
    lines = md.strip().splitlines()
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        short_fragments = [c for c in cells if 0 < len(c) <= 2 and c[0].isalpha()]
        if len(short_fragments) >= 2:
            return True
    return False


def _rejoin_split_identifiers(text: str) -> str:
    """Rejoin camelCase/PascalCase identifiers split by PDF line wrapping.

    Handles two patterns:
      "cryptoAd dressInfo"  → "cryptoAddressInfo"  (lowercase continuation)
      "complete Time"       → "completeTime"       (PascalCase continuation)
    """
    words = text.split()
    if len(words) != 2:
        return text
    left, right = words
    if len(left) + len(right) > 35:
        return text

    # Case 1: right starts lowercase (e.g. "cryptoAd" + "dressInfo")
    if right[0].islower():
        joined = left + right
        if re.search(r"[a-z][A-Z]", joined):
            return joined

    # Case 2: right starts uppercase, left all lowercase (e.g. "complete" + "Time")
    if right[0].isupper() and left == left.lower() and left not in _COMMON_WORDS:
        joined = left + right
        if re.search(r"[a-z][A-Z]", joined):
            return joined

    return text


def _sanitize_pipe_cell(value: object) -> str:
    """Sanitize a value for inclusion in a GFM pipe table cell."""
    text = str(value) if value is not None else ""
    text = _rejoin_split_identifiers(text)
    text = text.replace("|", "\\|")
    text = text.replace("\r\n", "<br>").replace("\n", "<br>")
    return text.strip()

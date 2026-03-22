"""Repair engine — deterministic fixes based on audit results.

Builds a ``NormalizedDocument`` from ``content.json`` and the draft
Markdown, then applies fixes for missing blocks, tables, images,
headings, and overlap content.
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

            md = _block_to_markdown(block_type, text)
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

    # Apply heading fixes
    _fix_heading_levels(doc, auto_fixes)

    return doc, auto_fixes


def _block_to_markdown(block_type: str, text: str) -> str:
    """Convert a content.json block to Markdown."""
    if not text:
        return ""
    if block_type == "heading":
        # Default to ## for headings from content blocks
        return f"## {text}"
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
    # Try structured markdown first
    md = table.get("markdown", "")
    if md and md.strip():
        return md.strip()

    # Try rebuilding from headers + rows
    headers = table.get("headers", [])
    rows = table.get("rows", [])
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
    header_cells = [str(h).replace("|", "\\|") for h in headers]
    lines.append("| " + " | ".join(header_cells) + " |")

    # Separator row
    lines.append("| " + " | ".join(["---"] * col_count) + " |")

    # Data rows
    for row in rows:
        cells = []
        for i in range(col_count):
            cell = str(row[i]).replace("|", "\\|") if i < len(row) else ""
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

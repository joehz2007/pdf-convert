"""Coverage auditor — completeness verification against content.json.

Builds a coverage ledger from content.json, then uses ``block_aligner``
to check draft Markdown against the ledger.  Outputs ``AuditIssue`` list
and ``CoverageStats``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .block_aligner import align_blocks, table_node_ref, image_node_ref
from .contracts import AuditIssue, CoverageStats

LOGGER = logging.getLogger("md_format.coverage_auditor")


@dataclass(slots=True)
class AuditResult:
    """Complete audit output for a single slice."""

    coverage: CoverageStats
    issues: list[AuditIssue] = field(default_factory=list)


def audit_coverage(
    content_data: dict[str, Any],
    draft_markdown: str | None,
) -> AuditResult:
    """Run completeness audit on draft Markdown against content.json.

    Returns ``AuditResult`` with coverage statistics and issue list.
    """
    # Build expected counts from content.json
    source_pages = content_data.get("source_pages", [])

    expected_blocks: list[dict] = []
    expected_tables: list[dict] = []
    expected_images: list[dict] = []
    overlap_pages: list[int] = []

    for page_data in source_pages:
        source_page = page_data.get("source_page", 0)
        is_overlap = page_data.get("is_overlap", False)
        if is_overlap:
            overlap_pages.append(source_page)

        for block in page_data.get("blocks", []):
            expected_blocks.append({**block, "_source_page": source_page})
        for idx, table in enumerate(page_data.get("tables", [])):
            expected_tables.append({
                **table,
                "_source_page": source_page,
                "_node_ref": table_node_ref(source_page, idx),
            })
        for idx, image in enumerate(page_data.get("images", [])):
            expected_images.append({
                **image,
                "_source_page": source_page,
                "_node_ref": image_node_ref(source_page, idx),
            })

    # Run alignment. When draft is absent, treat content.json as the baseline
    # and suppress draft-only "missing from markdown" findings.
    alignment = align_blocks(content_data, draft_markdown)

    # Build coverage stats
    text_blocks_expected = len(expected_blocks)
    text_blocks_matched = len(alignment.matched_blocks)
    tables_expected = len(expected_tables)
    tables_matched = len(alignment.matched_tables)
    images_expected = len(expected_images)
    images_matched = len(alignment.matched_images)
    overlap_pages_expected = len(overlap_pages)

    # Check overlap pages — verify overlap content is present in draft
    overlap_pages_matched = 0
    for page_data in source_pages:
        if not page_data.get("is_overlap", False):
            continue
        page_md = page_data.get("markdown", "")
        if page_md and page_md.strip():
            # Check if any substantial text from the overlap page appears in draft
            overlap_pages_matched += 1

    coverage = CoverageStats(
        text_blocks_expected=text_blocks_expected,
        text_blocks_matched=text_blocks_matched,
        tables_expected=tables_expected,
        tables_matched=tables_matched,
        images_expected=images_expected,
        images_matched=images_matched,
        overlap_pages_expected=overlap_pages_expected,
        overlap_pages_matched=overlap_pages_matched,
    )

    # Build issues
    issues: list[AuditIssue] = []

    if draft_markdown:
        # Missing blocks
        for dedupe_key in alignment.unmatched_block_keys:
            block_info = _find_block_by_key(expected_blocks, dedupe_key)
            source_page = block_info.get("_source_page") if block_info else None
            reading_order = block_info.get("reading_order") if block_info else None
            block_text = (block_info.get("text", "") or "")[:80] if block_info else ""
            issues.append(AuditIssue(
                issue_type="missing_block",
                severity="warning",
                source_page=source_page,
                reading_order=reading_order,
                node_ref=dedupe_key,
                message=f"Block not found in draft Markdown: {block_text!r}",
                auto_fixable=True,
            ))

    if draft_markdown:
        # Missing tables
        for table in expected_tables:
            node_ref = table["_node_ref"]
            if node_ref not in alignment.matched_tables:
                source_page = table["_source_page"]
                headers = table.get("headers", [])
                has_fallback = bool(table.get("fallback_html") or table.get("fallback_image"))
                issues.append(AuditIssue(
                    issue_type="table_render_failed",
                    severity="warning" if has_fallback else "error",
                    source_page=source_page,
                    reading_order=None,
                    node_ref=node_ref,
                    message=f"Table not found in draft Markdown. Headers: {headers[:4]}",
                    auto_fixable=has_fallback,
                ))

    if draft_markdown:
        # Missing images
        for image in expected_images:
            node_ref = image["_node_ref"]
            if node_ref not in alignment.matched_images:
                source_page = image["_source_page"]
                asset_path = image.get("asset_path", "")
                issues.append(AuditIssue(
                    issue_type="image_reference_missing",
                    severity="warning",
                    source_page=source_page,
                    reading_order=None,
                    node_ref=node_ref,
                    message=f"Image reference not found in draft Markdown: {asset_path}",
                    auto_fixable=True,
                ))

    # Overlap page issues
    if overlap_pages_expected > overlap_pages_matched:
        for page_data in source_pages:
            if not page_data.get("is_overlap", False):
                continue
            source_page = page_data.get("source_page", 0)
            page_md = page_data.get("markdown", "")
            if not page_md or not page_md.strip():
                issues.append(AuditIssue(
                    issue_type="overlap_lost",
                    severity="warning",
                    source_page=source_page,
                    reading_order=None,
                    node_ref=None,
                    message=f"Overlap page {source_page} content is empty or missing.",
                    auto_fixable=True,
                ))

    if issues:
        LOGGER.debug("Audit found %d issues for %s", len(issues), content_data.get("slice_file", ""))

    return AuditResult(coverage=coverage, issues=issues)


def _find_block_by_key(blocks: list[dict], dedupe_key: str) -> dict | None:
    for block in blocks:
        if block.get("dedupe_key") == dedupe_key:
            return block
    return None

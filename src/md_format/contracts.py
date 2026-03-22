from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

JsonDict = dict[str, Any]

# ---------------------------------------------------------------------------
# Status / severity / issue_type enums
# ---------------------------------------------------------------------------

Status = Literal["success", "failed", "skipped_upstream_failed"]

Severity = Literal["error", "warning", "info"]

IssueType = Literal[
    "missing_block",
    "duplicate_block",
    "heading_level_invalid",
    "list_broken",
    "code_fence_unclosed",
    "table_render_failed",
    "image_reference_missing",
    "overlap_lost",
    "asset_not_found",
    "format_parse_unstable",
]

FixType = Literal[
    "heading_normalized",
    "heading_inserted",
    "paragraph_merged",
    "missing_block_restored",
    "list_rebuilt",
    "code_fence_closed",
    "code_block_rebuilt",
    "table_separator_inserted",
    "table_rebuilt",
    "table_fallback_html_applied",
    "table_fallback_image_applied",
    "image_reference_restored",
    "image_caption_filled",
    "overlap_block_restored",
]

AssetMode = Literal["copy", "reuse_phase2"]


# ---------------------------------------------------------------------------
# Task model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FormatTask:
    slice_file: str
    display_title: str
    order_index: int
    input_dir: Path
    content_file: Path
    draft_md_file: Path
    assets_dir: Path
    phase2_manual_review_required: bool
    start_page: int = 0
    end_page: int = 0


# ---------------------------------------------------------------------------
# Audit model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AuditIssue:
    issue_type: str
    severity: str
    source_page: int | None
    reading_order: int | None
    node_ref: str | None
    message: str
    auto_fixable: bool


# ---------------------------------------------------------------------------
# Normalized intermediate representation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class NormalizedBlock:
    block_type: str
    source_page: int
    reading_order: int
    node_ref: str | None
    markdown: str
    is_overlap: bool
    repaired: bool = False
    repair_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedPage:
    source_page: int
    slice_page: int
    is_overlap: bool
    blocks: list[NormalizedBlock] = field(default_factory=list)


@dataclass(slots=True)
class NormalizedDocument:
    slice_file: str
    display_title: str
    order_index: int
    start_page: int
    end_page: int
    pages: list[NormalizedPage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    phase2_manual_review_required: bool = False
    phase3_manual_review_required: bool = False
    metadata: JsonDict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Auto-fix record
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AutoFix:
    fix_type: str
    source_page: int | None
    node_ref: str | None
    message: str


# ---------------------------------------------------------------------------
# Coverage stats
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CoverageStats:
    text_blocks_expected: int = 0
    text_blocks_matched: int = 0
    tables_expected: int = 0
    tables_matched: int = 0
    images_expected: int = 0
    images_matched: int = 0
    overlap_pages_expected: int = 0
    overlap_pages_matched: int = 0


# ---------------------------------------------------------------------------
# Review report
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReviewReport:
    slice_file: str
    final_md_file: str
    created_at: str
    status: str
    manual_review_required: bool
    coverage: CoverageStats = field(default_factory=CoverageStats)
    formatted_stats: JsonDict = field(default_factory=dict)
    issues: list[AuditIssue] = field(default_factory=list)
    auto_fixes: list[AutoFix] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-slice result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FormatResult:
    slice_file: str
    final_md_file: str | None
    review_report_file: str | None
    status: str
    warning_count: int
    issue_count: int
    auto_fixed_count: int
    manual_review_required: bool
    elapsed_ms: int
    display_title: str = ""
    order_index: int = 0
    start_page: int = 0
    end_page: int = 0
    formatted_char_count: int = 0
    formatted_block_count: int = 0
    asset_mode: str = "copy"
    error_code: str | None = None
    error_message: str | None = None
    stage_timings: JsonDict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Global manifest
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class FormatManifest:
    source_extract_manifest: str
    source_file: str
    created_at: str
    generator_version: str
    total_slices: int
    success_count: int
    failed_count: int
    manual_review_count: int
    total_issue_count: int
    total_auto_fixed_count: int
    total_elapsed_ms: int
    slices: list[FormatResult]
    timings: JsonDict = field(default_factory=dict)

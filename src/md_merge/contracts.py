from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

JsonDict = dict[str, Any]

# ---------------------------------------------------------------------------
# Enum-like Literals
# ---------------------------------------------------------------------------

MergeStatus = Literal["success", "failed", "aborted_upstream_invalid"]

MatchStrategy = Literal["dedupe_key", "source_page_text_hash", "asset_ref", "none"]

RemovedFrom = Literal["left_tail", "right_head", "none"]

WarningType = Literal[
    "overlap_match_unstable",
    "overlap_no_provenance",
    "asset_copy_failed",
    "asset_path_missing",
    "page_gap_detected",
    "slice_missing",
    "upstream_manual_review_inherited",
    "consecutive_duplicate_detected",
    "heading_count_mismatch",
]

# ---------------------------------------------------------------------------
# MergeTask — one slice to be merged
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MergeTask:
    slice_file: str
    display_title: str
    order_index: int
    start_page: int
    end_page: int
    input_dir: Path
    final_md_file: Path
    review_report_file: Path
    assets_dir: Path | None
    manual_review_required: bool


# ---------------------------------------------------------------------------
# MergeBlockRef — a single block in a slice for overlap comparison
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MergeBlockRef:
    source_page: int
    block_type: str
    is_overlap: bool
    dedupe_key: str | None
    normalized_text_hash: str | None
    asset_ref: str | None
    markdown: str


# ---------------------------------------------------------------------------
# DedupDecision — one dedup action between adjacent slices
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DedupDecision:
    left_slice_file: str
    right_slice_file: str
    source_page: int | None
    match_strategy: MatchStrategy
    removed_from: RemovedFrom
    removed_count: int
    warning: str | None


# ---------------------------------------------------------------------------
# MergeWarning — structured warning
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MergeWarning:
    warning_type: WarningType
    slice_file: str | None
    message: str


# ---------------------------------------------------------------------------
# AssetRelink — one path rewrite record
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AssetRelink:
    slice_file: str
    original_path: str
    rewritten_path: str


# ---------------------------------------------------------------------------
# MergeResult — overall merge outcome
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MergeResult:
    source_file: str
    merged_md_file: str
    status: MergeStatus
    total_slices: int
    merged_slices: int
    removed_overlap_blocks: int
    warning_count: int
    manual_review_required: bool
    warnings: list[MergeWarning] = field(default_factory=list)
    elapsed_ms: int = 0


# ---------------------------------------------------------------------------
# MergeReport — detailed report written to merge_report.json
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MergeReport:
    source_file: str
    merged_md_file: str
    created_at: str
    status: MergeStatus
    manual_review_required: bool
    summary: JsonDict = field(default_factory=dict)
    asset_relinks: list[AssetRelink] = field(default_factory=list)
    pairs: list[DedupDecision] = field(default_factory=list)
    warnings: list[MergeWarning] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MergeManifest — global execution manifest
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SliceEntry:
    slice_file: str
    display_title: str
    order_index: int
    start_page: int
    end_page: int
    status: str
    manual_review_required: bool


@dataclass(slots=True)
class MergeManifest:
    source_format_manifest: str
    source_file: str
    created_at: str
    generator_version: str
    merged_md_file: str
    status: MergeStatus
    total_slices: int
    merged_slices: int
    manual_review_required: bool
    removed_overlap_blocks: int
    warning_count: int
    total_elapsed_ms: int
    slices: list[SliceEntry] = field(default_factory=list)

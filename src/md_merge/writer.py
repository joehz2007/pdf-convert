from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import GENERATOR_VERSION
from .contracts import (
    AssetRelink,
    DedupDecision,
    MergeManifest,
    MergeReport,
    MergeTask,
    MergeWarning,
    SliceEntry,
)

LOGGER = logging.getLogger("md_merge.writer")


def write_output(
    *,
    out_path: Path,
    source_file: str,
    raw_manifest: dict[str, Any],
    tasks: list[MergeTask],
    final_markdown: str,
    dedup_decisions: list[DedupDecision],
    asset_relinks: list[AssetRelink],
    warnings: list[MergeWarning],
    manual_review_required: bool,
    removed_overlap_blocks: int,
    timings: dict[str, int],
) -> str:
    """Write final merged markdown, merge_report.json, and merge_manifest.json.

    Returns the merged markdown filename.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Derive output filename from source_file
    source_stem = Path(source_file).stem if source_file else "merged"
    md_filename = f"{source_stem}.md"
    md_path = out_path / md_filename

    # Write final markdown
    md_path.write_text(final_markdown, encoding="utf-8")
    LOGGER.info("Wrote merged markdown: %s (%d chars)", md_path, len(final_markdown))

    # Build merge_report.json
    status = "success" if not any(
        w.warning_type in ("slice_missing",) for w in warnings
    ) else "failed"

    report = MergeReport(
        source_file=source_file,
        merged_md_file=md_filename,
        created_at=now,
        status=status,
        manual_review_required=manual_review_required,
        summary={
            "total_slices": len(tasks),
            "merged_slices": len(tasks),
            "adjacent_pairs": max(0, len(tasks) - 1),
            "removed_overlap_blocks": removed_overlap_blocks,
            "warning_count": len(warnings),
        },
        asset_relinks=asset_relinks,
        pairs=dedup_decisions,
        warnings=warnings,
    )
    report_path = out_path / "merge_report.json"
    report_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    LOGGER.info("Wrote merge report: %s", report_path)

    # Build merge_manifest.json
    slice_entries = [
        SliceEntry(
            slice_file=t.slice_file,
            display_title=t.display_title,
            order_index=t.order_index,
            start_page=t.start_page,
            end_page=t.end_page,
            status="merged",
            manual_review_required=t.manual_review_required,
        )
        for t in tasks
    ]

    manifest = MergeManifest(
        source_format_manifest="format_manifest.json",
        source_file=source_file,
        created_at=now,
        generator_version=GENERATOR_VERSION,
        merged_md_file=md_filename,
        status=status,
        total_slices=len(tasks),
        merged_slices=len(tasks),
        manual_review_required=manual_review_required,
        removed_overlap_blocks=removed_overlap_blocks,
        warning_count=len(warnings),
        total_elapsed_ms=timings.get("total_ms", 0),
        slices=slice_entries,
    )
    manifest_path = out_path / "merge_manifest.json"
    manifest_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    LOGGER.info("Wrote merge manifest: %s", manifest_path)

    return md_filename

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import GENERATOR_VERSION
from .contracts import (
    FormatManifest,
    FormatResult,
    FormatTask,
    ReviewReport,
)
from .errors import OutputExistsError


def resolve_output_dir(input_dir: Path, output_dir: str | Path | None) -> Path:
    if output_dir is not None:
        return Path(output_dir)
    return input_dir.parent / (input_dir.name.replace("_extract", "") + "_format")


def prepare_output_dir(output_dir: Path, *, overwrite: bool) -> Path:
    if output_dir.exists():
        if not overwrite:
            raise OutputExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def slice_output_dir(output_root: Path, task: FormatTask) -> Path:
    dir_name = f"{task.order_index:03d}-{_safe_dirname(task.display_title)}"
    return output_root / dir_name


def write_slice_result(
    output_root: Path,
    task: FormatTask,
    final_markdown: str,
    review_report: ReviewReport,
    *,
    copy_assets: bool,
    stage_timings: dict,
) -> FormatResult:
    out_dir = slice_output_dir(output_root, task)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write final .md
    md_filename = task.draft_md_file.name
    md_path = out_dir / md_filename
    md_path.write_text(final_markdown, encoding="utf-8")

    # Write review_report.json
    report_path = out_dir / "review_report.json"
    report_path.write_text(
        json.dumps(asdict(review_report), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # Handle assets
    asset_mode = "copy" if copy_assets else "reuse_phase2"
    if copy_assets and task.assets_dir.exists():
        dest_assets = out_dir / "assets"
        if dest_assets.exists():
            shutil.rmtree(dest_assets)
        shutil.copytree(task.assets_dir, dest_assets)

    rel_md = str(md_path.relative_to(output_root))
    rel_report = str(report_path.relative_to(output_root))

    return FormatResult(
        slice_file=task.slice_file,
        final_md_file=rel_md,
        review_report_file=rel_report,
        status="success",
        warning_count=len(review_report.warnings),
        issue_count=len(review_report.issues),
        auto_fixed_count=len(review_report.auto_fixes),
        manual_review_required=review_report.manual_review_required,
        elapsed_ms=0,
        display_title=task.display_title,
        order_index=task.order_index,
        start_page=task.start_page,
        end_page=task.end_page,
        formatted_char_count=review_report.formatted_stats.get("char_count", 0),
        formatted_block_count=review_report.formatted_stats.get("block_count", 0),
        asset_mode=asset_mode,
        stage_timings=dict(stage_timings),
    )


def build_skipped_result(
    raw_slice: dict,
    order_index: int,
) -> FormatResult:
    return FormatResult(
        slice_file=str(raw_slice.get("slice_file", "")),
        final_md_file=None,
        review_report_file=None,
        status="skipped_upstream_failed",
        warning_count=0,
        issue_count=0,
        auto_fixed_count=0,
        manual_review_required=bool(raw_slice.get("manual_review_required", False)),
        elapsed_ms=0,
        display_title=str(raw_slice.get("slice_file", "")),
        order_index=order_index,
    )


def build_failure_result(
    task: FormatTask,
    *,
    elapsed_ms: int,
    error_code: str,
    error_message: str,
    stage_timings: dict,
) -> FormatResult:
    return FormatResult(
        slice_file=task.slice_file,
        final_md_file=None,
        review_report_file=None,
        status="failed",
        warning_count=0,
        issue_count=0,
        auto_fixed_count=0,
        manual_review_required=True,
        elapsed_ms=elapsed_ms,
        display_title=task.display_title,
        order_index=task.order_index,
        start_page=task.start_page,
        end_page=task.end_page,
        error_code=error_code,
        error_message=error_message,
        stage_timings=dict(stage_timings),
    )


def write_format_manifest(
    output_dir: Path,
    raw_manifest: dict,
    slice_results: list[FormatResult],
    *,
    total_elapsed_ms: int,
    run_timings: dict,
) -> FormatManifest:
    success_count = sum(1 for r in slice_results if r.status == "success")
    failed_count = sum(1 for r in slice_results if r.status == "failed")
    manual_review_count = sum(1 for r in slice_results if r.manual_review_required)
    total_issue_count = sum(r.issue_count for r in slice_results)
    total_auto_fixed_count = sum(r.auto_fixed_count for r in slice_results)

    manifest = FormatManifest(
        source_extract_manifest="extract_manifest.json",
        source_file=str(raw_manifest.get("source_file", "")),
        created_at=datetime.now(timezone.utc).isoformat(),
        generator_version=GENERATOR_VERSION,
        total_slices=len(slice_results),
        success_count=success_count,
        failed_count=failed_count,
        manual_review_count=manual_review_count,
        total_issue_count=total_issue_count,
        total_auto_fixed_count=total_auto_fixed_count,
        total_elapsed_ms=total_elapsed_ms,
        slices=slice_results,
        timings={**run_timings, "total_ms": total_elapsed_ms},
    )

    manifest_path = output_dir / "format_manifest.json"
    manifest_path.write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return manifest


def _safe_dirname(title: str) -> str:
    illegal = r'<>:"/\|?*'
    result = title
    for ch in illegal:
        result = result.replace(ch, "_")
    return result.strip(". ")

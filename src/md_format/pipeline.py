from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .contracts import (
    AutoFix,
    CoverageStats,
    FormatManifest,
    FormatResult,
    FormatTask,
    NormalizedDocument,
    ReviewReport,
)
from .block_aligner import align_blocks
from .coverage_auditor import audit_coverage
from .errors import MdFormatError
from .manifest_loader import load_extract_manifest
from .md_normalizer import normalize_markdown
from .postcheck import postcheck
from .renderer import render
from .repair_engine import repair
from .writer import (
    build_failure_result,
    build_skipped_result,
    prepare_output_dir,
    resolve_output_dir,
    write_format_manifest,
    write_slice_result,
)

LOGGER = logging.getLogger("md_format.pipeline")
SLICE_TIMING_KEYS = (
    "coverage_audit_ms",
    "repair_ms",
    "render_ms",
    "postcheck_ms",
    "write_ms",
)


@dataclass(slots=True)
class SliceProcessOutcome:
    task: FormatTask
    final_markdown: str | None = None
    review_report: ReviewReport | None = None
    stage_timings: dict[str, int] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


def run_pipeline(
    *,
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    workers: int = 1,
    overwrite: bool = False,
    fail_on_manual_review: bool = False,
    copy_assets: bool = True,
) -> FormatManifest:
    total_start = perf_counter()

    # Load manifest
    manifest_load_start = perf_counter()
    input_path = Path(input_dir)
    raw_manifest, tasks = load_extract_manifest(input_path)
    manifest_load_ms = elapsed_ms_since(manifest_load_start)

    # Prepare output directory
    resolved_output_dir = prepare_output_dir(
        resolve_output_dir(input_path, output_dir),
        overwrite=overwrite,
    )

    # Build skipped results for upstream-failed slices
    skipped_results = _build_skipped_results(raw_manifest, tasks)

    # Process successful slices
    outcomes = _process_all_slices(tasks, workers=max(1, workers))

    # Write results
    slice_results: list[FormatResult] = list(skipped_results)
    for outcome in outcomes:
        if outcome.final_markdown is None or outcome.review_report is None:
            finalize_stage_timings(outcome.stage_timings)
            slice_results.append(
                build_failure_result(
                    outcome.task,
                    elapsed_ms=outcome.stage_timings.get("total_ms", 0),
                    error_code=outcome.error_code or "unexpected_error",
                    error_message=outcome.error_message or "unknown_error",
                    stage_timings=outcome.stage_timings,
                )
            )
            LOGGER.warning(
                "Slice failed: slice=%s code=%s message=%s",
                outcome.task.slice_file,
                outcome.error_code,
                outcome.error_message,
            )
            continue

        write_start = perf_counter()
        try:
            result = write_slice_result(
                resolved_output_dir,
                outcome.task,
                outcome.final_markdown,
                outcome.review_report,
                copy_assets=copy_assets,
                stage_timings=outcome.stage_timings,
            )
            outcome.stage_timings["write_ms"] = elapsed_ms_since(write_start)
            finalize_stage_timings(outcome.stage_timings)
            result.elapsed_ms = outcome.stage_timings["total_ms"]
            result.stage_timings = dict(outcome.stage_timings)
            slice_results.append(result)
            LOGGER.info(
                "Slice succeeded: slice=%s issues=%s auto_fixed=%s total_ms=%s",
                outcome.task.slice_file,
                result.issue_count,
                result.auto_fixed_count,
                result.elapsed_ms,
            )
        except MdFormatError as exc:
            outcome.stage_timings["write_ms"] = elapsed_ms_since(write_start)
            finalize_stage_timings(outcome.stage_timings)
            slice_results.append(
                build_failure_result(
                    outcome.task,
                    elapsed_ms=outcome.stage_timings["total_ms"],
                    error_code=exc.error_code,
                    error_message=str(exc),
                    stage_timings=outcome.stage_timings,
                )
            )
            LOGGER.warning("Slice write failed: slice=%s code=%s", outcome.task.slice_file, exc.error_code)
        except Exception as exc:
            outcome.stage_timings["write_ms"] = elapsed_ms_since(write_start)
            finalize_stage_timings(outcome.stage_timings)
            slice_results.append(
                build_failure_result(
                    outcome.task,
                    elapsed_ms=outcome.stage_timings["total_ms"],
                    error_code="unexpected_error",
                    error_message=str(exc),
                    stage_timings=outcome.stage_timings,
                )
            )
            LOGGER.exception("Unexpected write failure for slice=%s", outcome.task.slice_file)

    # Sort by order_index
    slice_results.sort(key=lambda r: r.order_index)

    # Write format manifest
    slice_total_ms = sum(r.elapsed_ms for r in slice_results)
    total_elapsed_ms = elapsed_ms_since(total_start)
    manifest = write_format_manifest(
        resolved_output_dir,
        raw_manifest,
        slice_results,
        total_elapsed_ms=total_elapsed_ms,
        run_timings={"manifest_load_ms": manifest_load_ms, "slice_total_ms": slice_total_ms},
    )

    # Handle --fail-on-manual-review
    if fail_on_manual_review and manifest.manual_review_count > 0:
        LOGGER.warning(
            "%d slice(s) require manual review; --fail-on-manual-review is set.",
            manifest.manual_review_count,
        )

    return manifest


def _build_skipped_results(raw_manifest: dict, tasks: list[FormatTask]) -> list[FormatResult]:
    """Build FormatResult entries for upstream-failed slices."""
    task_files = {t.slice_file for t in tasks}
    skipped: list[FormatResult] = []
    for index, raw_slice in enumerate(raw_manifest.get("slices", [])):
        slice_file = str(raw_slice.get("slice_file", ""))
        if slice_file not in task_files:
            skipped.append(build_skipped_result(raw_slice, order_index=index + 1))
    return skipped


def _process_all_slices(
    tasks: list[FormatTask],
    workers: int,
) -> list[SliceProcessOutcome]:
    if workers == 1:
        return [_process_slice(task) for task in tasks]

    futures = {}
    results: list[SliceProcessOutcome] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for task in tasks:
            futures[executor.submit(_process_slice, task)] = task.order_index
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item.task.order_index)
    return results


def _process_slice(task: FormatTask) -> SliceProcessOutcome:
    """Process a single slice through the Phase 3 pipeline.

    Stages: coverage audit → repair → render → normalize → postcheck
    → build review report.
    """
    stage_timings = new_stage_timings()
    try:
        # --- Stage: coverage audit ---
        audit_start = perf_counter()
        content_data = json.loads(task.content_file.read_text(encoding="utf-8"))
        draft_markdown = None
        if task.draft_md_file is not None:
            draft_markdown = task.draft_md_file.read_text(encoding="utf-8")
        audit_result = audit_coverage(content_data, draft_markdown)
        alignment = align_blocks(content_data, draft_markdown)
        stage_timings["coverage_audit_ms"] = elapsed_ms_since(audit_start)

        # --- Stage: repair ---
        repair_start = perf_counter()
        normalized_doc, auto_fixes = repair(
            task, content_data, draft_markdown, audit_result, alignment,
        )
        stage_timings["repair_ms"] = elapsed_ms_since(repair_start)

        # --- Stage: render ---
        render_start = perf_counter()
        rendered_markdown, render_stats = render(normalized_doc)
        stage_timings["render_ms"] = elapsed_ms_since(render_start)

        # --- Stage: normalize + postcheck ---
        postcheck_start = perf_counter()
        normalized_markdown = normalize_markdown(rendered_markdown)

        # Collect asset paths for postcheck
        asset_paths = []
        for page in content_data.get("source_pages", []):
            for img in page.get("images", []):
                ap = img.get("asset_path", "")
                if ap:
                    asset_paths.append(ap)

        pc_result = postcheck(rendered_markdown, normalized_markdown, asset_paths=asset_paths)
        stage_timings["postcheck_ms"] = elapsed_ms_since(postcheck_start)

        # If postcheck failed, fall back to rendered (pre-normalize) version
        if not pc_result.passed:
            LOGGER.warning(
                "Postcheck failed for slice=%s, using pre-normalization markdown",
                task.slice_file,
            )
            final_markdown = rendered_markdown
        else:
            final_markdown = normalized_markdown

        # Combine all issues
        all_issues = list(audit_result.issues) + list(pc_result.issues)

        # Determine manual review
        has_errors = any(i.severity == "error" for i in all_issues)
        manual_review = (
            task.phase2_manual_review_required
            or normalized_doc.phase3_manual_review_required
            or has_errors
        )

        # Build review report
        report = ReviewReport(
            slice_file=task.slice_file,
            final_md_file=_final_markdown_filename(task),
            created_at=datetime.now(timezone.utc).isoformat(),
            status="success",
            manual_review_required=manual_review,
            coverage=audit_result.coverage,
            formatted_stats={
                "char_count": render_stats.char_count,
                "block_count": render_stats.block_count,
                "table_count": render_stats.table_count,
                "image_count": render_stats.image_count,
            },
            issues=all_issues,
            auto_fixes=auto_fixes,
            warnings=[i.message for i in all_issues if i.severity == "warning"],
        )

        finalize_stage_timings(stage_timings)
        return SliceProcessOutcome(
            task=task,
            final_markdown=final_markdown,
            review_report=report,
            stage_timings=stage_timings,
        )
    except MdFormatError as exc:
        finalize_stage_timings(stage_timings)
        return SliceProcessOutcome(
            task=task,
            error_code=exc.error_code,
            error_message=str(exc),
            stage_timings=stage_timings,
        )
    except Exception as exc:
        finalize_stage_timings(stage_timings)
        return SliceProcessOutcome(
            task=task,
            error_code="unexpected_error",
            error_message=str(exc),
            stage_timings=stage_timings,
        )


def new_stage_timings() -> dict[str, int]:
    return {key: 0 for key in SLICE_TIMING_KEYS} | {"total_ms": 0}


def finalize_stage_timings(stage_timings: dict[str, int]) -> None:
    stage_timings["total_ms"] = sum(int(stage_timings.get(key, 0) or 0) for key in SLICE_TIMING_KEYS)


def elapsed_ms_since(start: float) -> int:
    elapsed = (perf_counter() - start) * 1000
    return max(1, int(elapsed))


def _final_markdown_filename(task: FormatTask) -> str:
    if task.draft_md_file is not None:
        return task.draft_md_file.name
    return Path(task.slice_file).with_suffix(".md").name

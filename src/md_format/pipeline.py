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
from .errors import MdFormatError
from .manifest_loader import load_extract_manifest
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

    Current implementation is a placeholder that passes through the
    Phase 2 draft Markdown with minimal processing.  Real audit, repair,
    render, normalize, and postcheck stages will be implemented in M2/M3.
    """
    stage_timings = new_stage_timings()
    try:
        # --- Stage: coverage audit (placeholder) ---
        audit_start = perf_counter()
        content_data = json.loads(task.content_file.read_text(encoding="utf-8"))
        draft_markdown = task.draft_md_file.read_text(encoding="utf-8")
        stage_timings["coverage_audit_ms"] = elapsed_ms_since(audit_start)

        # --- Stage: repair (placeholder) ---
        repair_start = perf_counter()
        final_markdown = draft_markdown
        stage_timings["repair_ms"] = elapsed_ms_since(repair_start)

        # --- Stage: render (placeholder) ---
        render_start = perf_counter()
        stage_timings["render_ms"] = elapsed_ms_since(render_start)

        # --- Stage: postcheck (placeholder) ---
        postcheck_start = perf_counter()
        stage_timings["postcheck_ms"] = elapsed_ms_since(postcheck_start)

        # Build review report
        source_pages = content_data.get("source_pages", [])
        text_blocks_expected = sum(len(p.get("blocks", [])) for p in source_pages)
        tables_expected = sum(len(p.get("tables", [])) for p in source_pages)
        images_expected = sum(len(p.get("images", [])) for p in source_pages)
        overlap_expected = sum(1 for p in source_pages if p.get("is_overlap"))

        report = ReviewReport(
            slice_file=task.slice_file,
            final_md_file=task.draft_md_file.name,
            created_at=datetime.now(timezone.utc).isoformat(),
            status="success",
            manual_review_required=task.phase2_manual_review_required,
            coverage=CoverageStats(
                text_blocks_expected=text_blocks_expected,
                text_blocks_matched=text_blocks_expected,
                tables_expected=tables_expected,
                tables_matched=tables_expected,
                images_expected=images_expected,
                images_matched=images_expected,
                overlap_pages_expected=overlap_expected,
                overlap_pages_matched=overlap_expected,
            ),
            formatted_stats={
                "char_count": len(final_markdown),
                "block_count": text_blocks_expected,
                "table_count": tables_expected,
                "image_count": images_expected,
            },
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

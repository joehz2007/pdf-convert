from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from .contracts import ContentResult, ExtractManifest, SliceTask
from .errors import PdfExtractError
from .manifest_loader import load_manifest
from .markdown_extractor import extract_markdown_chunks
from .metadata_builder import build_content_result
from .precheck import validate_supported_pdf
from .writer import (
    build_failure_record,
    prepare_output_dir,
    resolve_output_dir,
    slice_dir_path,
    write_extract_manifest,
    write_slice_result,
)

LOGGER = logging.getLogger("pdf_extract.pipeline")
SLICE_TIMING_KEYS = ("precheck_ms", "markdown_extract_ms", "metadata_build_ms", "write_ms")


@dataclass(slots=True)
class SliceProcessOutcome:
    task: SliceTask
    content_result: ContentResult | None
    stage_timings: dict[str, int] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


def run_pipeline(
    *,
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    emit_md: bool = True,
    overwrite: bool = False,
    workers: int = 1,
) -> ExtractManifest:
    total_start = perf_counter()
    manifest_load_start = perf_counter()
    loaded_manifest = load_manifest(manifest_path)
    manifest_load_ms = elapsed_ms_since(manifest_load_start)
    resolved_output_dir = prepare_output_dir(resolve_output_dir(loaded_manifest, output_dir), overwrite=overwrite)

    outcomes = _process_all_slices(loaded_manifest.slices, resolved_output_dir, workers=max(1, workers))
    slice_records = []
    for outcome in outcomes:
        if outcome.content_result is None:
            slice_records.append(
                build_failure_record(
                    outcome.task,
                    elapsed_ms=outcome.stage_timings["total_ms"],
                    error_code=outcome.error_code or "unexpected_error",
                    error_message=outcome.error_message or "unknown_error",
                    stage_timings=outcome.stage_timings,
                )
            )
            LOGGER.warning(
                "Slice failed: slice=%s code=%s total_ms=%s message=%s",
                outcome.task.slice_file,
                outcome.error_code or "unexpected_error",
                outcome.stage_timings["total_ms"],
                outcome.error_message or "unknown_error",
            )
            continue

        write_start = perf_counter()
        try:
            record = write_slice_result(
                resolved_output_dir,
                outcome.task,
                outcome.content_result,
                emit_md=emit_md,
                elapsed_ms=0,
                stage_timings=outcome.stage_timings,
            )
            outcome.stage_timings["write_ms"] = elapsed_ms_since(write_start)
            finalize_stage_timings(outcome.stage_timings)
            record.elapsed_ms = outcome.stage_timings["total_ms"]
            record.stage_timings = dict(outcome.stage_timings)
            slice_records.append(record)
            LOGGER.info(
                "Slice succeeded: slice=%s warnings=%s total_ms=%s",
                outcome.task.slice_file,
                record.warning_count,
                record.elapsed_ms,
            )
        except PdfExtractError as exc:
            outcome.stage_timings["write_ms"] = elapsed_ms_since(write_start)
            finalize_stage_timings(outcome.stage_timings)
            slice_records.append(
                build_failure_record(
                    outcome.task,
                    elapsed_ms=outcome.stage_timings["total_ms"],
                    error_code=exc.error_code,
                    error_message=str(exc),
                    stage_timings=outcome.stage_timings,
                )
            )
            LOGGER.warning(
                "Slice write failed: slice=%s code=%s total_ms=%s message=%s",
                outcome.task.slice_file,
                exc.error_code,
                outcome.stage_timings["total_ms"],
                str(exc),
            )
        except Exception as exc:
            outcome.stage_timings["write_ms"] = elapsed_ms_since(write_start)
            finalize_stage_timings(outcome.stage_timings)
            slice_records.append(
                build_failure_record(
                    outcome.task,
                    elapsed_ms=outcome.stage_timings["total_ms"],
                    error_code="unexpected_error",
                    error_message=str(exc),
                    stage_timings=outcome.stage_timings,
                )
            )
            LOGGER.exception("Unexpected write failure for slice=%s", outcome.task.slice_file)

    slice_total_ms = sum(record.elapsed_ms for record in slice_records)
    elapsed_before_manifest_write = elapsed_ms_since(total_start)
    return write_extract_manifest(
        resolved_output_dir,
        loaded_manifest,
        slice_records,
        total_elapsed_ms=elapsed_before_manifest_write,
        run_timings={
            "manifest_load_ms": manifest_load_ms,
            "slice_total_ms": slice_total_ms,
        },
    )


def _process_all_slices(
    tasks: list[SliceTask],
    output_root: Path,
    workers: int,
) -> list[SliceProcessOutcome]:
    if workers == 1:
        return [_process_slice(task, output_root) for task in tasks]

    futures = {}
    results: list[SliceProcessOutcome] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for task in tasks:
            futures[executor.submit(_process_slice, task, output_root)] = task.slice_number
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item.task.slice_number)
    return results


def _process_slice(task: SliceTask, output_root: Path) -> SliceProcessOutcome:
    stage_timings = new_stage_timings()
    try:
        precheck_start = perf_counter()
        try:
            validate_supported_pdf(task.source_path)
        finally:
            stage_timings["precheck_ms"] = elapsed_ms_since(precheck_start)

        markdown_start = perf_counter()
        try:
            chunks = extract_markdown_chunks(task.source_path)
        finally:
            stage_timings["markdown_extract_ms"] = elapsed_ms_since(markdown_start)

        metadata_start = perf_counter()
        try:
            result = build_content_result(task, chunks, slice_dir=slice_dir_path(output_root, task))
        finally:
            stage_timings["metadata_build_ms"] = elapsed_ms_since(metadata_start)

        finalize_stage_timings(stage_timings)
        return SliceProcessOutcome(task=task, content_result=result, stage_timings=stage_timings)
    except PdfExtractError as exc:
        finalize_stage_timings(stage_timings)
        return SliceProcessOutcome(
            task=task,
            content_result=None,
            error_code=exc.error_code,
            error_message=str(exc),
            stage_timings=stage_timings,
        )
    except Exception as exc:  # Keep per-slice failures isolated for the extract manifest.
        finalize_stage_timings(stage_timings)
        return SliceProcessOutcome(
            task=task,
            content_result=None,
            error_code="unexpected_error",
            error_message=str(exc),
            stage_timings=stage_timings,
        )


def new_stage_timings() -> dict[str, int]:
    return {
        "precheck_ms": 0,
        "markdown_extract_ms": 0,
        "metadata_build_ms": 0,
        "write_ms": 0,
        "total_ms": 0,
    }


def finalize_stage_timings(stage_timings: dict[str, int]) -> None:
    stage_timings["total_ms"] = sum(int(stage_timings.get(key, 0) or 0) for key in SLICE_TIMING_KEYS)


def elapsed_ms_since(start: float) -> int:
    elapsed = (perf_counter() - start) * 1000
    return max(1, int(elapsed))

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

from .contracts import ContentResult, ExtractManifest, ExtractSliceRecord, SliceTask
from .manifest_loader import load_manifest
from .markdown_extractor import extract_markdown_chunks
from .metadata_builder import build_content_result
from .precheck import validate_supported_pdf
from .writer import build_failure_record, prepare_output_dir, resolve_output_dir, write_extract_manifest, write_slice_result


def run_pipeline(
    *,
    manifest_path: str | Path,
    output_dir: str | Path | None = None,
    emit_md: bool = True,
    overwrite: bool = False,
    workers: int = 1,
) -> ExtractManifest:
    total_start = perf_counter()
    loaded_manifest = load_manifest(manifest_path)
    resolved_output_dir = prepare_output_dir(resolve_output_dir(loaded_manifest, output_dir), overwrite=overwrite)

    outcomes = _process_all_slices(loaded_manifest.slices, workers=max(1, workers))
    slice_records: list[ExtractSliceRecord] = []
    for task, content_result, elapsed_ms, error_message in outcomes:
        if content_result is None:
            slice_records.append(build_failure_record(task, elapsed_ms=elapsed_ms, error_message=error_message or "unknown_error"))
            continue
        slice_records.append(
            write_slice_result(
                resolved_output_dir,
                task,
                content_result,
                emit_md=emit_md,
                elapsed_ms=elapsed_ms,
            )
        )

    total_elapsed_ms = int((perf_counter() - total_start) * 1000)
    return write_extract_manifest(
        resolved_output_dir,
        loaded_manifest,
        slice_records,
        total_elapsed_ms=total_elapsed_ms,
    )


def _process_all_slices(
    tasks: list[SliceTask],
    workers: int,
) -> list[tuple[SliceTask, ContentResult | None, int, str | None]]:
    if workers == 1:
        return [_process_slice(task) for task in tasks]

    futures = {}
    results: list[tuple[SliceTask, ContentResult | None, int, str | None]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for task in tasks:
            futures[executor.submit(_process_slice, task)] = task.slice_number
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item[0].slice_number)
    return results


def _process_slice(task: SliceTask) -> tuple[SliceTask, ContentResult | None, int, str | None]:
    start = perf_counter()
    try:
        validate_supported_pdf(task.source_path)
        chunks = extract_markdown_chunks(task.source_path)
        result = build_content_result(task, chunks)
        elapsed_ms = int((perf_counter() - start) * 1000)
        return task, result, elapsed_ms, None
    except Exception as exc:  # Keep per-slice failures isolated for the extract manifest.
        elapsed_ms = int((perf_counter() - start) * 1000)
        return task, None, elapsed_ms, str(exc)


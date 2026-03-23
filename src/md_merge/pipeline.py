from __future__ import annotations

import logging
import time
from pathlib import Path

from .contracts import MergeResult, MergeWarning
from .errors import MdMergeError, OutputExistsError

LOGGER = logging.getLogger("md_merge.pipeline")


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def run_pipeline(
    *,
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    copy_assets: bool = True,
    overwrite: bool = False,
    fail_on_manual_review: bool = False,
    allow_upstream_manual_review: bool = False,
) -> MergeResult:
    from .manifest_loader import load_manifest
    from .provenance_loader import load_provenance
    from .merge_planner import plan_merge
    from .overlap_resolver import resolve_overlaps
    from .asset_relinker import relink_assets
    from .stitcher import stitch
    from .postcheck import postcheck
    from .writer import write_output

    total_start = time.perf_counter()
    timings: dict[str, int] = {}
    warnings: list[MergeWarning] = []

    input_path = Path(input_dir)

    # --- Resolve & prepare output dir ---
    if output_dir is not None:
        out_path = Path(output_dir)
    else:
        out_path = input_path.parent / (
            input_path.name.replace("_format", "") + "_merged"
        )

    if out_path.exists():
        if not overwrite:
            raise OutputExistsError(
                f"Output directory already exists: {out_path}. Use --overwrite to allow."
            )
        import shutil
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    # --- Stage 1: Load manifest ---
    t = time.perf_counter()
    tasks, source_file, raw_manifest = load_manifest(input_path)
    timings["manifest_load_ms"] = _ms_since(t)
    LOGGER.info("Loaded %d slices from manifest", len(tasks))

    # --- Check upstream manual review ---
    upstream_manual = [t for t in tasks if t.manual_review_required]
    if upstream_manual and not allow_upstream_manual_review:
        for um in upstream_manual:
            warnings.append(MergeWarning(
                warning_type="upstream_manual_review_inherited",
                slice_file=um.slice_file,
                message=f"Upstream slice requires manual review: {um.slice_file}",
            ))
        return MergeResult(
            source_file=source_file,
            merged_md_file="",
            status="aborted_upstream_invalid",
            total_slices=len(tasks),
            merged_slices=0,
            removed_overlap_blocks=0,
            warning_count=len(warnings),
            manual_review_required=True,
            warnings=warnings,
            elapsed_ms=_ms_since(total_start),
        )

    if upstream_manual:
        for um in upstream_manual:
            warnings.append(MergeWarning(
                warning_type="upstream_manual_review_inherited",
                slice_file=um.slice_file,
                message=f"Upstream slice flagged for manual review (allowed): {um.slice_file}",
            ))

    # --- Stage 2: Load provenance ---
    t = time.perf_counter()
    provenance = load_provenance(tasks, raw_manifest, warnings)
    timings["provenance_load_ms"] = _ms_since(t)

    # --- Stage 3: Plan merge ---
    t = time.perf_counter()
    pairs, asset_plan = plan_merge(tasks, warnings)
    timings["plan_ms"] = _ms_since(t)

    # --- Stage 4: Resolve overlaps ---
    t = time.perf_counter()
    dedup_decisions, slice_contents = resolve_overlaps(tasks, provenance, pairs, warnings)
    timings["overlap_resolve_ms"] = _ms_since(t)
    removed_blocks = sum(d.removed_count for d in dedup_decisions)

    # --- Stage 5: Relink assets ---
    t = time.perf_counter()
    asset_relinks = relink_assets(
        tasks, slice_contents, out_path, copy_assets=copy_assets, warnings=warnings,
    )
    timings["asset_relink_ms"] = _ms_since(t)

    # --- Stage 6: Stitch ---
    t = time.perf_counter()
    final_markdown = stitch(tasks, slice_contents)
    timings["stitch_ms"] = _ms_since(t)

    # --- Stage 7: Post-check ---
    t = time.perf_counter()
    manual_review = postcheck(tasks, final_markdown, out_path, warnings)
    timings["postcheck_ms"] = _ms_since(t)

    # Inherit upstream manual review
    if upstream_manual:
        manual_review = True

    # --- Stage 8: Write output ---
    t = time.perf_counter()
    merged_md_file = write_output(
        out_path=out_path,
        source_file=source_file,
        raw_manifest=raw_manifest,
        tasks=tasks,
        final_markdown=final_markdown,
        dedup_decisions=dedup_decisions,
        asset_relinks=asset_relinks,
        warnings=warnings,
        manual_review_required=manual_review,
        removed_overlap_blocks=removed_blocks,
        timings=timings,
    )
    timings["write_ms"] = _ms_since(t)

    total_ms = _ms_since(total_start)
    timings["total_ms"] = total_ms

    LOGGER.info("Pipeline timings: %s", timings)

    return MergeResult(
        source_file=source_file,
        merged_md_file=str(merged_md_file),
        status="success",
        total_slices=len(tasks),
        merged_slices=len(tasks),
        removed_overlap_blocks=removed_blocks,
        warning_count=len(warnings),
        manual_review_required=manual_review,
        warnings=warnings,
        elapsed_ms=total_ms,
    )

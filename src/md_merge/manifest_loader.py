from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .contracts import MergeTask
from .errors import (
    InvalidFormatManifestError,
    MissingFinalMarkdownError,
    MissingReviewReportError,
    UpstreamSliceFailedError,
)

LOGGER = logging.getLogger("md_merge.manifest_loader")

REQUIRED_TOP_KEYS = {"source_file", "slices"}
REQUIRED_SLICE_KEYS = {
    "slice_file",
    "display_title",
    "order_index",
    "start_page",
    "end_page",
    "final_md_file",
    "status",
}


def load_manifest(
    input_dir: Path,
) -> tuple[list[MergeTask], str, dict[str, Any]]:
    """Load format_manifest.json, validate, and return sorted MergeTask list.

    Returns:
        (tasks, source_file, raw_manifest_dict)
    """
    manifest_path = input_dir / "format_manifest.json"
    if not manifest_path.exists():
        raise InvalidFormatManifestError(
            f"format_manifest.json not found in {input_dir}"
        )

    raw: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing_top = REQUIRED_TOP_KEYS - raw.keys()
    if missing_top:
        raise InvalidFormatManifestError(
            f"format_manifest.json missing top-level keys: {missing_top}"
        )

    source_file: str = raw.get("source_file", "")
    raw_slices: list[dict] = raw.get("slices", [])
    if not raw_slices:
        raise InvalidFormatManifestError("format_manifest.json has no slices")

    # Filter: only process success slices; skip failed/skipped with warning
    success_slices: list[dict] = []
    for s in raw_slices:
        if s.get("status") == "success":
            success_slices.append(s)
        else:
            LOGGER.warning(
                "Skipping non-success slice [%s] status=%s",
                s.get("slice_file", "?"), s.get("status"),
            )

    if not success_slices:
        raise UpstreamSliceFailedError(
            "No slices with status=success found in format_manifest.json"
        )

    # Build MergeTasks
    tasks: list[MergeTask] = []
    seen_indices: set[int] = set()

    for s in success_slices:
        missing_keys = REQUIRED_SLICE_KEYS - s.keys()
        if missing_keys:
            raise InvalidFormatManifestError(
                f"Slice {s.get('slice_file', '?')} missing keys: {missing_keys}"
            )

        order_index = int(s["order_index"])
        if order_index in seen_indices:
            raise InvalidFormatManifestError(
                f"Duplicate order_index {order_index} in format_manifest.json"
            )
        seen_indices.add(order_index)

        final_md_rel = s.get("final_md_file", "")
        review_report_rel = s.get("review_report_file", "")

        final_md_path = input_dir / final_md_rel
        if not final_md_path.exists():
            raise MissingFinalMarkdownError(
                f"Final markdown not found: {final_md_path}"
            )

        review_report_path = input_dir / review_report_rel if review_report_rel else None
        if review_report_path and not review_report_path.exists():
            raise MissingReviewReportError(
                f"Review report not found: {review_report_path}"
            )

        # Assets dir: look in the same directory as the final md
        slice_dir = final_md_path.parent
        assets_dir = slice_dir / "assets"
        if not assets_dir.exists():
            assets_dir = None

        tasks.append(MergeTask(
            slice_file=s["slice_file"],
            display_title=s["display_title"],
            order_index=order_index,
            start_page=int(s["start_page"]),
            end_page=int(s["end_page"]),
            input_dir=slice_dir,
            final_md_file=final_md_path,
            review_report_file=review_report_path or (slice_dir / "review_report.json"),
            assets_dir=assets_dir,
            manual_review_required=bool(s.get("manual_review_required", False)),
        ))

    # Sort by order_index
    tasks.sort(key=lambda t: t.order_index)

    LOGGER.info(
        "Manifest loaded: source=%s, %d slices, pages %d-%d",
        source_file,
        len(tasks),
        tasks[0].start_page if tasks else 0,
        tasks[-1].end_page if tasks else 0,
    )

    return tasks, source_file, raw

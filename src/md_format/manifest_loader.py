from __future__ import annotations

import json
from pathlib import Path

from .contracts import FormatTask
from .errors import (
    InvalidExtractManifestError,
    MissingContentFileError,
    MissingDraftMarkdownError,
)

REQUIRED_GLOBAL_FIELDS = {"source_file", "total_slices", "slices"}
REQUIRED_SLICE_FIELDS = {"slice_file", "content_file", "status"}


def load_extract_manifest(
    input_dir: str | Path,
) -> tuple[dict, list[FormatTask]]:
    """Read extract_manifest.json and build a list of FormatTask objects.

    Returns ``(raw_manifest_dict, tasks)`` where *tasks* only includes
    slices whose upstream status is ``"success"``.  Failed upstream slices
    are excluded from the task list so the caller can record them as
    ``skipped_upstream_failed``.
    """
    input_path = Path(input_dir)
    manifest_file = input_path / "extract_manifest.json"
    if not manifest_file.exists():
        raise InvalidExtractManifestError(f"extract_manifest.json not found in {input_path}")

    try:
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidExtractManifestError(f"extract_manifest.json is not valid JSON: {manifest_file}") from exc

    missing_globals = REQUIRED_GLOBAL_FIELDS - data.keys()
    if missing_globals:
        raise InvalidExtractManifestError(f"extract_manifest.json missing required fields: {sorted(missing_globals)}")

    if not isinstance(data["slices"], list) or not data["slices"]:
        raise InvalidExtractManifestError("extract_manifest.json 'slices' must be a non-empty list.")

    tasks: list[FormatTask] = []
    for index, slice_data in enumerate(data["slices"]):
        missing_fields = REQUIRED_SLICE_FIELDS - slice_data.keys()
        if missing_fields:
            raise InvalidExtractManifestError(
                f"Slice entry {index + 1} missing required fields: {sorted(missing_fields)}"
            )

        status = str(slice_data["status"])
        if status != "success":
            continue

        content_rel = str(slice_data["content_file"])
        content_path = input_path / content_rel

        if not content_path.exists():
            raise MissingContentFileError(f"content.json not found: {content_path}")

        md_path: Path | None = None
        md_rel = slice_data.get("md_file")
        emit_draft_md = bool(slice_data.get("emit_draft_md", False))
        if md_rel:
            candidate = input_path / str(md_rel)
            if candidate.exists():
                md_path = candidate
            elif emit_draft_md:
                raise MissingDraftMarkdownError(f"Draft Markdown not found: {candidate}")

        slice_dir = content_path.parent
        assets_dir = slice_dir / "assets"

        # Read content.json to get display_title, start_page, end_page
        try:
            content_data = json.loads(content_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise InvalidExtractManifestError(f"Cannot read content.json: {content_path}") from exc

        tasks.append(
            FormatTask(
                slice_file=str(slice_data["slice_file"]),
                display_title=str(content_data.get("display_title", slice_data["slice_file"])),
                order_index=index + 1,
                input_dir=slice_dir,
                content_file=content_path,
                draft_md_file=md_path,
                assets_dir=assets_dir,
                phase2_manual_review_required=bool(slice_data.get("manual_review_required", False)),
                start_page=int(content_data.get("start_page", 0)),
                end_page=int(content_data.get("end_page", 0)),
            )
        )

    return data, tasks

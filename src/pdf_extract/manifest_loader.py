from __future__ import annotations

import json
from pathlib import Path

import pymupdf

from .contracts import LoadedManifest, SliceTask
from .errors import InvalidManifestError, MissingSliceError

REQUIRED_GLOBAL_FIELDS = {"source_file", "total_pages", "fallback_level", "slices"}
REQUIRED_SLICE_FIELDS = {
    "slice_file",
    "start_page",
    "end_page",
    "actual_pages",
    "display_title",
    "overlap_pages",
    "manual_review_required",
}


def load_manifest(manifest_path: str | Path) -> LoadedManifest:
    path = Path(manifest_path)
    if not path.exists():
        raise InvalidManifestError(f"Manifest file does not exist: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InvalidManifestError(f"Manifest is not valid JSON: {path}") from exc

    missing_globals = REQUIRED_GLOBAL_FIELDS - data.keys()
    if missing_globals:
        raise InvalidManifestError(f"Manifest is missing required fields: {sorted(missing_globals)}")

    if not isinstance(data["slices"], list) or not data["slices"]:
        raise InvalidManifestError("Manifest 'slices' must be a non-empty list.")

    slices: list[SliceTask] = []
    for index, slice_data in enumerate(data["slices"], start=1):
        missing_fields = REQUIRED_SLICE_FIELDS - slice_data.keys()
        if missing_fields:
            raise InvalidManifestError(f"Slice entry {index} is missing required fields: {sorted(missing_fields)}")

        start_page = int(slice_data["start_page"])
        end_page = int(slice_data["end_page"])
        actual_pages = int(slice_data["actual_pages"])
        if start_page <= 0 or end_page < start_page:
            raise InvalidManifestError(f"Slice entry {index} has invalid page range: {start_page}-{end_page}")

        expected_pages = end_page - start_page + 1
        if actual_pages != expected_pages:
            raise InvalidManifestError(
                f"Slice entry {index} declared actual_pages={actual_pages}, expected {expected_pages} from page range."
            )

        overlap_pages = [int(page) for page in slice_data.get("overlap_pages", [])]
        if any(page < start_page or page > end_page for page in overlap_pages):
            raise InvalidManifestError(f"Slice entry {index} has overlap pages outside its page range.")

        slice_file = str(slice_data["slice_file"])
        source_path = path.parent / slice_file
        if not source_path.exists():
            raise MissingSliceError(f"Slice PDF does not exist: {source_path}")
        _validate_slice_page_count(source_path, actual_pages=actual_pages, slice_index=index)

        slices.append(
            SliceTask(
                slice_number=index,
                slice_file=slice_file,
                source_path=source_path,
                display_title=str(slice_data["display_title"]),
                start_page=start_page,
                end_page=end_page,
                overlap_pages=overlap_pages,
                manual_review_required=bool(slice_data.get("manual_review_required", False)),
            )
        )

    return LoadedManifest(
        manifest_path=path,
        source_file=str(data["source_file"]),
        total_pages=int(data["total_pages"]),
        fallback_level=int(data["fallback_level"]),
        slices=slices,
    )


def _validate_slice_page_count(source_path: Path, *, actual_pages: int, slice_index: int) -> None:
    try:
        document = pymupdf.open(str(source_path))
    except Exception as exc:
        raise InvalidManifestError(f"Slice entry {slice_index} cannot be opened as PDF: {source_path}") from exc

    try:
        if document.page_count != actual_pages:
            raise InvalidManifestError(
                f"Slice entry {slice_index} actual_pages mismatch: manifest={actual_pages}, pdf={document.page_count}."
            )
    finally:
        document.close()

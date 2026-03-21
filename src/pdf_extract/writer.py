from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import GENERATOR_VERSION, OUTPUT_SCOPE
from .contracts import ContentResult, ExtractManifest, ExtractSliceRecord, LoadedManifest, SliceTask
from .errors import OutputExistsError

INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')
MAX_SAFE_PATH_LENGTH = 240
MIN_COMPONENT_LENGTH = 20


def resolve_output_dir(loaded_manifest: LoadedManifest, output_dir: str | Path | None) -> Path:
    if output_dir:
        return Path(output_dir)
    source_stem = Path(loaded_manifest.source_file).stem or loaded_manifest.manifest_path.parent.name.removesuffix("_split")
    return loaded_manifest.manifest_path.parent.with_name(f"{source_stem}_extract")


def prepare_output_dir(output_dir: Path, overwrite: bool) -> Path:
    if output_dir.exists():
        if not overwrite:
            raise OutputExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def write_slice_result(
    output_root: Path,
    task: SliceTask,
    result: ContentResult,
    *,
    emit_md: bool,
    elapsed_ms: int,
) -> ExtractSliceRecord:
    folder_name = fit_path_component(output_root, f"{task.slice_number:03d}-{sanitize_name(task.display_title)}")
    slice_dir = output_root / folder_name
    slice_dir.mkdir(parents=True, exist_ok=True)

    source_copy = slice_dir / "source.pdf"
    shutil.copy2(task.source_path, source_copy)

    content_path = slice_dir / "content.json"
    content_payload = asdict(result)
    content_path.write_text(json.dumps(content_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path: Path | None = None
    if emit_md:
        original_md_name = Path(task.slice_file).with_suffix(".md").name
        safe_md_name = fit_path_component(slice_dir, sanitize_name(original_md_name))
        md_path = slice_dir / safe_md_name
        md_text = "\n\n".join(page.markdown for page in result.source_pages if page.markdown).strip()
        if md_text:
            md_text += "\n"
        md_path.write_text(md_text, encoding="utf-8")

    return ExtractSliceRecord(
        slice_file=task.slice_file,
        content_file=str(content_path.relative_to(output_root)),
        md_file=str(md_path.relative_to(output_root)) if md_path is not None else None,
        status="success",
        warning_count=len(result.warnings),
        manual_review_required=result.manual_review_required,
        elapsed_ms=elapsed_ms,
    )


def write_extract_manifest(
    output_root: Path,
    loaded_manifest: LoadedManifest,
    slice_records: list[ExtractSliceRecord],
    *,
    total_elapsed_ms: int,
) -> ExtractManifest:
    extract_manifest = ExtractManifest(
        source_manifest=loaded_manifest.manifest_path.name,
        source_file=loaded_manifest.source_file,
        created_at=datetime.now(timezone.utc).isoformat(),
        generator_version=GENERATOR_VERSION,
        scope=OUTPUT_SCOPE,
        total_slices=len(slice_records),
        success_count=sum(1 for item in slice_records if item.status == "success"),
        failed_count=sum(1 for item in slice_records if item.status != "success"),
        total_warnings=sum(item.warning_count for item in slice_records),
        total_elapsed_ms=total_elapsed_ms,
        slices=slice_records,
    )
    manifest_path = output_root / "extract_manifest.json"
    manifest_path.write_text(json.dumps(asdict(extract_manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return extract_manifest


def build_failure_record(task: SliceTask, *, elapsed_ms: int, error_message: str) -> ExtractSliceRecord:
    return ExtractSliceRecord(
        slice_file=task.slice_file,
        content_file=None,
        md_file=None,
        status="failed",
        warning_count=0,
        manual_review_required=True,
        elapsed_ms=elapsed_ms,
        error_message=error_message,
    )


def sanitize_name(value: str) -> str:
    sanitized = INVALID_NAME_CHARS.sub("_", value).strip()
    return sanitized or "untitled"


def fit_path_component(parent: Path, name: str) -> str:
    candidate = sanitize_name(name)
    suffix = Path(candidate).suffix
    stem = Path(candidate).stem
    max_length = max(MIN_COMPONENT_LENGTH, MAX_SAFE_PATH_LENGTH - len(str(parent)) - 1)
    if len(candidate) <= max_length:
        return candidate

    keep = max(MIN_COMPONENT_LENGTH - len(suffix) - 3, max_length - len(suffix) - 3)
    truncated = stem[:keep].rstrip(" .") or "item"
    return f"{truncated}__{suffix}" if suffix else f"{truncated}__"


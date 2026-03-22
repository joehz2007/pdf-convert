from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from .config import GENERATOR_VERSION, OUTPUT_SCOPE
from .contracts import ContentResult, ExtractManifest, ExtractSliceRecord, LoadedManifest, PageContent, SliceTask, TableNode
from .errors import OutputExistsError

INVALID_NAME_CHARS = re.compile(r'[\\/:*?"<>|]')
MAX_SAFE_PATH_LENGTH = 240
MIN_COMPONENT_LENGTH = 20
SLICE_TIMING_KEYS = ("precheck_ms", "markdown_extract_ms", "metadata_build_ms", "write_ms", "total_ms")
RUN_TIMING_KEYS = ("manifest_load_ms", "slice_total_ms", "write_manifest_ms", "total_ms")
TABLE_FALLBACK_PLACEHOLDER = "[复杂表格 Markdown 已回退，请以 content.json / fallback_html 为准]"


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


def slice_dir_path(output_root: Path, task: SliceTask) -> Path:
    folder_name = fit_path_component(output_root, f"{task.slice_number:03d}-{sanitize_name(task.display_title)}")
    return output_root / folder_name


def write_slice_result(
    output_root: Path,
    task: SliceTask,
    result: ContentResult,
    *,
    emit_md: bool,
    elapsed_ms: int,
    stage_timings: dict[str, int] | None = None,
) -> ExtractSliceRecord:
    slice_dir = slice_dir_path(output_root, task)
    slice_dir.mkdir(parents=True, exist_ok=True)

    source_copy = slice_dir / "source.pdf"
    if not source_copy.exists():
        shutil.copy2(task.source_path, source_copy)

    content_path = slice_dir / "content.json"
    content_payload = asdict(result)
    content_path.write_text(json.dumps(content_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path: Path | None = None
    if emit_md:
        original_md_name = Path(task.slice_file).with_suffix(".md").name
        safe_md_name = fit_path_component(slice_dir, sanitize_name(original_md_name))
        md_path = slice_dir / safe_md_name
        md_sections = [render_page_markdown(page) for page in result.source_pages]
        md_text = "\n\n".join(section for section in md_sections if section).strip()
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
        stage_timings=normalize_slice_timings(stage_timings),
    )


def render_page_markdown(page: PageContent) -> str:
    markdown = (page.markdown or "").strip()
    complex_fragments = [fragment for table in page.tables if (fragment := render_complex_table_fragment(table))]
    if not markdown:
        return "\n\n".join(complex_fragments).strip()

    rendered = markdown
    used = 0
    while TABLE_FALLBACK_PLACEHOLDER in rendered and used < len(complex_fragments):
        rendered = rendered.replace(TABLE_FALLBACK_PLACEHOLDER, complex_fragments[used], 1)
        used += 1

    if TABLE_FALLBACK_PLACEHOLDER in rendered:
        rendered = rendered.replace(TABLE_FALLBACK_PLACEHOLDER, "")

    if used < len(complex_fragments):
        tail = "\n\n".join(complex_fragments[used:]).strip()
        if tail:
            rendered = rendered.rstrip()
            rendered = f"{rendered}\n\n{tail}" if rendered else tail
    return rendered.strip()


def render_complex_table_fragment(table: TableNode) -> str:
    if table.table_role == "parent" and not has_nonempty_table_rows(table):
        return ""
    if table.fallback_html:
        return table.fallback_html.strip()
    if table.fallback_image:
        alt = table.section_title or ("complex-table-child" if table.table_role == "child" else "complex-table-fallback")
        return f"![{alt}]({table.fallback_image})"
    return ""


def has_nonempty_table_rows(table: TableNode) -> bool:
    return any(any(str(cell).strip() for cell in row) for row in table.rows)


def write_extract_manifest(
    output_root: Path,
    loaded_manifest: LoadedManifest,
    slice_records: list[ExtractSliceRecord],
    *,
    total_elapsed_ms: int,
    run_timings: dict[str, int] | None = None,
) -> ExtractManifest:
    timings = normalize_run_timings(run_timings)
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
        timings=timings,
    )
    manifest_path = output_root / "extract_manifest.json"
    write_start = perf_counter()
    manifest_path.write_text(json.dumps(asdict(extract_manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    timings["write_manifest_ms"] = elapsed_ms_since(write_start)
    timings["total_ms"] = total_elapsed_ms + timings["write_manifest_ms"]
    extract_manifest.total_elapsed_ms = timings["total_ms"]
    manifest_path.write_text(json.dumps(asdict(extract_manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return extract_manifest


def build_failure_record(
    task: SliceTask,
    *,
    elapsed_ms: int,
    error_code: str,
    error_message: str,
    stage_timings: dict[str, int] | None = None,
) -> ExtractSliceRecord:
    return ExtractSliceRecord(
        slice_file=task.slice_file,
        content_file=None,
        md_file=None,
        status="failed",
        warning_count=0,
        manual_review_required=True,
        elapsed_ms=elapsed_ms,
        error_code=error_code,
        error_message=error_message,
        stage_timings=normalize_slice_timings(stage_timings),
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

    keep = max(MIN_COMPONENT_LENGTH - len(suffix) - 2, max_length - len(suffix) - 2)
    truncated = stem[:keep].rstrip(" .") or "item"
    return f"{truncated}__{suffix}" if suffix else f"{truncated}__"


def normalize_slice_timings(stage_timings: dict[str, int] | None) -> dict[str, int]:
    normalized = {key: 0 for key in SLICE_TIMING_KEYS}
    if stage_timings:
        for key in SLICE_TIMING_KEYS:
            normalized[key] = int(stage_timings.get(key, 0) or 0)
    if normalized["total_ms"] <= 0:
        normalized["total_ms"] = sum(normalized[key] for key in SLICE_TIMING_KEYS if key != "total_ms")
    return normalized


def normalize_run_timings(run_timings: dict[str, int] | None) -> dict[str, int]:
    normalized = {key: 0 for key in RUN_TIMING_KEYS}
    if run_timings:
        for key in RUN_TIMING_KEYS:
            normalized[key] = int(run_timings.get(key, 0) or 0)
    return normalized


def elapsed_ms_since(start: float) -> int:
    elapsed = (perf_counter() - start) * 1000
    return max(1, int(elapsed))

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]


@dataclass(slots=True)
class SliceTask:
    slice_number: int
    slice_file: str
    source_path: Path
    display_title: str
    start_page: int
    end_page: int
    overlap_pages: list[int] = field(default_factory=list)
    manual_review_required: bool = False

    @property
    def actual_pages(self) -> int:
        return self.end_page - self.start_page + 1


@dataclass(slots=True)
class LoadedManifest:
    manifest_path: Path
    source_file: str
    total_pages: int
    fallback_level: int
    slices: list[SliceTask]


@dataclass(slots=True)
class PageContent:
    slice_page: int
    source_page: int
    is_overlap: bool
    markdown: str
    blocks: list[JsonDict] = field(default_factory=list)
    tables: list[JsonDict] = field(default_factory=list)
    images: list[JsonDict] = field(default_factory=list)


@dataclass(slots=True)
class ContentResult:
    slice_file: str
    display_title: str
    start_page: int
    end_page: int
    source_pages: list[PageContent]
    assets: list[JsonDict] = field(default_factory=list)
    stats: JsonDict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    manual_review_required: bool = False


@dataclass(slots=True)
class ExtractSliceRecord:
    slice_file: str
    content_file: str | None
    md_file: str | None
    status: str
    warning_count: int
    manual_review_required: bool
    elapsed_ms: int
    error_message: str | None = None


@dataclass(slots=True)
class ExtractManifest:
    source_manifest: str
    source_file: str
    created_at: str
    generator_version: str
    scope: str
    total_slices: int
    success_count: int
    failed_count: int
    total_warnings: int
    total_elapsed_ms: int
    slices: list[ExtractSliceRecord]

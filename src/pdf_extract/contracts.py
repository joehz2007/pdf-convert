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
class BlockNode:
    type: str
    text: str
    source_page: int
    bbox: list[float]
    reading_order: int
    is_overlap: bool
    dedupe_key: str
    heading_level: int | None = None


@dataclass(slots=True)
class TableNode:
    type: str
    source_page: int
    bbox: list[float]
    table_strategy_used: str
    table_fallback_used: bool
    table_retry_pages: list[int] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    markdown: str | None = None
    rendered_markdown: str | None = None
    fallback_html: str | None = None
    fallback_image: str | None = None
    table_id: str = ""
    parent_table_id: str | None = None
    table_role: str = "standalone"
    section_title: str | None = None
    child_table_ids: list[str] = field(default_factory=list)
    table_kind: str = "simple"
    render_strategy: str = "gfm_table"
    data_attributes: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ImageNode:
    type: str
    source_page: int
    bbox: list[float]
    asset_path: str
    width: int
    height: int
    caption: str | None = None


@dataclass(slots=True)
class OutlineNode:
    section_id: str
    title: str
    level: int
    source_page: int
    parent_id: str | None = None


@dataclass(slots=True)
class PageContent:
    slice_page: int
    source_page: int
    is_overlap: bool
    markdown: str
    blocks: list[BlockNode] = field(default_factory=list)
    tables: list[TableNode] = field(default_factory=list)
    images: list[ImageNode] = field(default_factory=list)


@dataclass(slots=True)
class ContentResult:
    slice_file: str
    display_title: str
    start_page: int
    end_page: int
    source_pages: list[PageContent]
    document_outline: list[OutlineNode] = field(default_factory=list)
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
    error_code: str | None = None
    error_message: str | None = None
    stage_timings: JsonDict = field(default_factory=dict)


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
    timings: JsonDict = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChapterNode:
    """All pages are 1-based for user-facing output."""

    title: str
    start_page: int
    end_page: int
    level: int = 1

    @property
    def page_span(self) -> int:
        return self.end_page - self.start_page + 1


@dataclass(slots=True)
class SlicePlan:
    """All pages are 1-based and directly used in filenames, logs and manifest."""

    title: str
    start_page: int
    end_page: int
    split_mode: str
    overlap_pages: list[int] = field(default_factory=list)
    boundary_reason: str = "chapter_boundary"
    exception_type: str | None = None
    manual_review_required: bool = False
    toc_level: int = 1

    @property
    def actual_pages(self) -> int:
        return self.end_page - self.start_page + 1


@dataclass(slots=True)
class RecognitionResult:
    chapters: list[ChapterNode]
    fallback_level: int

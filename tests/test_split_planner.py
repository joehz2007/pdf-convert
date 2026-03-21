from __future__ import annotations

from pdf_slicer.models import ChapterNode, SlicePlan
from pdf_slicer.split_planner import SplitPlanner


class FakeDocument:
    def __init__(self, total_pages: int, texts: dict[int, str] | None = None):
        self.total_pages = total_pages
        self._texts = texts or {}

    def page_text(self, page_number: int) -> str:
        return self._texts.get(page_number, "")

    def get_text_dict(self, page_number: int):
        return {"height": 1000, "blocks": []}


class FakeAnalyzer:
    def __init__(self, safe_boundaries: set[int]):
        self.safe_boundaries = safe_boundaries

    def is_safe_split_boundary(self, page_number: int) -> bool:
        return page_number in self.safe_boundaries


def test_small_chapters_can_merge():
    planner = SplitPlanner(FakeDocument(18), FakeAnalyzer({10}), max_pages=20, hard_max_pages=25)
    chapters = [
        ChapterNode("Chapter 1", 1, 10, 1),
        ChapterNode("Chapter 2", 11, 18, 1),
    ]
    plans = planner.plan(chapters)
    assert len(plans) == 1
    assert plans[0].split_mode == "merge"
    assert plans[0].start_page == 1
    assert plans[0].end_page == 18


def test_small_chapters_merge_until_minimum_page_budget():
    planner = SplitPlanner(FakeDocument(24), FakeAnalyzer(set(range(1, 25))), max_pages=20, hard_max_pages=25)
    chapters = [
        ChapterNode("前言", 1, 1, 1),
        ChapterNode("Chapter 1", 2, 6, 1),
        ChapterNode("Chapter 2", 7, 7, 1),
        ChapterNode("Chapter 3", 8, 10, 1),
        ChapterNode("Chapter 4", 11, 13, 1),
        ChapterNode("Chapter 5", 14, 15, 1),
    ]
    plans = planner.plan(chapters)
    assert [(plan.start_page, plan.end_page) for plan in plans] == [(1, 7), (7, 14), (14, 15)]
    assert plans[1].title == "Chapter 2 + Chapter 3 + Chapter 4"
    assert plans[0].overlap_pages == [7]
    assert plans[1].overlap_pages == [7, 14]
    assert plans[2].overlap_pages == [14]


def test_section_packing_can_float_to_hard_max_and_overlap_structural_start(monkeypatch):
    planner = SplitPlanner(FakeDocument(30), FakeAnalyzer(set(range(1, 31))), max_pages=20, hard_max_pages=25)
    chapter = ChapterNode("Chapter 8", 1, 26, 1)
    sections = [
        ChapterNode("8.1", 1, 10, 2),
        ChapterNode("8.2", 11, 20, 2),
        ChapterNode("8.3", 21, 23, 2),
        ChapterNode("8.4", 24, 26, 2),
    ]
    monkeypatch.setattr("pdf_slicer.split_planner.detect_sections", lambda document, current: sections)
    plans = planner.plan([chapter])
    assert [(plan.start_page, plan.end_page) for plan in plans] == [(1, 24), (24, 26)]
    assert plans[0].overlap_pages == [24]
    assert plans[1].overlap_pages == [24]


def test_large_chapter_uses_safe_boundaries():
    planner = SplitPlanner(FakeDocument(45), FakeAnalyzer({20, 40}), max_pages=20, hard_max_pages=25)
    chapters = [ChapterNode("Chapter 1", 1, 45, 1)]
    plans = planner.plan(chapters)
    assert [(plan.start_page, plan.end_page) for plan in plans] == [(1, 20), (21, 45)]


def test_planner_uses_oversized_fallback_when_no_safe_boundary_within_25():
    planner = SplitPlanner(FakeDocument(40), FakeAnalyzer({27}), max_pages=20, hard_max_pages=25)
    chapters = [ChapterNode("Chapter 1", 1, 40, 1)]
    plans = planner.plan(chapters)
    assert plans[0].end_page == 27
    assert plans[0].exception_type == "oversized_semantic_block"
    assert plans[0].manual_review_required is True
    assert plans[1].start_page == 28


def test_chapter_boundaries_prefer_overlap_over_pulling_next_slice_backward():
    planner = SplitPlanner(FakeDocument(30), FakeAnalyzer({22}), max_pages=20, hard_max_pages=25)
    chapters = [
        ChapterNode("Chapter 1", 1, 20, 1),
        ChapterNode("Chapter 2", 21, 30, 1),
    ]
    plans = planner.plan(chapters)
    assert [(plan.start_page, plan.end_page) for plan in plans] == [(1, 21), (21, 30)]
    assert plans[0].overlap_pages == [21]
    assert plans[1].overlap_pages == [21]


def test_non_chapter_boundaries_still_receive_semantic_adjustment():
    planner = SplitPlanner(FakeDocument(30), FakeAnalyzer({22}), max_pages=20, hard_max_pages=25)
    adjusted = planner._apply_semantic_boundary_pass(
        [
            SlicePlan("Section A", 1, 20, split_mode="section", boundary_reason="section_boundary"),
            SlicePlan("Section B", 21, 30, split_mode="section", boundary_reason="section_boundary"),
        ]
    )
    assert [(plan.start_page, plan.end_page) for plan in adjusted] == [(1, 22), (23, 30)]
    assert adjusted[0].boundary_reason == "semantic_integrity"
    assert adjusted[1].boundary_reason == "semantic_integrity"


def test_planner_clears_oversized_flags_after_boundary_adjustment_returns_within_limit():
    planner = SplitPlanner(FakeDocument(30), FakeAnalyzer({19}), max_pages=20, hard_max_pages=25)
    plans = planner._normalize_plan_flags(
        [
            SlicePlan(
                "Chapter 1",
                1,
                19,
                split_mode="section",
                boundary_reason="semantic_integrity",
                exception_type="oversized_semantic_block",
                manual_review_required=True,
            )
        ]
    )
    assert plans[0].actual_pages == 19
    assert plans[0].exception_type is None
    assert plans[0].manual_review_required is False


def test_planner_injects_overlap_page_when_next_page_mentions_previous_title():
    document = FakeDocument(25, texts={21: "Chapter 1 end Chapter 2 start"})
    planner = SplitPlanner(document, FakeAnalyzer({20}), max_pages=20, hard_max_pages=25)
    chapters = [
        ChapterNode("Chapter 1", 1, 20, 1),
        ChapterNode("Chapter 2", 21, 25, 1),
    ]
    plans = planner.plan(chapters)
    assert plans[0].end_page == 21
    assert plans[1].start_page == 21
    assert plans[0].overlap_pages == [21]
    assert plans[1].overlap_pages == [21]


def test_overlap_injection_marks_manual_review_when_hard_max_is_exceeded():
    document = FakeDocument(30, texts={26: "Chapter 1 recap Chapter 2 begins"})
    planner = SplitPlanner(document, FakeAnalyzer({25}), max_pages=20, hard_max_pages=25)
    plans = planner._inject_overlap_pages(
        [
            SlicePlan("Chapter 1", 1, 25, split_mode="physical", boundary_reason="semantic_integrity"),
            SlicePlan("Chapter 2", 26, 30, split_mode="chapter", boundary_reason="chapter_boundary"),
        ]
    )
    assert plans[0].end_page == 26
    assert plans[0].actual_pages == 26
    assert plans[0].manual_review_required is True
    assert plans[0].exception_type == "oversized_semantic_block"

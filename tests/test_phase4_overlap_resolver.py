from __future__ import annotations

import pytest
from pathlib import Path

from md_merge.overlap_resolver import resolve_overlaps, _match_blocks, _is_chapter_heading
from md_merge.provenance_loader import SliceProvenance, text_hash
from md_merge.merge_planner import AdjacentPair
from md_merge.contracts import MergeBlockRef, MergeTask, MergeWarning


def _task(tmp_path: Path, order: int, start: int = 1, end: int = 10, name: str = "", md_content: str = "") -> MergeTask:
    base = name or f"slice_{order}"
    d = tmp_path / base
    d.mkdir(exist_ok=True)
    md = d / f"{base}.md"
    md.write_text(md_content or f"# {base}\n", encoding="utf-8")
    return MergeTask(
        slice_file=f"{base}.pdf",
        display_title=base,
        order_index=order,
        start_page=start,
        end_page=end,
        input_dir=d,
        final_md_file=md,
        review_report_file=d / "review_report.json",
        assets_dir=None,
        manual_review_required=False,
    )


def _block(
    text: str = "Hello",
    block_type: str = "paragraph",
    page: int = 1,
    is_overlap: bool = False,
    dedupe_key: str | None = None,
    asset_ref: str | None = None,
) -> MergeBlockRef:
    return MergeBlockRef(
        source_page=page,
        block_type=block_type,
        is_overlap=is_overlap,
        dedupe_key=dedupe_key,
        normalized_text_hash=text_hash(text) if text else None,
        asset_ref=asset_ref,
        markdown=text,
    )


class TestMatchBlocks:
    def test_dedupe_key_match(self):
        a = _block("text", dedupe_key="dk1")
        b = _block("different", dedupe_key="dk1")
        assert _match_blocks(a, b) == "dedupe_key"

    def test_source_page_text_hash_match(self):
        a = _block("same text", page=5)
        b = _block("same text", page=5)
        assert _match_blocks(a, b) == "source_page_text_hash"

    def test_different_page_no_match(self):
        a = _block("same text", page=5)
        b = _block("same text", page=6)
        assert _match_blocks(a, b) == "none"

    def test_asset_ref_match(self):
        a = _block("img1", asset_ref="assets/img.png")
        b = _block("img2", asset_ref="assets/img.png")
        assert _match_blocks(a, b) == "asset_ref"

    def test_no_match(self):
        a = _block("hello")
        b = _block("world")
        assert _match_blocks(a, b) == "none"


class TestIsChapterHeading:
    def test_heading_at_start_page(self, tmp_path):
        task = _task(tmp_path, 2, start=11)
        block = _block("# Chapter 2", block_type="heading", page=11)
        assert _is_chapter_heading(block, task) is True

    def test_heading_not_at_start(self, tmp_path):
        task = _task(tmp_path, 2, start=11)
        block = _block("# Section", block_type="heading", page=13)
        assert _is_chapter_heading(block, task) is False

    def test_paragraph_not_protected(self, tmp_path):
        task = _task(tmp_path, 2, start=11)
        block = _block("some text", block_type="paragraph", page=11)
        assert _is_chapter_heading(block, task) is False

    def test_h3_not_protected(self, tmp_path):
        task = _task(tmp_path, 2, start=11)
        block = _block("### Section", block_type="heading", page=11)
        assert _is_chapter_heading(block, task) is False


class TestResolveOverlaps:
    def test_no_overlap(self, tmp_path):
        t1 = _task(tmp_path, 1, 1, 10, "s1", "# Ch1\n\nContent 1.\n")
        t2 = _task(tmp_path, 2, 11, 20, "s2", "# Ch2\n\nContent 2.\n")

        prov = {
            "s1.pdf": SliceProvenance(t1, [], [_block("Content 1.", page=10)], [_block("Content 1.", page=10)]),
            "s2.pdf": SliceProvenance(t2, [_block("# Ch2", block_type="heading", page=11)], [], [_block("# Ch2", block_type="heading", page=11)]),
        }
        pairs = [AdjacentPair(t1, t2, 0, 1)]
        warnings: list[MergeWarning] = []

        decisions, contents = resolve_overlaps([t1, t2], prov, pairs, warnings)
        assert len(decisions) == 1
        assert decisions[0].removed_count == 0

    def test_dedupe_key_dedup(self, tmp_path):
        overlap_text = "This is overlap content."
        t1 = _task(tmp_path, 1, 1, 10, "s1", f"# Ch1\n\n{overlap_text}\n")
        t2 = _task(tmp_path, 2, 10, 20, "s2", f"{overlap_text}\n\n# Ch2\n\nNew content.\n")

        left_block = _block(overlap_text, page=10, is_overlap=True, dedupe_key="dk1")
        right_block = _block(overlap_text, page=10, is_overlap=True, dedupe_key="dk1")
        chapter_heading = _block("# Ch2", block_type="heading", page=10)

        prov = {
            "s1.pdf": SliceProvenance(t1, [], [left_block], [left_block]),
            "s2.pdf": SliceProvenance(t2, [right_block, chapter_heading], [], [right_block, chapter_heading]),
        }
        pairs = [AdjacentPair(t1, t2, 0, 1)]
        warnings: list[MergeWarning] = []

        decisions, contents = resolve_overlaps([t1, t2], prov, pairs, warnings)
        assert decisions[0].removed_count == 1
        assert decisions[0].match_strategy == "dedupe_key"
        assert decisions[0].removed_from == "right_head"
        # Overlap text should be removed from right content
        assert overlap_text not in contents["s2.pdf"]

    def test_code_block_protected_as_unit(self, tmp_path):
        code = "```python\nprint('hello')\n```"
        t1 = _task(tmp_path, 1, 1, 10, "s1", f"# Ch1\n\n{code}\n")
        t2 = _task(tmp_path, 2, 10, 20, "s2", f"{code}\n\n# Ch2\n")

        left_block = _block(code, block_type="code", page=10, is_overlap=True, dedupe_key="code1")
        right_block = _block(code, block_type="code", page=10, is_overlap=True, dedupe_key="code1")

        prov = {
            "s1.pdf": SliceProvenance(t1, [], [left_block], [left_block]),
            "s2.pdf": SliceProvenance(t2, [right_block], [], [right_block]),
        }
        pairs = [AdjacentPair(t1, t2, 0, 1)]
        warnings: list[MergeWarning] = []

        decisions, contents = resolve_overlaps([t1, t2], prov, pairs, warnings)
        assert decisions[0].removed_count == 1
        # Code block fully removed from right, not truncated
        assert code not in contents["s2.pdf"]

    def test_repeated_overlap_heading_is_deduped(self, tmp_path):
        heading = "# 8.8.2 Confirm Order"
        t1 = _task(tmp_path, 1, 1, 23, "s1", f"{heading}\n\nBody.\n")
        t2 = _task(tmp_path, 2, 23, 23, "s2", f"{heading}\n\nMore body.\n")

        left_heading = _block(heading, block_type="heading", page=23, is_overlap=True, dedupe_key="h23")
        right_heading = _block(heading, block_type="heading", page=23, is_overlap=True, dedupe_key="h23")

        prov = {
            "s1.pdf": SliceProvenance(t1, [], [left_heading], [left_heading]),
            "s2.pdf": SliceProvenance(t2, [right_heading], [], [right_heading]),
        }
        pairs = [AdjacentPair(t1, t2, 0, 1)]
        warnings: list[MergeWarning] = []

        decisions, contents = resolve_overlaps([t1, t2], prov, pairs, warnings)

        assert decisions[0].removed_count == 1
        assert contents["s2.pdf"].count(heading) == 0

    def test_repeated_boundary_heading_with_markdown_fallback_is_deduped(self, tmp_path):
        left_heading_text = "### 8.8.2 Confirm Order"
        right_heading_text = "# 8.8.2 Confirm Order"
        t1 = _task(tmp_path, 1, 1, 23, "s1", f"{left_heading_text}\n\nBody.\n")
        t2 = _task(tmp_path, 2, 23, 23, "s2", f"{right_heading_text}\n\nMore body.\n")

        left_heading = _block(left_heading_text, block_type="heading", page=1)
        right_heading = _block(right_heading_text, block_type="heading", page=23)

        prov = {
            "s1.pdf": SliceProvenance(t1, [], [left_heading], [left_heading]),
            "s2.pdf": SliceProvenance(t2, [right_heading], [], [right_heading]),
        }
        pairs = [AdjacentPair(t1, t2, 0, 1)]
        warnings: list[MergeWarning] = []

        decisions, contents = resolve_overlaps([t1, t2], prov, pairs, warnings)

        assert decisions[0].removed_count == 1
        assert contents["s2.pdf"].count(right_heading_text) == 0

    def test_repeated_boundary_paragraph_with_markdown_fallback_is_deduped(self, tmp_path):
        paragraph = "Request Parameters:"
        t1 = _task(tmp_path, 1, 1, 23, "s1", f"{paragraph}\n")
        t2 = _task(tmp_path, 2, 23, 23, "s2", f"{paragraph}\n\nMore body.\n")

        left_block = _block(paragraph, block_type="paragraph", page=1)
        right_block = _block(paragraph, block_type="paragraph", page=23)

        prov = {
            "s1.pdf": SliceProvenance(t1, [], [left_block], [left_block]),
            "s2.pdf": SliceProvenance(t2, [right_block], [], [right_block]),
        }
        pairs = [AdjacentPair(t1, t2, 0, 1)]
        warnings: list[MergeWarning] = []

        decisions, contents = resolve_overlaps([t1, t2], prov, pairs, warnings)

        assert decisions[0].removed_count == 1
        assert contents["s2.pdf"].count(paragraph) == 0

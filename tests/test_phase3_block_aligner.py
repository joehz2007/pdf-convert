from __future__ import annotations

import pytest

from md_format.block_aligner import (
    AlignmentResult,
    MarkdownSegment,
    align_blocks,
    normalize_text,
    parse_markdown_segments,
    table_node_ref,
    image_node_ref,
)


# ---------------------------------------------------------------------------
# normalize_text
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_collapses_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_strips_leading_trailing(self):
        assert normalize_text("  hello  ") == "hello"

    def test_nfkc_normalization(self):
        # fullwidth A → normal A
        assert normalize_text("\uff21\uff22\uff23") == "ABC"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_tabs_and_newlines(self):
        assert normalize_text("hello\t\nworld") == "hello world"


# ---------------------------------------------------------------------------
# parse_markdown_segments
# ---------------------------------------------------------------------------


class TestParseMarkdownSegments:
    def test_heading(self):
        md = "# Hello World\n"
        segments = parse_markdown_segments(md)
        headings = [s for s in segments if s.segment_type == "heading"]
        assert len(headings) == 1
        assert headings[0].text == "Hello World"

    def test_paragraph(self):
        md = "This is a paragraph.\n"
        segments = parse_markdown_segments(md)
        paras = [s for s in segments if s.segment_type == "paragraph"]
        assert len(paras) == 1
        assert "This is a paragraph" in paras[0].text

    def test_bullet_list(self):
        md = "- item 1\n- item 2\n- item 3\n"
        segments = parse_markdown_segments(md)
        lists = [s for s in segments if s.segment_type == "list"]
        assert len(lists) == 1
        assert "item 1" in lists[0].text

    def test_ordered_list(self):
        md = "1. first\n2. second\n"
        segments = parse_markdown_segments(md)
        lists = [s for s in segments if s.segment_type == "list"]
        assert len(lists) == 1
        assert "first" in lists[0].text

    def test_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        segments = parse_markdown_segments(md)
        tables = [s for s in segments if s.segment_type == "table"]
        assert len(tables) == 1

    def test_code_fence(self):
        md = "```python\nprint('hello')\n```\n"
        segments = parse_markdown_segments(md)
        codes = [s for s in segments if s.segment_type == "code"]
        assert len(codes) == 1
        assert "print" in codes[0].text

    def test_image(self):
        md = "![alt text](assets/img01.png)\n"
        segments = parse_markdown_segments(md)
        images = [s for s in segments if s.segment_type == "image"]
        assert len(images) == 1
        assert images[0].text == "assets/img01.png"

    def test_html_block(self):
        md = "<div class='complex-table'>content</div>\n\n"
        segments = parse_markdown_segments(md)
        html = [s for s in segments if s.segment_type == "html_block"]
        assert len(html) == 1

    def test_mixed_content(self):
        md = "# Title\n\nParagraph text.\n\n- item\n\n| A |\n|---|\n| 1 |\n"
        segments = parse_markdown_segments(md)
        types = {s.segment_type for s in segments}
        assert "heading" in types
        assert "paragraph" in types
        assert "list" in types
        assert "table" in types

    def test_empty_markdown(self):
        segments = parse_markdown_segments("")
        assert segments == []

    def test_line_numbers_recorded(self):
        md = "# Title\n\nParagraph.\n"
        segments = parse_markdown_segments(md)
        assert segments[0].line_start == 0
        assert segments[0].line_end == 1


# ---------------------------------------------------------------------------
# align_blocks
# ---------------------------------------------------------------------------


def _make_content_data(blocks=None, tables=None, images=None, source_page=1):
    """Helper to build content.json-like data."""
    page = {"source_page": source_page, "blocks": blocks or [], "tables": tables or [], "images": images or []}
    return {"source_pages": [page]}


class TestAlignBlocks:
    def test_no_draft_marks_content_as_covered(self):
        content = _make_content_data(
            blocks=[{"dedupe_key": "blk1", "text": "Hello world"}],
            tables=[{"table_id": "t1", "headers": ["A", "B"]}],
            images=[{"asset_path": "assets/p0001_img01.png"}],
        )
        result = align_blocks(content, None)

        assert "blk1" in result.matched_blocks
        assert "table:1:0" in result.matched_tables
        assert "image:1:0" in result.matched_images
        assert result.unmatched_block_keys == []

    def test_exact_text_match(self):
        content = _make_content_data(blocks=[
            {"dedupe_key": "blk1", "text": "Hello world"},
        ])
        md = "Hello world\n"
        result = align_blocks(content, md)
        assert "blk1" in result.matched_blocks
        assert len(result.unmatched_block_keys) == 0

    def test_unmatched_block(self):
        content = _make_content_data(blocks=[
            {"dedupe_key": "blk1", "text": "This text is not in the markdown"},
        ])
        md = "Completely different content\n"
        result = align_blocks(content, md)
        assert "blk1" in result.unmatched_block_keys

    def test_fuzzy_match_by_word_overlap(self):
        content = _make_content_data(blocks=[
            {"dedupe_key": "blk1", "text": "The quick brown fox jumps over the lazy dog"},
        ])
        md = "The quick brown fox jumps over the lazy dog today\n"
        result = align_blocks(content, md)
        assert "blk1" in result.matched_blocks

    def test_table_matched_by_segment_type(self):
        content = _make_content_data(tables=[
            {"table_id": "t1", "headers": ["A", "B"]},
        ])
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        result = align_blocks(content, md)
        assert "table:1:0" in result.matched_tables

    def test_table_unmatched_no_table_in_md(self):
        content = _make_content_data(tables=[
            {"table_id": "t1", "headers": ["A", "B"]},
        ])
        md = "Just a paragraph.\n"
        result = align_blocks(content, md)
        assert "table:1:0" not in result.matched_tables

    def test_image_matched_by_asset_path(self):
        content = _make_content_data(images=[
            {"asset_path": "assets/p0001_img01.png"},
        ])
        md = "![image](assets/p0001_img01.png)\n"
        result = align_blocks(content, md)
        assert "image:1:0" in result.matched_images

    def test_image_matched_in_raw_markdown(self):
        content = _make_content_data(images=[
            {"asset_path": "assets/p0001_img01.png"},
        ])
        md = "Some text with assets/p0001_img01.png reference\n"
        result = align_blocks(content, md)
        assert "image:1:0" in result.matched_images

    def test_image_unmatched(self):
        content = _make_content_data(images=[
            {"asset_path": "assets/missing.png"},
        ])
        md = "No image here.\n"
        result = align_blocks(content, md)
        assert "image:1:0" not in result.matched_images

    def test_multiple_pages(self):
        content = {
            "source_pages": [
                {"source_page": 1, "blocks": [{"dedupe_key": "b1", "text": "Page one text"}], "tables": [], "images": []},
                {"source_page": 2, "blocks": [{"dedupe_key": "b2", "text": "Page two text"}], "tables": [], "images": []},
            ]
        }
        md = "Page one text\n\nPage two text\n"
        result = align_blocks(content, md)
        assert "b1" in result.matched_blocks
        assert "b2" in result.matched_blocks

    def test_short_text_matched_via_normalized_index(self):
        content = _make_content_data(blocks=[
            {"dedupe_key": "blk1", "text": "short"},
        ])
        md = "This is a short paragraph with more text.\n"
        result = align_blocks(content, md)
        # "short" is found as normalized text in segment_texts index via exact lookup
        assert "blk1" in result.matched_blocks

    def test_html_block_table_match(self):
        content = _make_content_data(tables=[
            {"table_id": "t1", "fallback_html": "<table>...</table>"},
        ])
        md = "<div class='complex-table'>content</div>\n\n"
        result = align_blocks(content, md)
        assert "table:1:0" in result.matched_tables


# ---------------------------------------------------------------------------
# Node ref helpers
# ---------------------------------------------------------------------------


class TestNodeRefHelpers:
    def test_table_node_ref(self):
        assert table_node_ref(1, 0) == "table:1:0"
        assert table_node_ref(5, 3) == "table:5:3"

    def test_image_node_ref(self):
        assert image_node_ref(1, 0) == "image:1:0"
        assert image_node_ref(10, 2) == "image:10:2"

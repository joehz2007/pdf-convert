from __future__ import annotations

import pytest

from md_format.block_aligner import align_blocks
from md_format.contracts import AutoFix, NormalizedDocument
from md_format.coverage_auditor import audit_coverage
from md_format.repair_engine import repair


def _make_task(**kwargs):
    """Build a minimal FormatTask-like object for testing."""
    from pathlib import Path
    from md_format.contracts import FormatTask
    defaults = {
        "slice_file": "test.pdf",
        "display_title": "Test",
        "order_index": 1,
        "input_dir": Path("."),
        "content_file": Path("content.json"),
        "draft_md_file": Path("test.md"),
        "assets_dir": Path("assets"),
        "phase2_manual_review_required": False,
        "start_page": 1,
        "end_page": 1,
    }
    defaults.update(kwargs)
    return FormatTask(**defaults)


def _make_content(blocks=None, tables=None, images=None, source_page=1, is_overlap=False):
    page = {
        "source_page": source_page,
        "slice_page": 1,
        "is_overlap": is_overlap,
        "blocks": blocks or [],
        "tables": tables or [],
        "images": images or [],
    }
    return {"source_pages": [page]}


def _run_repair(content, draft_md="Draft text.\n"):
    task = _make_task()
    audit_result = audit_coverage(content, draft_md)
    alignment = align_blocks(content, draft_md)
    return repair(task, content, draft_md, audit_result, alignment)


def _run_repair_no_heading(content, draft_md="Draft text.\n"):
    """Run repair with empty display_title to avoid H1 insertion."""
    task = _make_task(display_title="")
    audit_result = audit_coverage(content, draft_md)
    alignment = align_blocks(content, draft_md)
    return repair(task, content, draft_md, audit_result, alignment)


class TestRepairBasic:
    def test_returns_normalized_document(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Hello world", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, fixes = _run_repair_no_heading(content, "Hello world\n")
        assert isinstance(doc, NormalizedDocument)
        assert len(doc.pages) == 1
        assert len(doc.pages[0].blocks) == 1

    def test_paragraph_block_rendered(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Simple paragraph", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, _ = _run_repair_no_heading(content)
        block = doc.pages[0].blocks[0]
        assert block.markdown == "Simple paragraph"
        assert block.block_type == "paragraph"

    def test_heading_block_rendered(self):
        content = _make_content(blocks=[
            {"type": "heading", "text": "Chapter Title", "reading_order": 1, "dedupe_key": "h1"},
        ])
        doc, _ = _run_repair_no_heading(content)
        block = doc.pages[0].blocks[0]
        assert block.markdown.startswith("##")
        assert "Chapter Title" in block.markdown

    def test_list_item_rendered(self):
        content = _make_content(blocks=[
            {"type": "list_item", "text": "First item", "reading_order": 1, "dedupe_key": "l1"},
        ])
        doc, _ = _run_repair_no_heading(content)
        block = doc.pages[0].blocks[0]
        assert block.markdown == "- First item"

    def test_code_block_rendered(self):
        content = _make_content(blocks=[
            {"type": "code", "text": "print('hello')", "reading_order": 1, "dedupe_key": "c1"},
        ])
        doc, _ = _run_repair_no_heading(content)
        block = doc.pages[0].blocks[0]
        assert "```" in block.markdown
        assert "print('hello')" in block.markdown

    def test_blocks_sorted_by_reading_order(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Second", "reading_order": 2, "dedupe_key": "b2"},
            {"type": "paragraph", "text": "First", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, _ = _run_repair_no_heading(content)
        assert doc.pages[0].blocks[0].markdown == "First"
        assert doc.pages[0].blocks[1].markdown == "Second"

    def test_pages_sorted_by_source_page(self):
        content = {
            "source_pages": [
                {"source_page": 2, "slice_page": 2, "blocks": [
                    {"type": "paragraph", "text": "Page 2", "reading_order": 1, "dedupe_key": "b2"},
                ], "tables": [], "images": []},
                {"source_page": 1, "slice_page": 1, "blocks": [
                    {"type": "paragraph", "text": "Page 1", "reading_order": 1, "dedupe_key": "b1"},
                ], "tables": [], "images": []},
            ]
        }
        doc, _ = _run_repair(content)
        assert doc.pages[0].source_page == 1
        assert doc.pages[1].source_page == 2


class TestRepairTables:
    def test_table_with_markdown(self):
        content = _make_content(tables=[
            {"markdown": "| A | B |\n|---|---|\n| 1 | 2 |", "headers": ["A", "B"], "rows": [["1", "2"]]},
        ])
        doc, fixes = _run_repair(content)
        table_blocks = [b for b in doc.pages[0].blocks if b.block_type == "table"]
        assert len(table_blocks) == 1
        assert "| A | B |" in table_blocks[0].markdown

    def test_table_rebuilt_from_headers_rows(self):
        content = _make_content(tables=[
            {"markdown": "", "headers": ["Name", "Value"], "rows": [["a", "1"], ["b", "2"]]},
        ])
        doc, fixes = _run_repair(content)
        table_blocks = [b for b in doc.pages[0].blocks if b.block_type == "table"]
        assert len(table_blocks) == 1
        assert "| Name | Value |" in table_blocks[0].markdown
        assert "| --- | --- |" in table_blocks[0].markdown
        assert any(f.fix_type == "table_rebuilt" for f in fixes)

    def test_table_fallback_html(self):
        content = _make_content(tables=[
            {"markdown": "", "headers": [], "rows": [], "fallback_html": "<table><tr><td>X</td></tr></table>"},
        ])
        doc, fixes = _run_repair(content)
        table_blocks = [b for b in doc.pages[0].blocks if b.block_type == "table"]
        assert "<table>" in table_blocks[0].markdown
        assert any(f.fix_type == "table_fallback_html_applied" for f in fixes)

    def test_table_fallback_image(self):
        content = _make_content(tables=[
            {"markdown": "", "headers": [], "rows": [], "fallback_html": "", "fallback_image": "assets/table.png"},
        ])
        doc, fixes = _run_repair(content)
        table_blocks = [b for b in doc.pages[0].blocks if b.block_type == "table"]
        assert "assets/table.png" in table_blocks[0].markdown
        assert any(f.fix_type == "table_fallback_image_applied" for f in fixes)


class TestRepairImages:
    def test_image_with_asset_path(self):
        content = _make_content(images=[
            {"asset_path": "assets/img01.png", "caption": "Figure 1"},
        ])
        doc, _ = _run_repair(content)
        img_blocks = [b for b in doc.pages[0].blocks if b.block_type == "image"]
        assert len(img_blocks) == 1
        assert "![Figure 1](assets/img01.png)" in img_blocks[0].markdown

    def test_image_without_caption_uses_default(self):
        content = _make_content(images=[
            {"asset_path": "assets/img01.png", "caption": ""},
        ])
        doc, _ = _run_repair(content)
        img_blocks = [b for b in doc.pages[0].blocks if b.block_type == "image"]
        assert "![image](assets/img01.png)" in img_blocks[0].markdown

    def test_image_without_asset_path(self):
        content = _make_content(images=[
            {"asset_path": ""},
        ])
        doc, _ = _run_repair(content)
        img_blocks = [b for b in doc.pages[0].blocks if b.block_type == "image"]
        assert "<!-- image" in img_blocks[0].markdown


class TestRepairHeadings:
    def test_heading_level_jump_fixed(self):
        """Repair engine uses _block_to_markdown which gives ## for all headings.
        The _fix_heading_levels pass then normalizes jumps.
        We simulate a jump by manually setting levels in the NormalizedDocument.
        """
        from md_format.repair_engine import _fix_heading_levels
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf",
            display_title="Test",
            order_index=1,
            start_page=1,
            end_page=1,
            pages=[NormalizedPage(
                source_page=1,
                slice_page=1,
                is_overlap=False,
                blocks=[
                    NormalizedBlock("heading", 1, 1, "h1", "## Title", False),
                    NormalizedBlock("heading", 1, 2, "h2", "#### Sub-sub", False),
                ],
            )],
        )
        fixes = []
        _fix_heading_levels(doc, fixes)
        headings = doc.pages[0].blocks
        assert headings[0].markdown == "## Title"
        assert headings[1].markdown == "### Sub-sub"
        assert any(f.fix_type == "heading_normalized" for f in fixes)

    def test_same_level_headings_no_fix(self):
        content = _make_content(blocks=[
            {"type": "heading", "text": "A", "reading_order": 1, "dedupe_key": "h1"},
            {"type": "heading", "text": "B", "reading_order": 2, "dedupe_key": "h2"},
        ])
        doc, fixes = _run_repair(content)
        heading_fixes = [f for f in fixes if f.fix_type == "heading_normalized"]
        assert len(heading_fixes) == 0


class TestRepairOverlap:
    def test_overlap_page_preserved(self):
        content = _make_content(
            blocks=[{"type": "paragraph", "text": "Overlap content", "reading_order": 1, "dedupe_key": "ov1"}],
            is_overlap=True,
        )
        doc, _ = _run_repair_no_heading(content)
        assert doc.pages[0].is_overlap is True
        assert doc.pages[0].blocks[0].is_overlap is True


class TestRepairHeadingInserted:
    def test_heading_inserted_when_no_h1(self):
        content = _make_content(blocks=[
            {"type": "heading", "text": "Subtitle", "reading_order": 1, "dedupe_key": "h1"},
        ])
        task = _make_task(display_title="My Chapter")
        audit_result = audit_coverage(content, "## Subtitle\n")
        alignment = align_blocks(content, "## Subtitle\n")
        doc, fixes = repair(task, content, "## Subtitle\n", audit_result, alignment)
        # First block should be the inserted H1
        assert doc.pages[0].blocks[0].markdown == "# My Chapter"
        assert any(f.fix_type == "heading_inserted" for f in fixes)

    def test_heading_not_inserted_when_h1_exists(self):
        """If content already generates an H1 via _block_to_markdown (which uses ##),
        we need to manually test with a pre-existing H1."""
        from md_format.repair_engine import _fix_missing_top_heading
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("heading", 1, 1, "h1", "# Existing Title", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_missing_top_heading(doc, fixes)
        assert len(fixes) == 0
        assert len(doc.pages[0].blocks) == 1

    def test_heading_inserted_on_first_non_overlap_page(self):
        content = {
            "source_pages": [
                {"source_page": 1, "slice_page": 1, "is_overlap": True,
                 "blocks": [{"type": "paragraph", "text": "Overlap", "reading_order": 1, "dedupe_key": "ov1"}],
                 "tables": [], "images": []},
                {"source_page": 2, "slice_page": 2, "is_overlap": False,
                 "blocks": [{"type": "paragraph", "text": "Body", "reading_order": 1, "dedupe_key": "b1"}],
                 "tables": [], "images": []},
            ]
        }
        task = _make_task(display_title="Chapter X")
        audit_result = audit_coverage(content, "Draft\n")
        alignment = align_blocks(content, "Draft\n")
        doc, fixes = repair(task, content, "Draft\n", audit_result, alignment)
        # H1 should be on page 2 (non-overlap), not page 1 (overlap)
        h1_blocks = [b for b in doc.pages[1].blocks if b.markdown.startswith("# ")]
        assert len(h1_blocks) == 1
        assert h1_blocks[0].markdown == "# Chapter X"


class TestRepairMissingBlockRestored:
    def test_missing_block_marked_restored(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Found text", "reading_order": 1, "dedupe_key": "b1"},
            {"type": "paragraph", "text": "Missing text", "reading_order": 2, "dedupe_key": "b2"},
        ])
        # Draft only has the first block
        doc, fixes = _run_repair(content, "Found text\n")
        restored = [f for f in fixes if f.fix_type == "missing_block_restored"]
        assert len(restored) >= 1
        assert any(f.node_ref == "b2" for f in restored)

    def test_all_blocks_present_no_restore(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Hello", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, fixes = _run_repair(content, "Hello\n")
        assert not any(f.fix_type == "missing_block_restored" for f in fixes)


class TestRepairCodeFenceClosed:
    def test_unclosed_fence_gets_closed(self):
        from md_format.repair_engine import _fix_unclosed_code_fences
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("code", 1, 1, "c1", "```\nprint('hi')", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_unclosed_code_fences(doc, fixes)
        assert doc.pages[0].blocks[0].markdown.endswith("```")
        assert any(f.fix_type == "code_fence_closed" for f in fixes)

    def test_already_closed_fence_no_fix(self):
        from md_format.repair_engine import _fix_unclosed_code_fences
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("code", 1, 1, "c1", "```\nprint('hi')\n```", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_unclosed_code_fences(doc, fixes)
        assert len(fixes) == 0


class TestRepairListRebuilt:
    def test_list_items_get_proper_prefix(self):
        from md_format.repair_engine import _fix_broken_lists
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("list_item", 1, 1, "l1", "First item", False),
                NormalizedBlock("list_item", 1, 2, "l2", "- Second item", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_broken_lists(doc, fixes)
        assert doc.pages[0].blocks[0].markdown == "- First item"
        assert doc.pages[0].blocks[1].markdown == "- Second item"  # unchanged
        assert len(fixes) == 1  # only first was fixed


class TestRepairTableSeparator:
    def test_pipe_table_missing_separator(self):
        from md_format.repair_engine import _fix_table_separators
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("table", 1, 1, "t1", "| A | B |\n| 1 | 2 |", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_table_separators(doc, fixes)
        lines = doc.pages[0].blocks[0].markdown.splitlines()
        assert "---" in lines[1]
        assert any(f.fix_type == "table_separator_inserted" for f in fixes)

    def test_table_with_separator_no_fix(self):
        from md_format.repair_engine import _fix_table_separators
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("table", 1, 1, "t1", "| A | B |\n| --- | --- |\n| 1 | 2 |", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_table_separators(doc, fixes)
        assert len(fixes) == 0


class TestRepairImageCaptionFilled:
    def test_default_alt_replaced_with_caption(self):
        """Test _fix_image_captions directly: block has default alt, content_data has caption."""
        from md_format.repair_engine import _fix_image_captions
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("image", 1, 1, "image:1:0", "![image](assets/img.png)", False),
            ])],
        )
        content_data = _make_content(images=[
            {"asset_path": "assets/img.png", "caption": "Figure 1"},
        ])
        fixes: list[AutoFix] = []
        _fix_image_captions(doc, content_data, fixes)
        assert "![Figure 1](" in doc.pages[0].blocks[0].markdown
        assert any(f.fix_type == "image_caption_filled" for f in fixes)

    def test_existing_caption_not_replaced(self):
        content = _make_content(images=[
            {"asset_path": "assets/img.png", "caption": "Figure 1"},
        ])
        doc, fixes = _run_repair(content, "![Figure 1](assets/img.png)\n")
        img_blocks = [b for b in doc.pages[0].blocks if b.block_type == "image"]
        assert "![Figure 1](" in img_blocks[0].markdown
        # image_caption_filled should not fire because _image_to_markdown already used the caption
        assert not any(f.fix_type == "image_caption_filled" for f in fixes)


class TestRepairImageReferenceRestored:
    def test_missing_image_marked_restored(self):
        content = _make_content(images=[
            {"asset_path": "assets/img01.png", "caption": "Fig"},
        ])
        # Draft doesn't contain the image reference
        doc, fixes = _run_repair(content, "No images here.\n")
        assert any(f.fix_type == "image_reference_restored" for f in fixes)


class TestRepairOverlapBlockRestored:
    def test_overlap_blocks_marked_restored(self):
        content = _make_content(
            blocks=[{"type": "paragraph", "text": "Overlap text", "reading_order": 1, "dedupe_key": "ov1"}],
            is_overlap=True,
        )
        # Overlap page has empty markdown so auditor reports overlap_lost
        content["source_pages"][0]["markdown"] = ""
        doc, fixes = _run_repair(content, "Unrelated draft.\n")
        assert any(f.fix_type == "overlap_block_restored" for f in fixes)


class TestRepairParagraphMerged:
    def test_broken_paragraphs_merged(self):
        from md_format.repair_engine import _fix_broken_paragraphs
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("paragraph", 1, 1, "p1", "This is an incomplete", False),
                NormalizedBlock("paragraph", 1, 2, "p2", "sentence that continues here.", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_broken_paragraphs(doc, fixes)
        assert "incomplete sentence" in doc.pages[0].blocks[0].markdown
        assert doc.pages[0].blocks[1].markdown == ""
        assert any(f.fix_type == "paragraph_merged" for f in fixes)

    def test_complete_paragraphs_not_merged(self):
        from md_format.repair_engine import _fix_broken_paragraphs
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Test", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("paragraph", 1, 1, "p1", "First paragraph.", False),
                NormalizedBlock("paragraph", 1, 2, "p2", "Second paragraph.", False),
            ])],
        )
        fixes: list[AutoFix] = []
        _fix_broken_paragraphs(doc, fixes)
        assert doc.pages[0].blocks[0].markdown == "First paragraph."
        assert doc.pages[0].blocks[1].markdown == "Second paragraph."
        assert len(fixes) == 0


class TestRepairOrdering:
    def test_completeness_before_structural_before_style(self):
        """Verify fix ordering: heading_inserted before code_fence_closed before paragraph_merged."""
        from md_format.contracts import NormalizedBlock, NormalizedPage, NormalizedDocument
        from md_format.repair_engine import (
            _fix_missing_top_heading, _fix_unclosed_code_fences,
            _fix_broken_paragraphs, _fix_heading_levels,
        )

        doc = NormalizedDocument(
            slice_file="test.pdf", display_title="Chapter", order_index=1,
            start_page=1, end_page=1,
            pages=[NormalizedPage(1, 1, False, blocks=[
                NormalizedBlock("heading", 1, 1, "h1", "## Sub", False),
                NormalizedBlock("code", 1, 2, "c1", "```\ncode", False),
                NormalizedBlock("paragraph", 1, 3, "p1", "Broken text", False),
                NormalizedBlock("paragraph", 1, 4, "p2", "continues here.", False),
            ])],
        )
        all_fixes: list[AutoFix] = []
        _fix_missing_top_heading(doc, all_fixes)
        _fix_unclosed_code_fences(doc, all_fixes)
        _fix_heading_levels(doc, all_fixes)
        _fix_broken_paragraphs(doc, all_fixes)

        fix_types = [f.fix_type for f in all_fixes]
        # Completeness (heading_inserted) comes first
        assert fix_types[0] == "heading_inserted"
        # Then structural (code_fence_closed)
        assert "code_fence_closed" in fix_types
        # Then style (heading_normalized / paragraph_merged) comes after
        if "paragraph_merged" in fix_types:
            assert fix_types.index("code_fence_closed") < fix_types.index("paragraph_merged")


class TestRepairMetadata:
    def test_document_metadata(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Test", "reading_order": 1, "dedupe_key": "b1"},
        ])
        task = _make_task(display_title="My Chapter", start_page=5, end_page=10)
        audit_result = audit_coverage(content, "Test\n")
        alignment = align_blocks(content, "Test\n")
        doc, _ = repair(task, content, "Test\n", audit_result, alignment)

        assert doc.display_title == "My Chapter"
        assert doc.start_page == 5
        assert doc.end_page == 10
        assert "content_file" in doc.metadata


# ---------------------------------------------------------------------------
# Heading level hierarchy tests
# ---------------------------------------------------------------------------


class TestHeadingLevelHierarchy:
    """Test that heading levels are correctly detected and rendered."""

    def test_numbered_section_levels(self):
        """Section numbering: 1 → H1, 1.1 → H2, 1.1.1 → H3."""
        content = _make_content(blocks=[
            {"type": "heading", "text": "1 Introduction", "reading_order": 1, "dedupe_key": "h1", "heading_level": 1},
            {"type": "heading", "text": "1.1 Overview", "reading_order": 2, "dedupe_key": "h2", "heading_level": 2},
            {"type": "heading", "text": "1.1.1 Detail", "reading_order": 3, "dedupe_key": "h3", "heading_level": 3},
        ])
        doc, _ = _run_repair_no_heading(content)
        blocks = doc.pages[0].blocks
        assert blocks[0].markdown == "# 1 Introduction"
        assert blocks[1].markdown == "## 1.1 Overview"
        assert blocks[2].markdown == "### 1.1.1 Detail"

    def test_heading_level_from_draft_markdown(self):
        """Cross-reference draft markdown to recover heading levels."""
        draft = "# Main Title\n\n## 2.1 Section\n\nSome text.\n"
        content = _make_content(blocks=[
            {"type": "heading", "text": "Main Title", "reading_order": 1, "dedupe_key": "h1"},
            {"type": "heading", "text": "2.1 Section", "reading_order": 2, "dedupe_key": "h2"},
        ])
        doc, _ = _run_repair_no_heading(content, draft)
        blocks = doc.pages[0].blocks
        assert blocks[0].markdown == "# Main Title"
        assert blocks[1].markdown == "## 2.1 Section"

    def test_heading_level_section_numbering_fallback(self):
        """When no heading_level in content.json and no draft match, use section numbering."""
        content = _make_content(blocks=[
            {"type": "heading", "text": "3.2.1 Sub Section", "reading_order": 1, "dedupe_key": "h1"},
        ])
        doc, _ = _run_repair_no_heading(content)
        assert doc.pages[0].blocks[0].markdown == "### 3.2.1 Sub Section"

    def test_chinese_chapter_heading(self):
        """Chinese chapter marker: 第X章 → H1."""
        content = _make_content(blocks=[
            {"type": "heading", "text": "第三章 支付接口", "reading_order": 1, "dedupe_key": "h1", "heading_level": 1},
        ])
        doc, _ = _run_repair_no_heading(content)
        assert doc.pages[0].blocks[0].markdown == "# 第三章 支付接口"

    def test_promote_matching_heading_to_h1(self):
        """When display_title matches an existing heading, promote it instead of inserting."""
        content = _make_content(blocks=[
            {"type": "heading", "text": "3.2 Payment API", "reading_order": 1, "dedupe_key": "h1", "heading_level": 2},
            {"type": "paragraph", "text": "Some content.", "reading_order": 2, "dedupe_key": "p1"},
        ])
        task = _make_task(display_title="3.2 Payment API")
        audit_result = audit_coverage(content, "Some content.\n")
        alignment = align_blocks(content, "Some content.\n")
        doc, fixes = repair(task, content, "Some content.\n", audit_result, alignment)
        # The heading should be promoted to H1, not a new block inserted
        headings = [b for b in doc.pages[0].blocks if b.block_type == "heading"]
        assert headings[0].markdown == "# 3.2 Payment API"
        # Should be exactly one heading_inserted fix (promotion)
        assert sum(1 for f in fixes if f.fix_type == "heading_inserted") == 1


# ---------------------------------------------------------------------------
# Code block recovery tests
# ---------------------------------------------------------------------------


class TestCodeBlockRecovery:
    """Test code block recovery from draft markdown fences."""

    def test_paragraph_reclassified_as_code(self):
        """Paragraph block matching draft code fence is reclassified as code."""
        draft = "Some text.\n\n```\ncurl -X POST /api/v1/pay\n```\n"
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Some text.", "reading_order": 1, "dedupe_key": "p1"},
            {"type": "paragraph", "text": "curl -X POST /api/v1/pay", "reading_order": 2, "dedupe_key": "p2"},
        ])
        doc, fixes = _run_repair_no_heading(content, draft)
        code_blocks = [b for b in doc.pages[0].blocks if b.block_type == "code"]
        assert len(code_blocks) == 1
        assert "curl -X POST" in code_blocks[0].markdown
        assert "```" in code_blocks[0].markdown
        assert any(f.fix_type == "code_block_rebuilt" for f in fixes)

    def test_already_code_block_not_double_wrapped(self):
        """Blocks already classified as code are not re-wrapped."""
        draft = "```\nprint('hello')\n```\n"
        content = _make_content(blocks=[
            {"type": "code", "text": "print('hello')", "reading_order": 1, "dedupe_key": "c1"},
        ])
        doc, fixes = _run_repair_no_heading(content, draft)
        block = doc.pages[0].blocks[0]
        assert block.block_type == "code"
        # Should have exactly one pair of ``` fences, not double
        assert block.markdown.count("```") == 2

    def test_short_text_not_reclassified(self):
        """Very short paragraph text is not reclassified as code."""
        draft = "```\nx = 1\n```\n"
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "x = 1", "reading_order": 1, "dedupe_key": "p1"},
        ])
        doc, _ = _run_repair_no_heading(content, draft)
        block = doc.pages[0].blocks[0]
        # "x = 1" is only 5 chars, below the 8-char threshold
        assert block.block_type == "paragraph"


# ---------------------------------------------------------------------------
# Table quality tests
# ---------------------------------------------------------------------------


class TestTableQuality:
    """Test table corruption detection and fallback logic."""

    def test_corrupted_markdown_uses_image_fallback(self):
        """When table markdown has broken words, prefer image fallback."""
        content = _make_content(tables=[{
            "type": "table",
            "source_page": 1,
            "bbox": [0, 0, 100, 50],
            "headers": ["Field", "Type"],
            "rows": [["name", "string"]],
            "markdown": "| Fie<br>ld | Ty<br>pe |\n| --- | --- |\n| na<br>me | str<br>ing |",
            "fallback_html": None,
            "fallback_image": "assets/table_p1.png",
            "table_id": "t1",
            "table_role": "standalone",
        }])
        doc, fixes = _run_repair_no_heading(content)
        table_blocks = [b for b in doc.pages[0].blocks if b.block_type == "table"]
        assert len(table_blocks) == 1
        assert "![Table](" in table_blocks[0].markdown
        assert any(f.fix_type == "table_fallback_image_applied" for f in fixes)

    def test_clean_markdown_used_directly(self):
        """Clean table markdown is used without triggering fallback."""
        content = _make_content(tables=[{
            "type": "table",
            "source_page": 1,
            "bbox": [0, 0, 100, 50],
            "headers": ["Field", "Type"],
            "rows": [["name", "string"]],
            "markdown": "| Field | Type |\n| --- | --- |\n| name | string |",
            "fallback_html": None,
            "fallback_image": None,
            "table_id": "t1",
            "table_role": "standalone",
        }])
        doc, fixes = _run_repair_no_heading(content)
        table_blocks = [b for b in doc.pages[0].blocks if b.block_type == "table"]
        assert "| Field | Type |" in table_blocks[0].markdown
        assert not any(f.fix_type == "table_fallback_image_applied" for f in fixes)

    def test_rebuild_pipe_table_handles_none_cells(self):
        """_rebuild_pipe_table handles None values in cells."""
        from md_format.repair_engine import _rebuild_pipe_table
        result = _rebuild_pipe_table(["A", "B"], [[None, "val"], ["x", None]])
        assert "| A | B |" in result
        assert "|  | val |" in result
        assert "| x |  |" in result

    def test_rebuild_pipe_table_handles_newlines(self):
        """_rebuild_pipe_table converts newlines to <br>."""
        from md_format.repair_engine import _rebuild_pipe_table
        result = _rebuild_pipe_table(["Header"], [["line1\nline2"]])
        assert "line1<br>line2" in result


# ---------------------------------------------------------------------------
# Phase 2 heading level detection tests
# ---------------------------------------------------------------------------


class TestPhase2HeadingLevel:
    """Test detect_heading_level from metadata_builder."""

    def test_numbered_sections(self):
        from pdf_extract.metadata_builder import detect_heading_level
        assert detect_heading_level("1 Introduction") == 1
        assert detect_heading_level("1.2 Setup") == 2
        assert detect_heading_level("1.2.3 Config") == 3
        assert detect_heading_level("1.2.3.4 Advanced") == 4

    def test_chinese_markers(self):
        from pdf_extract.metadata_builder import detect_heading_level
        assert detect_heading_level("第一章 概述") == 1
        assert detect_heading_level("第二节 接口说明") == 2
        assert detect_heading_level("附录A 错误码") == 1

    def test_alpha_numbered(self):
        from pdf_extract.metadata_builder import detect_heading_level
        assert detect_heading_level("A1 Appendix Section") == 1
        assert detect_heading_level("A1.2 Subsection") == 2

    def test_font_size_fallback(self):
        from pdf_extract.metadata_builder import detect_heading_level
        assert detect_heading_level("Big Title", font_size=20, max_font_size=20) == 1
        assert detect_heading_level("Medium Title", font_size=17, max_font_size=20) == 2
        assert detect_heading_level("Small Title", font_size=14, max_font_size=20) == 3

    def test_default_level(self):
        from pdf_extract.metadata_builder import detect_heading_level
        assert detect_heading_level("Unknown Heading") == 2

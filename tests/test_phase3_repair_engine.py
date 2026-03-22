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


class TestRepairBasic:
    def test_returns_normalized_document(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Hello world", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, fixes = _run_repair(content, "Hello world\n")
        assert isinstance(doc, NormalizedDocument)
        assert len(doc.pages) == 1
        assert len(doc.pages[0].blocks) == 1

    def test_paragraph_block_rendered(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Simple paragraph", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, _ = _run_repair(content)
        block = doc.pages[0].blocks[0]
        assert block.markdown == "Simple paragraph"
        assert block.block_type == "paragraph"

    def test_heading_block_rendered(self):
        content = _make_content(blocks=[
            {"type": "heading", "text": "Chapter Title", "reading_order": 1, "dedupe_key": "h1"},
        ])
        doc, _ = _run_repair(content)
        block = doc.pages[0].blocks[0]
        assert block.markdown.startswith("##")
        assert "Chapter Title" in block.markdown

    def test_list_item_rendered(self):
        content = _make_content(blocks=[
            {"type": "list_item", "text": "First item", "reading_order": 1, "dedupe_key": "l1"},
        ])
        doc, _ = _run_repair(content)
        block = doc.pages[0].blocks[0]
        assert block.markdown == "- First item"

    def test_code_block_rendered(self):
        content = _make_content(blocks=[
            {"type": "code", "text": "print('hello')", "reading_order": 1, "dedupe_key": "c1"},
        ])
        doc, _ = _run_repair(content)
        block = doc.pages[0].blocks[0]
        assert "```" in block.markdown
        assert "print('hello')" in block.markdown

    def test_blocks_sorted_by_reading_order(self):
        content = _make_content(blocks=[
            {"type": "paragraph", "text": "Second", "reading_order": 2, "dedupe_key": "b2"},
            {"type": "paragraph", "text": "First", "reading_order": 1, "dedupe_key": "b1"},
        ])
        doc, _ = _run_repair(content)
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
        doc, _ = _run_repair(content)
        assert doc.pages[0].is_overlap is True
        assert doc.pages[0].blocks[0].is_overlap is True


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

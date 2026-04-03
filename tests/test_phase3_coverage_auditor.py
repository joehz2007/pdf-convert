from __future__ import annotations

import pytest

from md_format.coverage_auditor import AuditResult, audit_coverage


def _make_content(blocks=None, tables=None, images=None, source_page=1, is_overlap=False):
    """Build a minimal content.json dict with one source page."""
    page = {
        "source_page": source_page,
        "is_overlap": is_overlap,
        "blocks": blocks or [],
        "tables": tables or [],
        "images": images or [],
    }
    return {"source_pages": [page]}


# ---------------------------------------------------------------------------
# Block coverage
# ---------------------------------------------------------------------------


class TestBlockCoverage:
    def test_all_blocks_matched(self):
        content = _make_content(blocks=[
            {"dedupe_key": "b1", "text": "Hello world paragraph"},
            {"dedupe_key": "b2", "text": "Another paragraph here"},
        ])
        md = "Hello world paragraph\n\nAnother paragraph here\n"
        result = audit_coverage(content, md)

        assert result.coverage.text_blocks_expected == 2
        assert result.coverage.text_blocks_matched == 2
        assert not any(i.issue_type == "missing_block" for i in result.issues)

    def test_missing_block_generates_warning(self):
        content = _make_content(blocks=[
            {"dedupe_key": "b1", "text": "Present in markdown"},
            {"dedupe_key": "b2", "text": "This text is completely absent from draft"},
        ])
        md = "Present in markdown\n"
        result = audit_coverage(content, md)

        assert result.coverage.text_blocks_expected == 2
        assert result.coverage.text_blocks_matched == 1
        missing = [i for i in result.issues if i.issue_type == "missing_block"]
        assert len(missing) == 1
        assert missing[0].severity == "warning"
        assert missing[0].node_ref == "b2"
        assert missing[0].auto_fixable is True

    def test_no_blocks_no_issues(self):
        content = _make_content(blocks=[])
        md = "Some draft text\n"
        result = audit_coverage(content, md)

        assert result.coverage.text_blocks_expected == 0
        assert result.coverage.text_blocks_matched == 0
        assert not any(i.issue_type == "missing_block" for i in result.issues)

    def test_no_draft_uses_content_as_baseline(self):
        content = _make_content(blocks=[
            {"dedupe_key": "b1", "text": "Present only in content"},
        ])
        result = audit_coverage(content, None)

        assert result.coverage.text_blocks_expected == 1
        assert result.coverage.text_blocks_matched == 1
        assert not any(i.issue_type == "missing_block" for i in result.issues)


# ---------------------------------------------------------------------------
# Table coverage
# ---------------------------------------------------------------------------


class TestTableCoverage:
    def test_table_matched(self):
        content = _make_content(tables=[
            {"table_id": "t1", "headers": ["Col A", "Col B"]},
        ])
        md = "| Col A | Col B |\n|---|---|\n| 1 | 2 |\n"
        result = audit_coverage(content, md)

        assert result.coverage.tables_expected == 1
        assert result.coverage.tables_matched == 1
        assert not any(i.issue_type == "table_render_failed" for i in result.issues)

    def test_missing_table_without_fallback_is_error(self):
        content = _make_content(tables=[
            {"table_id": "t1", "headers": ["A"]},
        ])
        md = "No table here.\n"
        result = audit_coverage(content, md)

        assert result.coverage.tables_expected == 1
        assert result.coverage.tables_matched == 0
        issues = [i for i in result.issues if i.issue_type == "table_render_failed"]
        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].auto_fixable is False

    def test_missing_table_with_fallback_is_warning(self):
        content = _make_content(tables=[
            {"table_id": "t1", "headers": ["A"], "fallback_html": "<table>...</table>"},
        ])
        md = "No table here.\n"
        result = audit_coverage(content, md)

        issues = [i for i in result.issues if i.issue_type == "table_render_failed"]
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].auto_fixable is True

    def test_missing_table_with_fallback_image(self):
        content = _make_content(tables=[
            {"table_id": "t1", "headers": ["A"], "fallback_image": "assets/table.png"},
        ])
        md = "No table here.\n"
        result = audit_coverage(content, md)

        issues = [i for i in result.issues if i.issue_type == "table_render_failed"]
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].auto_fixable is True


# ---------------------------------------------------------------------------
# Image coverage
# ---------------------------------------------------------------------------


class TestImageCoverage:
    def test_image_matched(self):
        content = _make_content(images=[
            {"asset_path": "assets/p0001_img01.png"},
        ])
        md = "![image](assets/p0001_img01.png)\n"
        result = audit_coverage(content, md)

        assert result.coverage.images_expected == 1
        assert result.coverage.images_matched == 1
        assert not any(i.issue_type == "image_reference_missing" for i in result.issues)

    def test_image_missing(self):
        content = _make_content(images=[
            {"asset_path": "assets/missing.png"},
        ])
        md = "No image reference.\n"
        result = audit_coverage(content, md)

        assert result.coverage.images_expected == 1
        assert result.coverage.images_matched == 0
        issues = [i for i in result.issues if i.issue_type == "image_reference_missing"]
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].auto_fixable is True

    def test_image_with_empty_asset_path_generates_issue(self):
        content = _make_content(images=[
            {"asset_path": ""},
        ])
        md = "Some text.\n"
        result = audit_coverage(content, md)

        assert result.coverage.images_expected == 1
        # Empty asset_path still generates a missing image issue from the auditor
        issues = [i for i in result.issues if i.issue_type == "image_reference_missing"]
        assert len(issues) == 1


# ---------------------------------------------------------------------------
# Overlap page coverage
# ---------------------------------------------------------------------------


class TestOverlapCoverage:
    def test_overlap_page_counted(self):
        content = {
            "source_pages": [
                {
                    "source_page": 5,
                    "is_overlap": True,
                    "markdown": "Overlap content here",
                    "blocks": [],
                    "tables": [],
                    "images": [],
                },
            ]
        }
        md = "Some draft.\n"
        result = audit_coverage(content, md)

        assert result.coverage.overlap_pages_expected == 1
        assert result.coverage.overlap_pages_matched == 1

    def test_overlap_page_empty_generates_issue(self):
        content = {
            "source_pages": [
                {
                    "source_page": 5,
                    "is_overlap": True,
                    "markdown": "",
                    "blocks": [],
                    "tables": [],
                    "images": [],
                },
            ]
        }
        md = "Draft text.\n"
        result = audit_coverage(content, md)

        assert result.coverage.overlap_pages_expected == 1
        assert result.coverage.overlap_pages_matched == 0
        issues = [i for i in result.issues if i.issue_type == "overlap_lost"]
        assert len(issues) == 1
        assert issues[0].source_page == 5


# ---------------------------------------------------------------------------
# AuditResult structure
# ---------------------------------------------------------------------------


class TestAuditResultStructure:
    def test_returns_audit_result(self):
        content = _make_content()
        result = audit_coverage(content, "text\n")
        assert isinstance(result, AuditResult)
        assert result.coverage is not None
        assert isinstance(result.issues, list)

    def test_multi_page_coverage(self):
        content = {
            "source_pages": [
                {"source_page": 1, "blocks": [{"dedupe_key": "b1", "text": "First page block"}], "tables": [], "images": []},
                {"source_page": 2, "blocks": [{"dedupe_key": "b2", "text": "Second page block"}], "tables": [], "images": []},
            ]
        }
        md = "First page block\n\nSecond page block\n"
        result = audit_coverage(content, md)

        assert result.coverage.text_blocks_expected == 2
        assert result.coverage.text_blocks_matched == 2

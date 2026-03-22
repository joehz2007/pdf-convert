from __future__ import annotations

import json
from pathlib import Path

import pytest

from md_format.contracts import (
    AutoFix,
    AuditIssue,
    CoverageStats,
    FormatResult,
    FormatTask,
    ReviewReport,
)
from md_format.writer import (
    build_failure_result,
    build_skipped_result,
    prepare_output_dir,
    resolve_output_dir,
    rewrite_asset_paths,
    slice_output_dir,
    write_format_manifest,
    write_slice_result,
)
from md_format.errors import OutputExistsError


def _make_task(tmp_path, display_title="Test Chapter", order_index=1):
    slice_dir = tmp_path / "input" / f"{order_index:03d}-{display_title}"
    slice_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = slice_dir / "assets"
    assets_dir.mkdir(exist_ok=True)
    content_file = slice_dir / "content.json"
    content_file.write_text("{}", encoding="utf-8")
    draft_md = slice_dir / "test.md"
    draft_md.write_text("# Test\n", encoding="utf-8")
    return FormatTask(
        slice_file="test.pdf",
        display_title=display_title,
        order_index=order_index,
        input_dir=slice_dir,
        content_file=content_file,
        draft_md_file=draft_md,
        assets_dir=assets_dir,
        phase2_manual_review_required=False,
        start_page=1,
        end_page=5,
    )


def _make_report():
    return ReviewReport(
        slice_file="test.pdf",
        final_md_file="test.md",
        created_at="2026-03-22T00:00:00Z",
        status="success",
        manual_review_required=False,
        coverage=CoverageStats(text_blocks_expected=5, text_blocks_matched=5),
        formatted_stats={"char_count": 100, "block_count": 5, "table_count": 0, "image_count": 0},
        issues=[],
        auto_fixes=[
            AutoFix(fix_type="heading_normalized", source_page=1, node_ref="h1", message="Fixed"),
        ],
        warnings=[],
    )


class TestResolveOutputDir:
    def test_default_output_dir(self):
        result = resolve_output_dir(Path("/data/book_extract"), None)
        assert str(result).endswith("book_format")

    def test_explicit_output_dir(self):
        result = resolve_output_dir(Path("/data/book_extract"), "/output/custom")
        assert str(result) == str(Path("/output/custom"))


class TestPrepareOutputDir:
    def test_creates_new_dir(self, tmp_path):
        out = tmp_path / "new_output"
        result = prepare_output_dir(out, overwrite=False)
        assert result.exists()

    def test_overwrite_false_raises(self, tmp_path):
        out = tmp_path / "existing"
        out.mkdir()
        with pytest.raises(OutputExistsError):
            prepare_output_dir(out, overwrite=False)

    def test_overwrite_true_recreates(self, tmp_path):
        out = tmp_path / "existing"
        out.mkdir()
        (out / "old.txt").write_text("old")
        result = prepare_output_dir(out, overwrite=True)
        assert result.exists()
        assert not (out / "old.txt").exists()


class TestSliceOutputDir:
    def test_dir_name_format(self, tmp_path):
        task = _make_task(tmp_path, "Chapter One", order_index=3)
        result = slice_output_dir(tmp_path / "output", task)
        assert result.name == "003-Chapter One"

    def test_illegal_chars_replaced(self, tmp_path):
        # Test _safe_dirname logic directly via slice_output_dir
        from md_format.writer import _safe_dirname
        assert "/" not in _safe_dirname("A/B:C")
        assert ":" not in _safe_dirname("A/B:C")
        assert _safe_dirname("A/B:C") == "A_B_C"


class TestWriteSliceResult:
    def test_writes_md_and_report(self, tmp_path):
        task = _make_task(tmp_path)
        report = _make_report()
        output_root = tmp_path / "output"
        output_root.mkdir()

        result = write_slice_result(
            output_root, task, "# Final\n\nContent.\n", report,
            copy_assets=True, stage_timings={"total_ms": 10},
        )

        assert result.status == "success"
        assert result.slice_file == "test.pdf"
        assert result.display_title == "Test Chapter"
        assert result.start_page == 1
        assert result.end_page == 5
        assert result.auto_fixed_count == 1

        # Check files exist
        out_dir = output_root / "001-Test Chapter"
        assert (out_dir / "test.md").exists()
        assert (out_dir / "review_report.json").exists()

        # Check md content
        md_text = (out_dir / "test.md").read_text(encoding="utf-8")
        assert "# Final" in md_text

        # Check report content
        report_data = json.loads((out_dir / "review_report.json").read_text(encoding="utf-8"))
        assert report_data["status"] == "success"
        assert report_data["coverage"]["text_blocks_expected"] == 5

    def test_copy_assets_true(self, tmp_path):
        task = _make_task(tmp_path)
        (task.assets_dir / "img.png").write_bytes(b"fake-png")
        report = _make_report()
        output_root = tmp_path / "output"
        output_root.mkdir()

        result = write_slice_result(
            output_root, task, "Text\n", report,
            copy_assets=True, stage_timings={},
        )

        assert result.asset_mode == "copy"
        out_assets = output_root / "001-Test Chapter" / "assets" / "img.png"
        assert out_assets.exists()

    def test_copy_assets_false(self, tmp_path):
        task = _make_task(tmp_path)
        (task.assets_dir / "img.png").write_bytes(b"fake-png")
        report = _make_report()
        output_root = tmp_path / "output"
        output_root.mkdir()

        result = write_slice_result(
            output_root, task, "![alt](assets/img.png)\n", report,
            copy_assets=False, stage_timings={},
        )

        assert result.asset_mode == "reuse_phase2"
        # Assets not copied
        out_assets = output_root / "001-Test Chapter" / "assets"
        assert not out_assets.exists()

    def test_formatted_stats(self, tmp_path):
        task = _make_task(tmp_path)
        report = _make_report()
        output_root = tmp_path / "output"
        output_root.mkdir()

        result = write_slice_result(
            output_root, task, "Content\n", report,
            copy_assets=True, stage_timings={},
        )

        assert result.formatted_char_count == 100
        assert result.formatted_block_count == 5


class TestBuildSkippedResult:
    def test_skipped_result(self):
        raw = {"slice_file": "fail.pdf", "manual_review_required": False}
        result = build_skipped_result(raw, order_index=3)
        assert result.status == "skipped_upstream_failed"
        assert result.slice_file == "fail.pdf"
        assert result.order_index == 3
        assert result.final_md_file is None


class TestBuildFailureResult:
    def test_failure_result(self, tmp_path):
        task = _make_task(tmp_path)
        result = build_failure_result(
            task,
            elapsed_ms=50,
            error_code="test_error",
            error_message="something failed",
            stage_timings={"total_ms": 50},
        )
        assert result.status == "failed"
        assert result.error_code == "test_error"
        assert result.manual_review_required is True
        assert result.elapsed_ms == 50


class TestWriteFormatManifest:
    def test_writes_manifest_json(self, tmp_path):
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        raw_manifest = {"source_file": "book.pdf"}
        results = [
            FormatResult(
                slice_file="ch1.pdf", final_md_file="001/ch1.md",
                review_report_file="001/review.json", status="success",
                warning_count=1, issue_count=2, auto_fixed_count=1,
                manual_review_required=False, elapsed_ms=100,
                display_title="Ch1", order_index=1, start_page=1, end_page=5,
            ),
            FormatResult(
                slice_file="ch2.pdf", final_md_file=None,
                review_report_file=None, status="failed",
                warning_count=0, issue_count=0, auto_fixed_count=0,
                manual_review_required=True, elapsed_ms=10,
                display_title="Ch2", order_index=2,
            ),
        ]

        manifest = write_format_manifest(
            output_dir, raw_manifest, results,
            total_elapsed_ms=200, run_timings={"manifest_load_ms": 5},
        )

        assert manifest.total_slices == 2
        assert manifest.success_count == 1
        assert manifest.failed_count == 1
        assert manifest.manual_review_count == 1
        assert manifest.total_issue_count == 2
        assert manifest.total_auto_fixed_count == 1
        assert manifest.total_elapsed_ms == 200
        assert manifest.timings["manifest_load_ms"] == 5

        # Check file
        manifest_path = output_dir / "format_manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["source_file"] == "book.pdf"
        assert len(data["slices"]) == 2


class TestRewriteAssetPaths:
    def test_rewrites_markdown_image(self, tmp_path):
        assets_dir = tmp_path / "input" / "001" / "assets"
        assets_dir.mkdir(parents=True)
        output_dir = tmp_path / "output" / "001"

        md = "![alt](assets/img.png)\n"
        result = rewrite_asset_paths(md, assets_dir, output_dir)

        # Original "assets/img.png" should be replaced with a relative path
        # that includes the Phase 2 directory
        assert "img.png" in result
        assert "![alt](" in result
        # Should not start with just "assets/" anymore
        assert result != md

    def test_rewrites_html_img_src(self, tmp_path):
        assets_dir = tmp_path / "input" / "001" / "assets"
        assets_dir.mkdir(parents=True)
        output_dir = tmp_path / "output" / "001"

        md = '<img src="assets/fig.jpg" alt="x">\n'
        result = rewrite_asset_paths(md, assets_dir, output_dir)

        assert 'src="assets/fig.jpg"' not in result
        assert "fig.jpg" in result

    def test_no_change_when_no_assets(self, tmp_path):
        md = "Just text, no images.\n"
        result = rewrite_asset_paths(md, tmp_path / "nonexistent", tmp_path)
        assert result == md

    def test_multiple_images_rewritten(self, tmp_path):
        assets_dir = tmp_path / "input" / "001" / "assets"
        assets_dir.mkdir(parents=True)
        output_dir = tmp_path / "output" / "001"

        md = "![a](assets/a.png)\n\n![b](assets/b.png)\n"
        result = rewrite_asset_paths(md, assets_dir, output_dir)

        # Both images should be rewritten
        assert "a.png" in result
        assert "b.png" in result
        assert result != md

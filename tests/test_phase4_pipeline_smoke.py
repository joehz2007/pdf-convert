from __future__ import annotations

import json
import pytest
from pathlib import Path

from md_merge.pipeline import run_pipeline
from md_merge.errors import OutputExistsError


def _build_phase3_output(root: Path, slices: list[dict] | None = None) -> Path:
    """Build a minimal Phase 3 output directory."""
    if slices is None:
        slices = [
            {"title": "第一章 概述", "order": 1, "start": 1, "end": 10,
             "content": "# 第一章 概述\n\n这是第一章的内容。\n\nOverlap text here.\n"},
            {"title": "第二章 设计", "order": 2, "start": 9, "end": 20,
             "content": "Overlap text here.\n\n# 第二章 设计\n\n这是第二章的内容。\n"},
        ]

    format_dir = root / "book_format"
    format_dir.mkdir(parents=True, exist_ok=True)

    manifest_slices = []
    for s in slices:
        dir_name = f"{s['order']:03d}-{s['title']}"
        sdir = format_dir / dir_name
        sdir.mkdir(parents=True, exist_ok=True)

        md_name = f"{s['title']}（{s['start']}-{s['end']}）.md"
        (sdir / md_name).write_text(s["content"], encoding="utf-8")
        (sdir / "review_report.json").write_text(json.dumps({
            "slice_file": f"{s['title']}.pdf",
            "status": "success",
            "manual_review_required": False,
        }), encoding="utf-8")

        # Create assets dir if content has images
        if "assets/" in s["content"]:
            assets = sdir / "assets"
            assets.mkdir(exist_ok=True)
            (assets / "img01.png").write_bytes(b"FAKE_PNG")

        manifest_slices.append({
            "slice_file": f"{s['title']}.pdf",
            "display_title": s["title"],
            "order_index": s["order"],
            "start_page": s["start"],
            "end_page": s["end"],
            "final_md_file": f"{dir_name}/{md_name}",
            "review_report_file": f"{dir_name}/review_report.json",
            "status": "success",
            "manual_review_required": s.get("manual_review", False),
        })

    manifest = {
        "source_file": "book.pdf",
        "source_extract_manifest": "extract_manifest.json",
        "generator_version": "phase3-v1",
        "total_slices": len(slices),
        "slices": manifest_slices,
    }
    (format_dir / "format_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return format_dir


class TestPipelineSmoke:
    def test_basic_merge(self, tmp_path):
        fmt_dir = _build_phase3_output(tmp_path)
        out_dir = tmp_path / "output"

        result = run_pipeline(
            input_dir=str(fmt_dir),
            output_dir=str(out_dir),
            copy_assets=True,
            overwrite=False,
        )
        assert result.status == "success"
        assert result.total_slices == 2
        assert result.merged_slices == 2
        assert (out_dir / "book.md").exists()
        assert (out_dir / "merge_report.json").exists()
        assert (out_dir / "merge_manifest.json").exists()

        # Check final markdown has both chapters
        md = (out_dir / "book.md").read_text(encoding="utf-8")
        assert "第一章 概述" in md
        assert "第二章 设计" in md

    def test_overwrite_false_fails(self, tmp_path):
        fmt_dir = _build_phase3_output(tmp_path)
        out_dir = tmp_path / "output"
        out_dir.mkdir()  # Pre-existing

        with pytest.raises(OutputExistsError):
            run_pipeline(
                input_dir=str(fmt_dir),
                output_dir=str(out_dir),
                overwrite=False,
            )

    def test_overwrite_true_succeeds(self, tmp_path):
        fmt_dir = _build_phase3_output(tmp_path)
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        (out_dir / "old_file.txt").write_text("old")

        result = run_pipeline(
            input_dir=str(fmt_dir),
            output_dir=str(out_dir),
            overwrite=True,
        )
        assert result.status == "success"
        assert not (out_dir / "old_file.txt").exists()

    def test_upstream_manual_review_blocks(self, tmp_path):
        slices = [
            {"title": "Ch1", "order": 1, "start": 1, "end": 10,
             "content": "# Ch1\n\nContent.\n", "manual_review": True},
        ]
        fmt_dir = _build_phase3_output(tmp_path, slices)
        out_dir = tmp_path / "output"

        result = run_pipeline(
            input_dir=str(fmt_dir),
            output_dir=str(out_dir),
            allow_upstream_manual_review=False,
        )
        assert result.status == "aborted_upstream_invalid"

    def test_upstream_manual_review_allowed(self, tmp_path):
        slices = [
            {"title": "Ch1", "order": 1, "start": 1, "end": 10,
             "content": "# Ch1\n\nContent.\n", "manual_review": True},
        ]
        fmt_dir = _build_phase3_output(tmp_path, slices)
        out_dir = tmp_path / "output"

        result = run_pipeline(
            input_dir=str(fmt_dir),
            output_dir=str(out_dir),
            allow_upstream_manual_review=True,
        )
        assert result.status == "success"
        assert result.manual_review_required is True

    def test_with_assets(self, tmp_path):
        slices = [
            {"title": "Ch1", "order": 1, "start": 1, "end": 10,
             "content": "# Ch1\n\n![img](assets/img01.png)\n"},
        ]
        fmt_dir = _build_phase3_output(tmp_path, slices)
        out_dir = tmp_path / "output"

        result = run_pipeline(
            input_dir=str(fmt_dir),
            output_dir=str(out_dir),
            copy_assets=True,
        )
        assert result.status == "success"
        # Asset copied and path rewritten
        md = (out_dir / "book.md").read_text(encoding="utf-8")
        assert "assets/001-Ch1/" in md

    def test_single_slice(self, tmp_path):
        slices = [
            {"title": "OnlyChapter", "order": 1, "start": 1, "end": 50,
             "content": "# Only Chapter\n\nAll content.\n"},
        ]
        fmt_dir = _build_phase3_output(tmp_path, slices)
        out_dir = tmp_path / "output"

        result = run_pipeline(
            input_dir=str(fmt_dir),
            output_dir=str(out_dir),
        )
        assert result.status == "success"
        assert result.total_slices == 1
        assert result.removed_overlap_blocks == 0

    def test_cli_exit_codes(self, tmp_path):
        """Test CLI via main() function."""
        from phase4_merge import main

        fmt_dir = _build_phase3_output(tmp_path)
        out_dir = tmp_path / "cli_output"

        exit_code = main([
            "--input-dir", str(fmt_dir),
            "--output-dir", str(out_dir),
        ])
        assert exit_code == 0

    def test_cli_fail_on_manual_review(self, tmp_path):
        from phase4_merge import main

        slices = [
            {"title": "Ch1", "order": 1, "start": 1, "end": 10,
             "content": "# Ch1\n\nContent.\n", "manual_review": True},
        ]
        fmt_dir = _build_phase3_output(tmp_path, slices)
        out_dir = tmp_path / "cli_output"

        # Without --allow-upstream-manual-review, it aborts → exit 1
        exit_code = main([
            "--input-dir", str(fmt_dir),
            "--output-dir", str(out_dir),
        ])
        assert exit_code == 1

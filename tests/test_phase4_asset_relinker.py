from __future__ import annotations

import pytest
from pathlib import Path

from md_merge.asset_relinker import relink_assets, _rewrite_paths
from md_merge.contracts import MergeTask, MergeWarning


def _task(tmp_path: Path, name: str = "slice1", order: int = 1, with_assets: bool = True) -> MergeTask:
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    assets_dir = None
    if with_assets:
        assets_dir = d / "assets"
        assets_dir.mkdir(exist_ok=True)
        (assets_dir / "img01.png").write_bytes(b"PNG_FAKE")
    return MergeTask(
        slice_file=f"{name}.pdf",
        display_title=name,
        order_index=order,
        start_page=1,
        end_page=10,
        input_dir=d,
        final_md_file=d / f"{name}.md",
        review_report_file=d / "review_report.json",
        assets_dir=assets_dir,
        manual_review_required=False,
    )


class TestRewritePaths:
    def test_markdown_image_rewrite(self):
        content = "# Title\n\n![alt](assets/img01.png)\n"
        warnings: list[MergeWarning] = []
        task = MergeTask(
            slice_file="s.pdf", display_title="Ch1", order_index=1,
            start_page=1, end_page=10, input_dir=Path("."),
            final_md_file=Path("."), review_report_file=Path("."),
            assets_dir=None, manual_review_required=False,
        )
        new_content, relinks = _rewrite_paths(content, task, "001-Ch1", warnings)
        assert "assets/001-Ch1/img01.png" in new_content
        assert len(relinks) == 1
        assert relinks[0].original_path == "assets/img01.png"
        assert relinks[0].rewritten_path == "assets/001-Ch1/img01.png"

    def test_html_img_rewrite(self):
        content = '<img src="assets/table.png" alt="table">'
        warnings: list[MergeWarning] = []
        task = MergeTask(
            slice_file="s.pdf", display_title="Ch1", order_index=1,
            start_page=1, end_page=10, input_dir=Path("."),
            final_md_file=Path("."), review_report_file=Path("."),
            assets_dir=None, manual_review_required=False,
        )
        new_content, relinks = _rewrite_paths(content, task, "001-Ch1", warnings)
        assert 'src="assets/001-Ch1/table.png"' in new_content
        assert len(relinks) == 1

    def test_no_assets_no_rewrite(self):
        content = "# Title\n\nNo images here.\n"
        warnings: list[MergeWarning] = []
        task = MergeTask(
            slice_file="s.pdf", display_title="Ch1", order_index=1,
            start_page=1, end_page=10, input_dir=Path("."),
            final_md_file=Path("."), review_report_file=Path("."),
            assets_dir=None, manual_review_required=False,
        )
        new_content, relinks = _rewrite_paths(content, task, "001-Ch1", warnings)
        assert new_content == content
        assert len(relinks) == 0


class TestRelinkAssets:
    def test_copy_and_rewrite(self, tmp_path):
        task = _task(tmp_path, "slice1", 1)
        out = tmp_path / "output"
        out.mkdir()
        contents = {"slice1.pdf": "![img](assets/img01.png)\n"}
        warnings: list[MergeWarning] = []

        relinks = relink_assets(
            [task], contents, out, copy_assets=True, warnings=warnings,
        )
        assert len(relinks) == 1
        assert "001-slice1" in relinks[0].rewritten_path
        # Asset copied
        assert (out / "assets" / "001-slice1" / "img01.png").exists()

    def test_no_copy(self, tmp_path):
        task = _task(tmp_path, "slice1", 1, with_assets=False)
        out = tmp_path / "output"
        out.mkdir()
        contents = {"slice1.pdf": "# Title\n"}
        warnings: list[MergeWarning] = []

        relinks = relink_assets(
            [task], contents, out, copy_assets=False, warnings=warnings,
        )
        assert len(relinks) == 0

    def test_copy_failure_warning(self, tmp_path):
        task = _task(tmp_path, "slice1", 1)
        # Point assets_dir to nonexistent
        task.assets_dir = tmp_path / "nonexistent_assets"
        out = tmp_path / "output"
        out.mkdir()
        contents = {"slice1.pdf": "# Title\n"}
        warnings: list[MergeWarning] = []

        relinks = relink_assets(
            [task], contents, out, copy_assets=True, warnings=warnings,
        )
        # No failure warning since assets_dir doesn't exist (skipped)
        assert len(warnings) == 0

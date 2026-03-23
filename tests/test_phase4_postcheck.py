from __future__ import annotations

import pytest
from pathlib import Path

from md_merge.postcheck import postcheck, _check_consecutive_duplicates
from md_merge.contracts import MergeTask, MergeWarning


def _task(order: int = 1) -> MergeTask:
    return MergeTask(
        slice_file=f"slice_{order}.pdf",
        display_title=f"Chapter {order}",
        order_index=order,
        start_page=1,
        end_page=10,
        input_dir=Path("."),
        final_md_file=Path("."),
        review_report_file=Path("."),
        assets_dir=None,
        manual_review_required=False,
    )


class TestPostcheck:
    def test_empty_markdown(self, tmp_path):
        warnings: list[MergeWarning] = []
        result = postcheck([_task()], "", tmp_path, warnings)
        assert result is True
        assert any(w.warning_type == "slice_missing" for w in warnings)

    def test_valid_markdown(self, tmp_path):
        md = "# Chapter 1\n\nSome content here.\n"
        warnings: list[MergeWarning] = []
        result = postcheck([_task()], md, tmp_path, warnings)
        assert result is False

    def test_heading_count_mismatch(self, tmp_path):
        # 5 tasks but only 1 heading — large discrepancy
        tasks = [_task(i) for i in range(1, 6)]
        md = "# Only Heading\n\nContent.\n"
        warnings: list[MergeWarning] = []
        result = postcheck(tasks, md, tmp_path, warnings)
        assert result is True
        assert any(w.warning_type == "heading_count_mismatch" for w in warnings)

    def test_missing_asset(self, tmp_path):
        md = "# Chapter\n\n![img](assets/missing.png)\n"
        warnings: list[MergeWarning] = []
        result = postcheck([_task()], md, tmp_path, warnings)
        assert result is True
        assert any(w.warning_type == "asset_path_missing" for w in warnings)

    def test_existing_asset(self, tmp_path):
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        (assets_dir / "exists.png").write_bytes(b"PNG")
        md = "# Chapter\n\n![img](assets/exists.png)\n"
        warnings: list[MergeWarning] = []
        result = postcheck([_task()], md, tmp_path, warnings)
        assert result is False


class TestConsecutiveDuplicates:
    def test_no_duplicates(self):
        md = "Block one.\n\nBlock two.\n\nBlock three.\n"
        warnings: list[MergeWarning] = []
        assert _check_consecutive_duplicates(md, warnings) is False

    def test_consecutive_duplicates(self):
        block = "Same content repeated."
        md = f"{block}\n\n{block}\n\n{block}\n"
        warnings: list[MergeWarning] = []
        assert _check_consecutive_duplicates(md, warnings) is True
        assert any(w.warning_type == "consecutive_duplicate_detected" for w in warnings)

    def test_two_duplicates_below_threshold(self):
        block = "Repeated."
        md = f"{block}\n\n{block}\n\nDifferent.\n"
        warnings: list[MergeWarning] = []
        assert _check_consecutive_duplicates(md, warnings) is False

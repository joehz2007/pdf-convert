from __future__ import annotations

import pytest
from pathlib import Path

from md_merge.merge_planner import plan_merge, AdjacentPair
from md_merge.contracts import MergeTask, MergeWarning


def _task(order: int, start: int, end: int, name: str = "") -> MergeTask:
    return MergeTask(
        slice_file=name or f"slice_{order}.pdf",
        display_title=name or f"Chapter {order}",
        order_index=order,
        start_page=start,
        end_page=end,
        input_dir=Path("."),
        final_md_file=Path("."),
        review_report_file=Path("."),
        assets_dir=None,
        manual_review_required=False,
    )


class TestPlanMerge:
    def test_single_slice_no_pairs(self):
        warnings: list[MergeWarning] = []
        pairs, plans = plan_merge([_task(1, 1, 10)], warnings)
        assert len(pairs) == 0
        assert len(plans) == 1
        assert len(warnings) == 0

    def test_two_contiguous_slices(self):
        warnings: list[MergeWarning] = []
        tasks = [_task(1, 1, 10), _task(2, 11, 20)]
        pairs, plans = plan_merge(tasks, warnings)
        assert len(pairs) == 1
        assert pairs[0].left.order_index == 1
        assert pairs[0].right.order_index == 2
        assert len(warnings) == 0

    def test_three_slices(self):
        warnings: list[MergeWarning] = []
        tasks = [_task(1, 1, 10), _task(2, 11, 20), _task(3, 21, 30)]
        pairs, _ = plan_merge(tasks, warnings)
        assert len(pairs) == 2

    def test_page_gap_warning(self):
        warnings: list[MergeWarning] = []
        tasks = [_task(1, 1, 10), _task(2, 15, 25)]  # gap: 11-14
        pairs, _ = plan_merge(tasks, warnings)
        assert len(pairs) == 1
        assert len(warnings) == 1
        assert warnings[0].warning_type == "page_gap_detected"

    def test_overlapping_pages_no_gap(self):
        warnings: list[MergeWarning] = []
        # Pages overlap (end 10, start 9) — no gap
        tasks = [_task(1, 1, 10), _task(2, 9, 20)]
        pairs, _ = plan_merge(tasks, warnings)
        assert len(warnings) == 0

    def test_asset_plan_subdir_names(self):
        warnings: list[MergeWarning] = []
        tasks = [_task(1, 1, 10, "第一章 概述"), _task(2, 11, 20, "第二章 设计")]
        _, plans = plan_merge(tasks, warnings)
        assert plans[0].target_subdir == "001-第一章 概述"
        assert plans[1].target_subdir == "002-第二章 设计"

from __future__ import annotations

import logging
from dataclasses import dataclass

from .contracts import MergeTask, MergeWarning

LOGGER = logging.getLogger("md_merge.merge_planner")


@dataclass(slots=True)
class AdjacentPair:
    left: MergeTask
    right: MergeTask
    left_index: int
    right_index: int


@dataclass(slots=True)
class AssetPlan:
    """Per-slice asset copy plan."""
    task: MergeTask
    target_subdir: str


def plan_merge(
    tasks: list[MergeTask],
    warnings: list[MergeWarning],
) -> tuple[list[AdjacentPair], list[AssetPlan]]:
    """Generate adjacent slice pairs and asset copy plan.

    Tasks MUST already be sorted by order_index.
    """
    pairs: list[AdjacentPair] = []
    asset_plans: list[AssetPlan] = []

    for idx, task in enumerate(tasks):
        # Asset plan — target subdir like "001-第一章-系统概述"
        target_subdir = f"{task.order_index:03d}-{_safe_dirname(task.display_title)}"
        asset_plans.append(AssetPlan(task=task, target_subdir=target_subdir))

        # Adjacent pair
        if idx > 0:
            left = tasks[idx - 1]
            right = task

            # Check page continuity
            if left.end_page + 1 < right.start_page:
                gap_msg = (
                    f"Page gap between {left.slice_file} (ends p{left.end_page}) "
                    f"and {right.slice_file} (starts p{right.start_page})"
                )
                LOGGER.warning(gap_msg)
                warnings.append(MergeWarning(
                    warning_type="page_gap_detected",
                    slice_file=right.slice_file,
                    message=gap_msg,
                ))

            pairs.append(AdjacentPair(
                left=left,
                right=right,
                left_index=idx - 1,
                right_index=idx,
            ))

    LOGGER.info("Planned %d adjacent pairs, %d asset plans", len(pairs), len(asset_plans))
    return pairs, asset_plans


def _safe_dirname(title: str) -> str:
    illegal = r'<>:"/\|?*'
    result = title
    for ch in illegal:
        result = result.replace(ch, "_")
    return result.strip(". ")

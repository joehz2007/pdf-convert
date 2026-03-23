from __future__ import annotations

from pathlib import Path

from md_merge.stitcher import stitch
from md_merge.contracts import MergeTask


def _task(order: int, name: str = "") -> MergeTask:
    base = name or f"slice_{order}"
    return MergeTask(
        slice_file=f"{base}.pdf",
        display_title=name or f"Chapter {order}",
        order_index=order,
        start_page=order * 10 - 9,
        end_page=order * 10,
        input_dir=Path("."),
        final_md_file=Path("."),
        review_report_file=Path("."),
        assets_dir=None,
        manual_review_required=False,
    )


class TestStitch:
    def test_single_slice(self):
        tasks = [_task(1, "s1")]
        contents = {"s1.pdf": "# Chapter 1\n\nContent."}
        result = stitch(tasks, contents)
        assert result.startswith("# Chapter 1")
        assert result.endswith("\n")

    def test_two_slices_blank_line(self):
        tasks = [_task(1, "s1"), _task(2, "s2")]
        contents = {
            "s1.pdf": "# Chapter 1\n\nContent 1.",
            "s2.pdf": "# Chapter 2\n\nContent 2.",
        }
        result = stitch(tasks, contents, separator_style="blank_line")
        assert "Content 1.\n\n# Chapter 2" in result

    def test_thematic_break(self):
        tasks = [_task(1, "s1"), _task(2, "s2")]
        contents = {
            "s1.pdf": "# Ch1\n\nA",
            "s2.pdf": "# Ch2\n\nB",
        }
        result = stitch(tasks, contents, separator_style="thematic_break")
        assert "---" in result

    def test_order_preserved(self):
        tasks = [_task(1, "s1"), _task(2, "s2"), _task(3, "s3")]
        contents = {
            "s1.pdf": "First",
            "s2.pdf": "Second",
            "s3.pdf": "Third",
        }
        result = stitch(tasks, contents)
        assert result.index("First") < result.index("Second") < result.index("Third")

    def test_empty_slices_skipped(self):
        tasks = [_task(1, "s1"), _task(2, "s2")]
        contents = {
            "s1.pdf": "# Ch1",
            "s2.pdf": "",
        }
        result = stitch(tasks, contents)
        assert "# Ch1" in result
        assert result.strip() == "# Ch1"

    def test_trailing_newline(self):
        tasks = [_task(1, "s1")]
        contents = {"s1.pdf": "Content"}
        result = stitch(tasks, contents)
        assert result.endswith("\n")

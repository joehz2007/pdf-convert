from __future__ import annotations

import json
import pytest
from pathlib import Path

from md_merge.writer import write_output
from md_merge.contracts import (
    AssetRelink,
    DedupDecision,
    MergeTask,
    MergeWarning,
)


def _task(order: int, name: str = "Chapter") -> MergeTask:
    return MergeTask(
        slice_file=f"{name}_{order}.pdf",
        display_title=f"{name} {order}",
        order_index=order,
        start_page=order * 10 - 9,
        end_page=order * 10,
        input_dir=Path("."),
        final_md_file=Path("."),
        review_report_file=Path("."),
        assets_dir=None,
        manual_review_required=False,
    )


class TestWriteOutput:
    def test_basic_write(self, tmp_path):
        out = tmp_path / "merged"
        out.mkdir()

        tasks = [_task(1), _task(2)]
        decisions = [
            DedupDecision("Chapter_1.pdf", "Chapter_2.pdf", 10, "dedupe_key", "right_head", 2, None),
        ]

        md_file = write_output(
            out_path=out,
            source_file="book.pdf",
            raw_manifest={"source_file": "book.pdf"},
            tasks=tasks,
            final_markdown="# Ch1\n\nContent.\n\n# Ch2\n\nMore.\n",
            dedup_decisions=decisions,
            asset_relinks=[],
            warnings=[],
            manual_review_required=False,
            removed_overlap_blocks=2,
            timings={"total_ms": 100},
        )

        assert md_file == "book.md"
        assert (out / "book.md").exists()
        assert (out / "merge_report.json").exists()
        assert (out / "merge_manifest.json").exists()

        # Check manifest content
        manifest = json.loads((out / "merge_manifest.json").read_text(encoding="utf-8"))
        assert manifest["total_slices"] == 2
        assert manifest["merged_slices"] == 2
        assert manifest["removed_overlap_blocks"] == 2
        assert manifest["generator_version"] == "phase4-v1"
        assert len(manifest["slices"]) == 2
        assert manifest["slices"][0]["start_page"] == 1
        assert manifest["slices"][1]["start_page"] == 11

        # Check report
        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        assert report["source_file"] == "book.pdf"
        assert len(report["pairs"]) == 1
        assert report["pairs"][0]["removed_count"] == 2

    def test_with_warnings_and_relinks(self, tmp_path):
        out = tmp_path / "merged"
        out.mkdir()

        md_file = write_output(
            out_path=out,
            source_file="doc.pdf",
            raw_manifest={},
            tasks=[_task(1)],
            final_markdown="# Ch1\n\nContent.\n",
            dedup_decisions=[],
            asset_relinks=[
                AssetRelink("Ch1.pdf", "assets/img.png", "assets/001-Ch1/img.png"),
            ],
            warnings=[
                MergeWarning("asset_path_missing", "Ch1.pdf", "Asset missing"),
            ],
            manual_review_required=True,
            removed_overlap_blocks=0,
            timings={},
        )

        report = json.loads((out / "merge_report.json").read_text(encoding="utf-8"))
        assert report["manual_review_required"] is True
        assert len(report["asset_relinks"]) == 1
        assert len(report["warnings"]) == 1
        assert report["warnings"][0]["warning_type"] == "asset_path_missing"

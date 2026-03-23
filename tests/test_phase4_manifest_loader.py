from __future__ import annotations

import json
import pytest
from pathlib import Path

from md_merge.manifest_loader import load_manifest
from md_merge.errors import (
    InvalidFormatManifestError,
    MissingFinalMarkdownError,
    UpstreamSliceFailedError,
)


def _make_manifest(tmp_path: Path, slices: list[dict], **overrides) -> Path:
    """Helper to create a format_manifest.json with slice directories."""
    manifest = {
        "source_file": "test.pdf",
        "source_extract_manifest": "extract_manifest.json",
        "generator_version": "phase3-v1",
        "total_slices": len(slices),
        "slices": slices,
        **overrides,
    }
    manifest_path = tmp_path / "format_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _make_slice(
    tmp_path: Path,
    order_index: int,
    title: str = "Chapter",
    start_page: int = 1,
    end_page: int = 10,
    status: str = "success",
    manual_review: bool = False,
) -> dict:
    """Create a slice directory with final md and review report, return slice dict."""
    dir_name = f"{order_index:03d}-{title}"
    slice_dir = tmp_path / dir_name
    slice_dir.mkdir(parents=True, exist_ok=True)

    md_name = f"{title}（{start_page}-{end_page}）.md"
    md_path = slice_dir / md_name
    md_path.write_text(f"# {title}\n\nContent here.\n", encoding="utf-8")

    report_path = slice_dir / "review_report.json"
    report_path.write_text(json.dumps({
        "slice_file": f"{title}.pdf",
        "status": status,
        "manual_review_required": manual_review,
    }), encoding="utf-8")

    return {
        "slice_file": f"{title}.pdf",
        "display_title": title,
        "order_index": order_index,
        "start_page": start_page,
        "end_page": end_page,
        "final_md_file": f"{dir_name}/{md_name}",
        "review_report_file": f"{dir_name}/review_report.json",
        "status": status,
        "manual_review_required": manual_review,
    }


class TestLoadManifest:
    def test_valid_single_slice(self, tmp_path):
        s = _make_slice(tmp_path, 1, "Chapter1", 1, 10)
        _make_manifest(tmp_path, [s])

        tasks, source, raw = load_manifest(tmp_path)
        assert len(tasks) == 1
        assert tasks[0].slice_file == "Chapter1.pdf"
        assert tasks[0].order_index == 1
        assert tasks[0].start_page == 1
        assert tasks[0].end_page == 10
        assert source == "test.pdf"

    def test_multiple_slices_sorted(self, tmp_path):
        s2 = _make_slice(tmp_path, 2, "ChapterB", 11, 20)
        s1 = _make_slice(tmp_path, 1, "ChapterA", 1, 10)
        _make_manifest(tmp_path, [s2, s1])

        tasks, _, _ = load_manifest(tmp_path)
        assert len(tasks) == 2
        assert tasks[0].order_index == 1
        assert tasks[1].order_index == 2

    def test_missing_manifest_file(self, tmp_path):
        with pytest.raises(InvalidFormatManifestError, match="not found"):
            load_manifest(tmp_path)

    def test_missing_required_key(self, tmp_path):
        (tmp_path / "format_manifest.json").write_text(
            json.dumps({"slices": []}), encoding="utf-8"
        )
        with pytest.raises(InvalidFormatManifestError, match="missing top-level"):
            load_manifest(tmp_path)

    def test_empty_slices(self, tmp_path):
        _make_manifest(tmp_path, [])
        with pytest.raises(InvalidFormatManifestError, match="no slices"):
            load_manifest(tmp_path)

    def test_duplicate_order_index(self, tmp_path):
        s1 = _make_slice(tmp_path, 1, "ChapterA", 1, 10)
        s2 = _make_slice(tmp_path, 1, "ChapterB", 11, 20)
        _make_manifest(tmp_path, [s1, s2])

        with pytest.raises(InvalidFormatManifestError, match="Duplicate order_index"):
            load_manifest(tmp_path)

    def test_all_upstream_failed(self, tmp_path):
        s = _make_slice(tmp_path, 1, "Chapter1", 1, 10, status="failed")
        _make_manifest(tmp_path, [s])

        with pytest.raises(UpstreamSliceFailedError):
            load_manifest(tmp_path)

    def test_partial_upstream_failed_skipped(self, tmp_path):
        s1 = _make_slice(tmp_path, 1, "ChapterA", 1, 10, status="success")
        s2 = _make_slice(tmp_path, 2, "ChapterB", 11, 20, status="skipped_upstream_failed")
        _make_manifest(tmp_path, [s1, s2])

        tasks, _, _ = load_manifest(tmp_path)
        # Only success slice is included
        assert len(tasks) == 1
        assert tasks[0].slice_file == "ChapterA.pdf"

    def test_missing_final_markdown(self, tmp_path):
        s = _make_slice(tmp_path, 1, "Chapter1", 1, 10)
        # Remove the markdown file
        for f in tmp_path.rglob("*.md"):
            f.unlink()
        _make_manifest(tmp_path, [s])

        with pytest.raises(MissingFinalMarkdownError):
            load_manifest(tmp_path)

    def test_manual_review_flag_preserved(self, tmp_path):
        s = _make_slice(tmp_path, 1, "Chapter1", 1, 10, manual_review=True)
        _make_manifest(tmp_path, [s])

        tasks, _, _ = load_manifest(tmp_path)
        assert tasks[0].manual_review_required is True

from __future__ import annotations

import pytest

from md_format.errors import InvalidExtractManifestError, MissingContentFileError
from md_format.manifest_loader import load_extract_manifest


def test_manifest_loader_builds_tasks_from_valid_extract(create_phase2_output):
    extract_dir = create_phase2_output(
        "test-load",
        [
            {"slice_file": "ch1.pdf", "display_title": "Chapter 1", "start_page": 1, "end_page": 3},
            {"slice_file": "ch2.pdf", "display_title": "Chapter 2", "start_page": 4, "end_page": 6},
        ],
    )

    raw, tasks = load_extract_manifest(extract_dir)

    assert len(tasks) == 2
    assert tasks[0].slice_file == "ch1.pdf"
    assert tasks[0].display_title == "Chapter 1"
    assert tasks[0].order_index == 1
    assert tasks[0].start_page == 1
    assert tasks[0].end_page == 3
    assert tasks[1].order_index == 2


def test_manifest_loader_skips_failed_upstream_slices(create_phase2_output):
    extract_dir = create_phase2_output(
        "test-skip",
        [
            {"slice_file": "ok.pdf", "display_title": "OK", "start_page": 1, "end_page": 1},
            {"slice_file": "fail.pdf", "display_title": "Failed", "status": "failed"},
        ],
    )

    raw, tasks = load_extract_manifest(extract_dir)

    assert len(tasks) == 1
    assert tasks[0].slice_file == "ok.pdf"


def test_manifest_loader_rejects_missing_extract_manifest(tmp_path):
    with pytest.raises(InvalidExtractManifestError):
        load_extract_manifest(tmp_path / "nonexistent")


def test_manifest_loader_rejects_missing_content_json(create_phase2_output):
    extract_dir = create_phase2_output(
        "test-missing-content",
        [{"slice_file": "ch1.pdf", "display_title": "Chapter 1"}],
    )
    # Delete the content.json
    for p in extract_dir.rglob("content.json"):
        p.unlink()

    with pytest.raises(MissingContentFileError):
        load_extract_manifest(extract_dir)

from __future__ import annotations

import json

import pytest

from pdf_extract.errors import MissingSliceError
from pdf_extract.manifest_loader import load_manifest


def test_manifest_loader_reads_slice_tasks(create_phase2_manifest):
    manifest_path = create_phase2_manifest(
        "phase2-manifest",
        [
            {
                "filename": "Chapter 1 Overview（1-2）.pdf",
                "pages": [
                    {"heading": "Chapter 1 Overview", "body": "page one"},
                    {"body": "page two"},
                ],
                "start_page": 1,
                "end_page": 2,
                "display_title": "Chapter 1 Overview",
            }
        ],
    )

    loaded = load_manifest(manifest_path)

    assert loaded.source_file == "phase2-manifest.pdf"
    assert len(loaded.slices) == 1
    assert loaded.slices[0].slice_file.endswith(".pdf")


def test_manifest_loader_rejects_missing_slice(tmp_path):
    split_dir = tmp_path / "missing_split"
    split_dir.mkdir()
    manifest_path = split_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_file": "missing.pdf",
                "total_pages": 1,
                "created_at": "2026-03-21T10:00:00Z",
                "generator_version": "phase1-v1",
                "fallback_level": 1,
                "slices": [
                    {
                        "slice_file": "missing-slice.pdf",
                        "start_page": 1,
                        "end_page": 1,
                        "actual_pages": 1,
                        "display_title": "Missing Slice",
                        "toc_level": 1,
                        "split_mode": "chapter",
                        "overlap_pages": [],
                        "boundary_reason": "chapter_boundary",
                        "exception_type": None,
                        "manual_review_required": False,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(MissingSliceError):
        load_manifest(manifest_path)

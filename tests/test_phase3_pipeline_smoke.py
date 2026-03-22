from __future__ import annotations

import json

import pytest

from md_format.errors import OutputExistsError
from md_format.pipeline import run_pipeline


def test_pipeline_smoke_produces_output(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output(
        "smoke",
        [
            {"slice_file": "ch1.pdf", "display_title": "Chapter 1", "start_page": 1, "end_page": 2},
            {"slice_file": "ch2.pdf", "display_title": "Chapter 2", "start_page": 3, "end_page": 4},
        ],
    )
    output_dir = tmp_path / "smoke_format"

    manifest = run_pipeline(input_dir=extract_dir, output_dir=output_dir)

    assert manifest.success_count == 2
    assert manifest.failed_count == 0
    assert manifest.total_slices == 2
    assert (output_dir / "format_manifest.json").exists()

    # Check slice output directories
    for i, display in enumerate(["Chapter 1", "Chapter 2"], start=1):
        slice_dir = output_dir / f"{i:03d}-{display}"
        assert slice_dir.exists()
        md_files = list(slice_dir.glob("*.md"))
        assert len(md_files) == 1
        assert (slice_dir / "review_report.json").exists()


def test_pipeline_skips_upstream_failed_slices(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output(
        "skip",
        [
            {"slice_file": "ok.pdf", "display_title": "OK"},
            {"slice_file": "fail.pdf", "display_title": "Failed", "status": "failed"},
        ],
    )
    output_dir = tmp_path / "skip_format"

    manifest = run_pipeline(input_dir=extract_dir, output_dir=output_dir)

    assert manifest.success_count == 1
    assert manifest.total_slices == 2
    skipped = [s for s in manifest.slices if s.status == "skipped_upstream_failed"]
    assert len(skipped) == 1
    assert skipped[0].slice_file == "fail.pdf"


def test_pipeline_overwrite_false_raises(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output("ow", [{"slice_file": "ch1.pdf", "display_title": "Ch1"}])
    output_dir = tmp_path / "ow_format"
    output_dir.mkdir()

    with pytest.raises(OutputExistsError):
        run_pipeline(input_dir=extract_dir, output_dir=output_dir, overwrite=False)


def test_pipeline_overwrite_true_succeeds(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output("ow2", [{"slice_file": "ch1.pdf", "display_title": "Ch1"}])
    output_dir = tmp_path / "ow2_format"
    output_dir.mkdir()
    (output_dir / "old_file.txt").write_text("old")

    manifest = run_pipeline(input_dir=extract_dir, output_dir=output_dir, overwrite=True)

    assert manifest.success_count == 1
    assert not (output_dir / "old_file.txt").exists()


def test_pipeline_fail_on_manual_review_returns_nonzero(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output(
        "review",
        [{"slice_file": "ch1.pdf", "display_title": "Ch1", "manual_review_required": True}],
    )
    output_dir = tmp_path / "review_format"

    manifest = run_pipeline(
        input_dir=extract_dir,
        output_dir=output_dir,
        fail_on_manual_review=True,
    )

    assert manifest.manual_review_count == 1


def test_pipeline_workers_concurrent(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output(
        "concurrent",
        [
            {"slice_file": "ch1.pdf", "display_title": "Ch1", "start_page": 1, "end_page": 1},
            {"slice_file": "ch2.pdf", "display_title": "Ch2", "start_page": 2, "end_page": 2},
            {"slice_file": "ch3.pdf", "display_title": "Ch3", "start_page": 3, "end_page": 3},
        ],
    )
    output_dir = tmp_path / "concurrent_format"

    manifest = run_pipeline(input_dir=extract_dir, output_dir=output_dir, workers=3)

    assert manifest.success_count == 3
    assert manifest.total_slices == 3
    # Verify order is preserved
    assert manifest.slices[0].order_index == 1
    assert manifest.slices[1].order_index == 2
    assert manifest.slices[2].order_index == 3


def test_pipeline_records_stage_timings(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output(
        "timing",
        [{"slice_file": "ch1.pdf", "display_title": "Ch1"}],
    )
    output_dir = tmp_path / "timing_format"

    manifest = run_pipeline(input_dir=extract_dir, output_dir=output_dir)

    result = manifest.slices[0]
    assert result.stage_timings.get("coverage_audit_ms", 0) >= 0
    assert result.stage_timings.get("repair_ms", 0) >= 0
    assert result.stage_timings.get("total_ms", 0) >= 0
    assert manifest.timings.get("manifest_load_ms", 0) >= 0


def test_pipeline_copy_assets_false(create_phase2_output, tmp_path):
    extract_dir = create_phase2_output(
        "no-copy",
        [{"slice_file": "ch1.pdf", "display_title": "Ch1"}],
    )
    # Add a dummy asset
    assets_dir = list(extract_dir.rglob("assets"))[0]
    (assets_dir / "p0001_img01.png").write_bytes(b"fake-png")

    output_dir = tmp_path / "no_copy_format"
    manifest = run_pipeline(input_dir=extract_dir, output_dir=output_dir, copy_assets=False)

    assert manifest.success_count == 1
    assert manifest.slices[0].asset_mode == "reuse_phase2"
    # Assets should NOT be copied
    out_assets = list((output_dir).rglob("assets/p0001_img01.png"))
    assert len(out_assets) == 0

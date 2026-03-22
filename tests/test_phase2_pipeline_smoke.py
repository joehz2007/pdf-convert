from __future__ import annotations

import json

import pdf_extract.writer as writer_module
from phase2_extract import build_parser, main


VALID_BODY = "This supported page contains enough extractable words for the Phase 2 precheck threshold."


def test_phase2_cli_help(capsys):
    parser = build_parser()
    try:
        parser.parse_args(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    captured = capsys.readouterr()
    assert "Extract Markdown drafts" in captured.out


def test_phase2_cli_runs_end_to_end(create_phase2_manifest, tmp_path):
    manifest_path = create_phase2_manifest(
        "phase2-cli",
        [
            {
                "filename": "Chapter 1 Overview（1-2）.pdf",
                "pages": [
                    {"heading": "Chapter 1 Overview", "body": "First page content."},
                    {"body": "Second page content."},
                ],
                "start_page": 1,
                "end_page": 2,
                "display_title": "Chapter 1 Overview",
            }
        ],
    )
    output_dir = tmp_path / "phase2-output"

    exit_code = main(
        [
            "--input-manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--emit-md",
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output_dir / "extract_manifest.json").read_text(encoding="utf-8"))
    assert manifest["success_count"] == 1
    assert manifest["failed_count"] == 0
    assert manifest["timings"]["manifest_load_ms"] >= 1
    slice_dir = output_dir / "001-Chapter 1 Overview"
    assert (slice_dir / "source.pdf").exists()
    assert (slice_dir / "Chapter 1 Overview（1-2）.md").exists()
    content = json.loads((slice_dir / "content.json").read_text(encoding="utf-8"))
    assert content["stats"]["char_count"] > 0
    assert len(content["source_pages"]) == 2
    assert content["source_pages"][0]["blocks"]
    assert content["source_pages"][0]["blocks"][0]["dedupe_key"]
    assert manifest["slices"][0]["stage_timings"]["write_ms"] >= 0


def test_phase2_cli_supports_no_emit_md(create_phase2_manifest, tmp_path):
    manifest_path = create_phase2_manifest(
        "phase2-no-md",
        [
            {
                "filename": "Chapter 1 Overview（1-1）.pdf",
                "pages": [{"heading": "Chapter 1 Overview", "body": "Body content."}],
                "start_page": 1,
                "end_page": 1,
                "display_title": "Chapter 1 Overview",
            }
        ],
    )
    output_dir = tmp_path / "phase2-output"

    exit_code = main(
        [
            "--input-manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--no-emit-md",
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output_dir / "extract_manifest.json").read_text(encoding="utf-8"))
    assert manifest["slices"][0]["md_file"] is None
    assert not list((output_dir / "001-Chapter 1 Overview").glob("*.md"))


def test_phase2_cli_rejects_existing_output_without_overwrite(create_phase2_manifest, tmp_path):
    manifest_path = create_phase2_manifest(
        "phase2-overwrite",
        [
            {
                "filename": "Chapter 1 Overview（1-1）.pdf",
                "pages": [{"heading": "Chapter 1 Overview", "body": VALID_BODY}],
                "start_page": 1,
                "end_page": 1,
                "display_title": "Chapter 1 Overview",
            }
        ],
    )
    output_dir = tmp_path / "phase2-output"

    first_exit = main([
        "--input-manifest",
        str(manifest_path),
        "--output-dir",
        str(output_dir),
        "--emit-md",
    ])
    second_exit = main([
        "--input-manifest",
        str(manifest_path),
        "--output-dir",
        str(output_dir),
        "--emit-md",
    ])

    assert first_exit == 0
    assert second_exit == 1
    manifest = json.loads((output_dir / "extract_manifest.json").read_text(encoding="utf-8"))
    assert manifest["success_count"] == 1


def test_phase2_cli_records_partial_failure_and_stage_timings(create_phase2_manifest, tmp_path):
    manifest_path = create_phase2_manifest(
        "phase2-partial-failure",
        [
            {
                "filename": "Chapter 1 Overview（1-1）.pdf",
                "pages": [{"heading": "Chapter 1 Overview", "body": VALID_BODY}],
                "start_page": 1,
                "end_page": 1,
                "display_title": "Chapter 1 Overview",
            },
            {
                "filename": "Scan Only（2-2）.pdf",
                "pages": [{"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]}],
                "start_page": 2,
                "end_page": 2,
                "display_title": "Scan Only",
            },
        ],
    )
    output_dir = tmp_path / "phase2-output"

    exit_code = main(
        [
            "--input-manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--emit-md",
            "--overwrite",
            "--workers",
            "2",
        ]
    )

    assert exit_code == 1
    manifest = json.loads((output_dir / "extract_manifest.json").read_text(encoding="utf-8"))
    assert manifest["success_count"] == 1
    assert manifest["failed_count"] == 1
    failed = next(item for item in manifest["slices"] if item["status"] == "failed")
    assert failed["error_code"] == "unsupported_input"
    assert failed["manual_review_required"] is True
    assert failed["stage_timings"]["precheck_ms"] >= 1
    assert failed["stage_timings"]["total_ms"] >= failed["stage_timings"]["precheck_ms"]
    assert manifest["timings"]["manifest_load_ms"] >= 1
    assert manifest["timings"]["slice_total_ms"] >= 0
    assert manifest["timings"]["write_manifest_ms"] >= 1
    assert manifest["timings"]["total_ms"] >= manifest["total_elapsed_ms"]


def test_phase2_cli_truncates_overlong_markdown_path(create_phase2_manifest, tmp_path, monkeypatch):
    long_title = "Very Long Title " * 8
    long_filename = f"{long_title.strip()}（1-1）.pdf"
    manifest_path = create_phase2_manifest(
        "phase2-long-path",
        [
            {
                "filename": long_filename,
                "pages": [{"heading": "Long Title", "body": "Body text for long path coverage."}],
                "start_page": 1,
                "end_page": 1,
                "display_title": long_title.strip(),
            }
        ],
    )
    output_dir = tmp_path / "phase2-output"
    monkeypatch.setattr(writer_module, "MAX_SAFE_PATH_LENGTH", 100)

    exit_code = main(
        [
            "--input-manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--emit-md",
            "--overwrite",
        ]
    )

    assert exit_code == 0
    manifest = json.loads((output_dir / "extract_manifest.json").read_text(encoding="utf-8"))
    md_rel_path = manifest["slices"][0]["md_file"]
    assert md_rel_path.endswith(".md")
    assert "__" in md_rel_path
    assert (output_dir / md_rel_path).exists()


from __future__ import annotations

import json

import pdf_extract.writer as writer_module
from phase2_extract import build_parser, main


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
    slice_dir = output_dir / "001-Chapter 1 Overview"
    assert (slice_dir / "source.pdf").exists()
    assert (slice_dir / "Chapter 1 Overview（1-2）.md").exists()
    content = json.loads((slice_dir / "content.json").read_text(encoding="utf-8"))
    assert content["stats"]["char_count"] > 0
    assert len(content["source_pages"]) == 2
    assert content["source_pages"][0]["blocks"]
    assert content["source_pages"][0]["blocks"][0]["dedupe_key"]


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



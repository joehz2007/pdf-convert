from __future__ import annotations

import json

import pytest

from split_pdf import build_parser, main


def test_cli_help(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "Split a large digital PDF" in captured.out


def test_cli_runs_end_to_end(create_pdf, tmp_path):
    pdf_path = create_pdf(
        "cli.pdf",
        pages=[
            {"heading": "Chapter 1 Overview", "body": "page one"},
            {"body": "page two"},
            {"heading": "Chapter 2 Design", "body": "page three"},
        ],
        toc=[[1, "Chapter 1 Overview", 1], [1, "Chapter 2 Design", 3]],
    )
    output_dir = tmp_path / "output"
    exit_code = main([str(pdf_path), "--output-dir", str(output_dir)])
    assert exit_code == 0
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fallback_level"] == 1
    assert len(manifest["slices"]) == 1
    assert manifest["slices"][0]["split_mode"] == "merge"


def test_cli_outputs_manifest_for_oversized_slice(create_pdf, tmp_path):
    pages = []
    for page_number in range(1, 31):
        page_data = {
            "extra_texts": [
                {"point": (50, 100), "text": f"continuation text on page {page_number}"},
                {"point": (50, 780), "text": f"continued content page {page_number}"},
            ]
        }
        if page_number == 1:
            page_data["heading"] = "Chapter 1 Oversized"
        if page_number == 28:
            page_data["extra_texts"][0] = {"point": (50, 100), "text": "figure 1 caption"}
        pages.append(page_data)

    pdf_path = create_pdf("oversized-cli.pdf", pages=pages)
    output_dir = tmp_path / "oversized-output"

    exit_code = main([str(pdf_path), "--output-dir", str(output_dir)])

    assert exit_code == 0
    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["slices"]) == 2
    assert manifest["slices"][0]["actual_pages"] == 27
    assert manifest["slices"][0]["exception_type"] == "oversized_semantic_block"
    assert manifest["slices"][0]["manual_review_required"] is True
    assert manifest["slices"][1]["start_page"] == 28

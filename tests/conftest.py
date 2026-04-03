from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pymupdf
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _create_pdf(path: Path, pages: list[dict], toc: list[list] | None = None, encrypt: bool = False) -> Path:
    document = pymupdf.open()
    for page_data in pages:
        page = document.new_page()
        if page_data.get("heading"):
            page.insert_text((50, 60), page_data["heading"], fontsize=20)
        if page_data.get("body"):
            page.insert_text((50, 100), page_data["body"], fontsize=11)
        if page_data.get("shapes"):
            for shape in page_data["shapes"]:
                if shape["type"] == "rect":
                    page.draw_rect(shape["rect"], color=(0, 0, 0), fill=shape.get("fill", (0.8, 0.8, 0.8)), width=shape.get("width", 1))
                if shape["type"] == "line":
                    page.draw_line(shape["p1"], shape["p2"], color=(0, 0, 0), width=shape.get("width", 1))
        for image in page_data.get("images", []):
            page.insert_image(image["rect"], stream=image["stream"])
        for extra_text in page_data.get("extra_texts", []):
            page.insert_text(extra_text["point"], extra_text["text"], fontsize=extra_text.get("fontsize", 11), fontname=extra_text.get("fontname", "helv"))

    if toc:
        document.set_toc(toc)

    save_kwargs = {}
    if encrypt:
        save_kwargs = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "owner_pw": "owner-pass",
            "user_pw": "user-pass",
        }
    document.save(path, **save_kwargs)
    document.close()
    return path


@pytest.fixture
def create_pdf(tmp_path):
    def factory(filename: str, pages: list[dict], toc: list[list] | None = None, encrypt: bool = False) -> Path:
        return _create_pdf(tmp_path / filename, pages, toc=toc, encrypt=encrypt)

    return factory


@pytest.fixture
def create_phase2_manifest(tmp_path, create_pdf):
    def factory(
        name: str,
        slice_specs: list[dict],
        *,
        source_file: str | None = None,
        fallback_level: int = 1,
    ) -> Path:
        split_dir = tmp_path / f"{name}_split"
        split_dir.mkdir()
        manifest = {
            "source_file": source_file or f"{name}.pdf",
            "total_pages": sum(spec["end_page"] - spec["start_page"] + 1 for spec in slice_specs),
            "created_at": "2026-03-21T10:00:00Z",
            "generator_version": "phase1-v1",
            "fallback_level": fallback_level,
            "slices": [],
        }
        for index, spec in enumerate(slice_specs, start=1):
            temp_pdf = create_pdf(spec["filename"], spec["pages"], toc=spec.get("toc"))
            target_pdf = split_dir / spec["filename"]
            shutil.copy2(temp_pdf, target_pdf)
            manifest["slices"].append(
                {
                    "slice_file": spec["filename"],
                    "start_page": spec["start_page"],
                    "end_page": spec["end_page"],
                    "actual_pages": spec["end_page"] - spec["start_page"] + 1,
                    "display_title": spec.get("display_title", f"Slice {index}"),
                    "toc_level": spec.get("toc_level", 1),
                    "split_mode": spec.get("split_mode", "chapter"),
                    "overlap_pages": spec.get("overlap_pages", []),
                    "boundary_reason": spec.get("boundary_reason", "chapter_boundary"),
                    "exception_type": spec.get("exception_type"),
                    "manual_review_required": spec.get("manual_review_required", False),
                }
            )
        manifest_path = split_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest_path

    return factory


@pytest.fixture
def create_phase2_output(tmp_path):
    """Create a minimal Phase 2 output directory with extract_manifest.json,
    content.json, draft .md, and assets/ for each slice."""

    def factory(
        name: str,
        slice_specs: list[dict],
        *,
        source_file: str | None = None,
    ) -> Path:
        extract_dir = tmp_path / f"{name}_extract"
        extract_dir.mkdir()

        manifest = {
            "source_manifest": "manifest.json",
            "source_file": source_file or f"{name}.pdf",
            "created_at": "2026-03-21T10:00:00Z",
            "generator_version": "phase2-v1",
            "scope": "digital-pdf-only",
            "total_slices": len(slice_specs),
            "success_count": 0,
            "failed_count": 0,
            "total_warnings": 0,
            "total_elapsed_ms": 100,
            "slices": [],
        }

        for index, spec in enumerate(slice_specs):
            slice_file = spec.get("slice_file", f"slice-{index + 1}.pdf")
            display_title = spec.get("display_title", f"Slice {index + 1}")
            status = spec.get("status", "success")
            dir_name = f"{index + 1:03d}-{display_title}"
            slice_dir = extract_dir / dir_name

            if status == "success":
                manifest["success_count"] += 1
                slice_dir.mkdir(parents=True)
                (slice_dir / "assets").mkdir()

                content = {
                    "slice_file": slice_file,
                    "display_title": display_title,
                    "start_page": spec.get("start_page", index + 1),
                    "end_page": spec.get("end_page", index + 1),
                    "source_pages": spec.get("source_pages", [
                        {
                            "slice_page": 1,
                            "source_page": spec.get("start_page", index + 1),
                            "is_overlap": False,
                            "markdown": spec.get("markdown", f"# {display_title}\n\nBody text."),
                            "blocks": spec.get("blocks", [
                                {
                                    "type": "heading",
                                    "text": display_title,
                                    "source_page": spec.get("start_page", index + 1),
                                    "bbox": [50, 40, 500, 70],
                                    "reading_order": 0,
                                    "is_overlap": False,
                                    "dedupe_key": f"{spec.get('start_page', index + 1)}:abc:def",
                                },
                                {
                                    "type": "paragraph",
                                    "text": "Body text.",
                                    "source_page": spec.get("start_page", index + 1),
                                    "bbox": [50, 80, 500, 110],
                                    "reading_order": 1,
                                    "is_overlap": False,
                                    "dedupe_key": f"{spec.get('start_page', index + 1)}:ghi:jkl",
                                },
                            ]),
                            "tables": spec.get("tables", []),
                            "images": spec.get("images", []),
                        }
                    ]),
                    "assets": [],
                    "stats": {"char_count": 50, "table_count": 0, "image_count": 0},
                    "warnings": [],
                    "manual_review_required": spec.get("manual_review_required", False),
                }
                content_path = slice_dir / "content.json"
                content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

                emit_draft_md = spec.get("emit_draft_md", True)
                md_path = slice_dir / slice_file.replace(".pdf", ".md")
                if emit_draft_md:
                    md_content = spec.get("markdown", f"# {display_title}\n\nBody text.")
                    md_path.write_text(md_content, encoding="utf-8")

                manifest["slices"].append({
                    "slice_file": slice_file,
                    "content_file": f"{dir_name}/content.json",
                    "md_file": f"{dir_name}/{md_path.name}" if emit_draft_md else None,
                    "emit_draft_md": emit_draft_md,
                    "status": "success",
                    "warning_count": 0,
                    "manual_review_required": spec.get("manual_review_required", False),
                    "elapsed_ms": 100,
                    "error_code": None,
                    "error_message": None,
                    "stage_timings": {},
                })
            else:
                manifest["failed_count"] += 1
                manifest["slices"].append({
                    "slice_file": slice_file,
                    "content_file": None,
                    "md_file": None,
                    "status": "failed",
                    "warning_count": 0,
                    "manual_review_required": False,
                    "elapsed_ms": 10,
                    "error_code": "unsupported_input",
                    "error_message": "test failure",
                    "stage_timings": {},
                })

        manifest_path = extract_dir / "extract_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return extract_dir

    return factory

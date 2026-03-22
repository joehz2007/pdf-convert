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

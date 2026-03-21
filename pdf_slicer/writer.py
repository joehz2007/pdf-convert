from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .models import SlicePlan

ILLEGAL_FILENAME_CHARACTERS = '\\/:*?"<>|'


class PdfSliceWriter:
    def __init__(self, document, generator_version: str = "phase1-v1"):
        self.document = document
        self.generator_version = generator_version

    def write(
        self,
        slices: list[SlicePlan],
        fallback_level: int,
        output_dir: str | Path | None = None,
    ) -> Path:
        destination = Path(output_dir) if output_dir else self.document.path.parent / f"{self.document.path.stem}_split"
        destination.mkdir(parents=True, exist_ok=True)

        name_counter: Counter[str] = Counter()
        manifest_slices = []
        for plan in slices:
            base_name = f"{self._sanitize_filename(plan.title)}（{plan.start_page}-{plan.end_page}）"
            name_counter[base_name] += 1
            suffix = f"_{name_counter[base_name]:02d}" if name_counter[base_name] > 1 else ""
            filename = f"{base_name}{suffix}.pdf"
            output_path = destination / filename
            self.document.slice_pdf(plan.start_page, plan.end_page, output_path)
            manifest_slices.append(
                {
                    "slice_file": filename,
                    "start_page": plan.start_page,
                    "end_page": plan.end_page,
                    "actual_pages": plan.actual_pages,
                    "display_title": plan.title,
                    "toc_level": plan.toc_level,
                    "split_mode": plan.split_mode,
                    "overlap_pages": sorted(plan.overlap_pages),
                    "boundary_reason": plan.boundary_reason,
                    "exception_type": plan.exception_type,
                    "manual_review_required": plan.manual_review_required,
                }
            )

        manifest = {
            "source_file": self.document.path.name,
            "total_pages": self.document.total_pages,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generator_version": self.generator_version,
            "fallback_level": fallback_level,
            "slices": manifest_slices,
        }
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return destination

    @staticmethod
    def _sanitize_filename(title: str) -> str:
        sanitized = title
        for character in ILLEGAL_FILENAME_CHARACTERS:
            sanitized = sanitized.replace(character, "_")
        return sanitized.strip() or "未命名章节"

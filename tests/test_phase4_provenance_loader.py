from __future__ import annotations

import json
import pytest
from pathlib import Path

from md_merge.provenance_loader import (
    load_provenance,
    normalize_text,
    text_hash,
    _blocks_from_markdown,
)
from md_merge.contracts import MergeTask, MergeWarning


def _make_task(tmp_path: Path, name: str = "slice1", md_content: str = "# Heading\n\nParagraph.\n") -> MergeTask:
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    md = d / f"{name}.md"
    md.write_text(md_content, encoding="utf-8")
    return MergeTask(
        slice_file=f"{name}.pdf",
        display_title=name,
        order_index=1,
        start_page=1,
        end_page=10,
        input_dir=d,
        final_md_file=md,
        review_report_file=d / "review_report.json",
        assets_dir=None,
        manual_review_required=False,
    )


class TestNormalization:
    def test_nfkc_normalization(self):
        # Fullwidth latin -> ascii
        assert normalize_text("\uff21\uff22") == "AB"

    def test_whitespace_collapse(self):
        assert normalize_text("hello   world\n\ttab") == "hello world tab"

    def test_strip(self):
        assert normalize_text("  hello  ") == "hello"

    def test_preserves_punctuation(self):
        assert normalize_text("hello, world!") == "hello, world!"

    def test_preserves_case(self):
        assert normalize_text("Hello World") == "Hello World"


class TestTextHash:
    def test_same_content_same_hash(self):
        assert text_hash("hello world") == text_hash("hello world")

    def test_different_content_different_hash(self):
        assert text_hash("hello") != text_hash("world")

    def test_whitespace_normalized(self):
        assert text_hash("hello  world") == text_hash("hello world")


class TestBlocksFromMarkdown:
    def test_heading(self, tmp_path):
        task = _make_task(tmp_path, md_content="# Title\n\nContent\n")
        blocks = _blocks_from_markdown("# Title\n\nContent\n", task)
        assert len(blocks) == 2
        assert blocks[0].block_type == "heading"
        assert blocks[1].block_type == "paragraph"

    def test_code_block(self, tmp_path):
        task = _make_task(tmp_path, md_content="```python\nprint('hi')\n```\n")
        blocks = _blocks_from_markdown("```python\nprint('hi')\n```\n", task)
        assert len(blocks) == 1
        assert blocks[0].block_type == "code"

    def test_table(self, tmp_path):
        task = _make_task(tmp_path, md_content="| A | B |\n|---|---|\n| 1 | 2 |\n")
        blocks = _blocks_from_markdown("| A | B |\n|---|---|\n| 1 | 2 |\n", task)
        assert len(blocks) == 1
        assert blocks[0].block_type == "table"

    def test_image(self, tmp_path):
        task = _make_task(tmp_path, md_content="![alt](assets/img.png)\n")
        blocks = _blocks_from_markdown("![alt](assets/img.png)\n", task)
        assert len(blocks) == 1
        assert blocks[0].block_type == "image"
        assert blocks[0].asset_ref == "assets/img.png"


class TestLoadProvenance:
    def test_fallback_to_markdown(self, tmp_path):
        task = _make_task(tmp_path, md_content="# Ch1\n\nPara 1.\n")
        warnings: list[MergeWarning] = []
        result = load_provenance([task], {}, warnings)
        assert task.slice_file in result
        prov = result[task.slice_file]
        assert len(prov.all_blocks) >= 1
        # Should have a fallback warning
        assert any(w.warning_type == "overlap_no_provenance" for w in warnings)

    def test_with_content_json(self, tmp_path):
        task = _make_task(tmp_path, md_content="# Ch1\n")
        # Write content.json into the task input_dir
        content = {
            "source_pages": [
                {
                    "source_page": 1,
                    "is_overlap": False,
                    "blocks": [{"type": "heading", "text": "# Ch1", "dedupe_key": "dk1"}],
                    "images": [],
                    "tables": [],
                }
            ]
        }
        (task.input_dir / "content.json").write_text(json.dumps(content), encoding="utf-8")

        # Need to pass source_extract_manifest so it tries to load content.json
        raw_manifest = {"source_extract_manifest": "extract_manifest.json"}
        warnings: list[MergeWarning] = []
        result = load_provenance([task], raw_manifest, warnings)
        prov = result[task.slice_file]
        assert len(prov.all_blocks) == 1
        assert prov.all_blocks[0].dedupe_key == "dk1"
        # No fallback warning
        assert not any(w.warning_type == "overlap_no_provenance" for w in warnings)

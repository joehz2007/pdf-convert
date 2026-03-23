from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from .config import OVERLAP_COMPARE_MAX_BLOCKS, TEXT_HASH_ALGORITHM
from .contracts import MergeBlockRef, MergeTask, MergeWarning

LOGGER = logging.getLogger("md_merge.provenance_loader")


def normalize_text(text: str) -> str:
    """Normalize text for hash comparison.

    1. NFKC normalization
    2. Collapse consecutive whitespace to single space
    3. Strip leading/trailing whitespace
    4. Preserve punctuation and case
    """
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def text_hash(text: str) -> str:
    normalized = normalize_text(text)
    h = hashlib.new(TEXT_HASH_ALGORITHM)
    h.update(normalized.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Provenance data per slice
# ---------------------------------------------------------------------------


class SliceProvenance:
    """Provenance info for a single slice: head/tail blocks for overlap comparison."""

    def __init__(
        self,
        task: MergeTask,
        head_blocks: list[MergeBlockRef],
        tail_blocks: list[MergeBlockRef],
        all_blocks: list[MergeBlockRef],
    ):
        self.task = task
        self.head_blocks = head_blocks
        self.tail_blocks = tail_blocks
        self.all_blocks = all_blocks


def load_provenance(
    tasks: list[MergeTask],
    raw_manifest: dict[str, Any],
    warnings: list[MergeWarning],
) -> dict[str, SliceProvenance]:
    """Load provenance info for each slice.

    Priority:
    1. Phase 2 content.json if available (via source_extract_manifest)
    2. Fallback: parse final markdown into blocks with text hashes
    """
    result: dict[str, SliceProvenance] = {}

    # Try to find Phase 2 content.json paths
    content_json_map = _try_load_content_jsons(raw_manifest, tasks)

    for task in tasks:
        content_data = content_json_map.get(task.slice_file)

        if content_data is not None:
            blocks = _blocks_from_content_json(content_data)
            LOGGER.debug(
                "Provenance from content.json for %s: %d blocks",
                task.slice_file, len(blocks),
            )
        else:
            # Fallback: parse final markdown
            md_text = task.final_md_file.read_text(encoding="utf-8")
            blocks = _blocks_from_markdown(md_text, task)
            if blocks:
                warnings.append(MergeWarning(
                    warning_type="overlap_no_provenance",
                    slice_file=task.slice_file,
                    message=(
                        f"No structured provenance for {task.slice_file}, "
                        "falling back to markdown block hashing."
                    ),
                ))

        n = OVERLAP_COMPARE_MAX_BLOCKS
        head_blocks = blocks[:n]
        tail_blocks = blocks[-n:] if len(blocks) > n else blocks[:]

        result[task.slice_file] = SliceProvenance(
            task=task,
            head_blocks=head_blocks,
            tail_blocks=tail_blocks,
            all_blocks=blocks,
        )

    return result


# ---------------------------------------------------------------------------
# Content.json loading (Phase 2 provenance)
# ---------------------------------------------------------------------------


def _try_load_content_jsons(
    raw_manifest: dict[str, Any],
    tasks: list[MergeTask],
) -> dict[str, dict[str, Any]]:
    """Try to load content.json for each slice from Phase 2 extract directory."""
    result: dict[str, dict[str, Any]] = {}

    # Try to find the Phase 2 extract manifest path
    source_extract_manifest = raw_manifest.get("source_extract_manifest", "")
    if not source_extract_manifest:
        return result

    for task in tasks:
        # Look for content.json in the task input dir (Phase 3 slice dir)
        # or try to go back to Phase 2
        content_path = task.input_dir / "content.json"
        if content_path.exists():
            try:
                data = json.loads(content_path.read_text(encoding="utf-8"))
                result[task.slice_file] = data
            except (json.JSONDecodeError, OSError) as e:
                LOGGER.warning("Failed to load content.json for %s: %s", task.slice_file, e)

    return result


def _blocks_from_content_json(data: dict[str, Any]) -> list[MergeBlockRef]:
    """Build MergeBlockRef list from Phase 2 content.json structure."""
    blocks: list[MergeBlockRef] = []

    source_pages = data.get("source_pages", [])
    for page_info in source_pages:
        source_page = int(page_info.get("source_page", 0))
        is_overlap = bool(page_info.get("is_overlap", False))

        # Process text blocks
        for block in page_info.get("blocks", []):
            text = block.get("text", "")
            blocks.append(MergeBlockRef(
                source_page=source_page,
                block_type=block.get("type", "paragraph"),
                is_overlap=is_overlap,
                dedupe_key=block.get("dedupe_key"),
                normalized_text_hash=text_hash(text) if text else None,
                asset_ref=None,
                markdown=text,
            ))

        # Process images
        for img in page_info.get("images", []):
            asset_path = img.get("asset_path", "")
            blocks.append(MergeBlockRef(
                source_page=source_page,
                block_type="image",
                is_overlap=is_overlap,
                dedupe_key=img.get("dedupe_key"),
                normalized_text_hash=None,
                asset_ref=asset_path,
                markdown=f"![image]({asset_path})" if asset_path else "",
            ))

        # Process tables
        for tbl in page_info.get("tables", []):
            md = tbl.get("markdown", "")
            asset_path = tbl.get("asset_path", "")
            blocks.append(MergeBlockRef(
                source_page=source_page,
                block_type="table",
                is_overlap=is_overlap,
                dedupe_key=tbl.get("dedupe_key"),
                normalized_text_hash=text_hash(md) if md else None,
                asset_ref=asset_path or None,
                markdown=md,
            ))

    return blocks


# ---------------------------------------------------------------------------
# Markdown-based fallback
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HTML_IMG_RE = re.compile(r"<img\s[^>]*src=[\"']([^\"']+)[\"']", re.IGNORECASE)


def _blocks_from_markdown(md_text: str, task: MergeTask) -> list[MergeBlockRef]:
    """Parse markdown into blocks for overlap comparison when no provenance available."""
    blocks: list[MergeBlockRef] = []
    lines = md_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Heading
        hm = _HEADING_RE.match(line)
        if hm:
            blocks.append(_make_block("heading", line, task))
            i += 1
            continue

        # Fenced code block
        fm = _FENCE_RE.match(line)
        if fm:
            fence = fm.group(1)
            code_lines = [line]
            i += 1
            while i < len(lines):
                code_lines.append(lines[i])
                if lines[i].strip().startswith(fence[:3]) and len(lines[i].strip()) >= len(fence):
                    i += 1
                    break
                i += 1
            block_text = "\n".join(code_lines)
            blocks.append(_make_block("code", block_text, task))
            continue

        # Image (standalone line)
        if _IMAGE_RE.match(line.strip()) or _HTML_IMG_RE.match(line.strip()):
            asset_ref = None
            m = _IMAGE_RE.search(line)
            if m:
                asset_ref = m.group(2)
            else:
                m2 = _HTML_IMG_RE.search(line)
                if m2:
                    asset_ref = m2.group(1)
            blocks.append(MergeBlockRef(
                source_page=task.start_page,
                block_type="image",
                is_overlap=False,
                dedupe_key=None,
                normalized_text_hash=text_hash(line),
                asset_ref=asset_ref,
                markdown=line,
            ))
            i += 1
            continue

        # Table (lines starting with |)
        if line.strip().startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            block_text = "\n".join(table_lines)
            blocks.append(_make_block("table", block_text, task))
            continue

        # Default: paragraph — collect until next empty line or structural element
        para_lines = []
        while i < len(lines) and lines[i].strip():
            if _HEADING_RE.match(lines[i]) or _FENCE_RE.match(lines[i]):
                break
            if lines[i].strip().startswith("|"):
                break
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            block_text = "\n".join(para_lines)
            blocks.append(_make_block("paragraph", block_text, task))

    return blocks


def _make_block(block_type: str, text: str, task: MergeTask) -> MergeBlockRef:
    return MergeBlockRef(
        source_page=task.start_page,
        block_type=block_type,
        is_overlap=False,
        dedupe_key=None,
        normalized_text_hash=text_hash(text),
        asset_ref=None,
        markdown=text,
    )

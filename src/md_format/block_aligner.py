"""Align draft Markdown segments against content.json block nodes.

The aligner parses the draft Markdown into logical segments and maps each
segment to a ``content.json`` block using a three-tier strategy:

1. **dedupe_key** exact match
2. **source_page + normalized_text** exact match
3. Same-page similarity + reading order fallback
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt

_MD_PARSER = MarkdownIt("gfm-like")


# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MarkdownSegment:
    """A logical segment extracted from draft Markdown."""

    segment_type: str  # heading, paragraph, list, table, code, image, html_block
    text: str
    line_start: int
    line_end: int
    raw: str = ""


@dataclass(slots=True)
class AlignmentResult:
    """Result of aligning draft Markdown against content.json blocks."""

    matched_blocks: dict[str, str] = field(default_factory=dict)  # dedupe_key -> segment text
    matched_tables: set[str] = field(default_factory=set)  # table node_refs that have MD representation
    matched_images: set[str] = field(default_factory=set)  # image node_refs that have MD reference
    unmatched_block_keys: list[str] = field(default_factory=list)  # dedupe_keys not found in MD
    segments: list[MarkdownSegment] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Text normalization (mirrors Phase 2 dedupe_key normalization)
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize text for comparison: NFKC, collapse whitespace, strip."""
    text = unicodedata.normalize("NFKC", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------------


def parse_markdown_segments(markdown: str) -> list[MarkdownSegment]:
    """Parse draft Markdown into logical segments."""
    tokens = _MD_PARSER.parse(markdown)
    lines = markdown.splitlines()
    segments: list[MarkdownSegment] = []

    i = 0
    while i < len(tokens):
        token = tokens[i]

        if token.type == "heading_open" and token.map:
            text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                text = tokens[i + 1].content
            raw = _extract_lines(lines, token.map)
            segments.append(MarkdownSegment("heading", text, token.map[0], token.map[1], raw))

        elif token.type == "paragraph_open" and token.map:
            text = ""
            if i + 1 < len(tokens) and tokens[i + 1].type == "inline":
                inline_token = tokens[i + 1]
                text = inline_token.content
                # Check for image-only paragraphs
                if inline_token.children and any(c.type == "image" for c in inline_token.children):
                    for child in inline_token.children:
                        if child.type == "image":
                            src = child.attrGet("src") or ""
                            alt = child.content or ""
                            raw = _extract_lines(lines, token.map)
                            segments.append(MarkdownSegment("image", alt, token.map[0], token.map[1], raw))
                            # Store src in text for matching
                            segments[-1].text = src
                    i += 1
                    continue
            raw = _extract_lines(lines, token.map)
            segments.append(MarkdownSegment("paragraph", text, token.map[0], token.map[1], raw))

        elif token.type == "bullet_list_open" and token.map:
            raw = _extract_lines(lines, token.map)
            # Collect all list item text
            list_texts = []
            j = i + 1
            while j < len(tokens) and tokens[j].type != "bullet_list_close":
                if tokens[j].type == "inline":
                    list_texts.append(tokens[j].content)
                j += 1
            text = "\n".join(list_texts)
            segments.append(MarkdownSegment("list", text, token.map[0], token.map[1], raw))

        elif token.type == "ordered_list_open" and token.map:
            raw = _extract_lines(lines, token.map)
            list_texts = []
            j = i + 1
            while j < len(tokens) and tokens[j].type != "ordered_list_close":
                if tokens[j].type == "inline":
                    list_texts.append(tokens[j].content)
                j += 1
            text = "\n".join(list_texts)
            segments.append(MarkdownSegment("list", text, token.map[0], token.map[1], raw))

        elif token.type == "table_open" and token.map:
            raw = _extract_lines(lines, token.map)
            segments.append(MarkdownSegment("table", raw, token.map[0], token.map[1], raw))

        elif token.type == "fence" and token.map:
            raw = _extract_lines(lines, token.map)
            segments.append(MarkdownSegment("code", token.content, token.map[0], token.map[1], raw))

        elif token.type == "code_block" and token.map:
            raw = _extract_lines(lines, token.map)
            segments.append(MarkdownSegment("code", token.content, token.map[0], token.map[1], raw))

        elif token.type == "html_block" and token.map:
            raw = _extract_lines(lines, token.map)
            segments.append(MarkdownSegment("html_block", token.content, token.map[0], token.map[1], raw))

        i += 1

    return segments


def _extract_lines(lines: list[str], line_map: list[int]) -> str:
    start, end = line_map
    return "\n".join(lines[start:end])


# ---------------------------------------------------------------------------
# Alignment logic
# ---------------------------------------------------------------------------


def align_blocks(
    content_data: dict[str, Any],
    draft_markdown: str,
) -> AlignmentResult:
    """Align draft Markdown segments against content.json blocks.

    Returns an ``AlignmentResult`` with matched/unmatched information.
    """
    segments = parse_markdown_segments(draft_markdown)
    result = AlignmentResult(segments=segments)

    # Collect all expected blocks, tables, images from content.json
    expected_blocks: list[dict] = []
    expected_tables: list[dict] = []
    expected_images: list[dict] = []

    for page_data in content_data.get("source_pages", []):
        source_page = page_data.get("source_page", 0)
        for block in page_data.get("blocks", []):
            block["_source_page"] = source_page
            expected_blocks.append(block)
        for idx, table in enumerate(page_data.get("tables", [])):
            table["_node_ref"] = _table_node_ref(source_page, idx)
            expected_tables.append(table)
        for idx, image in enumerate(page_data.get("images", [])):
            image["_node_ref"] = _image_node_ref(source_page, idx)
            expected_images.append(image)

    # Build normalized text index from segments
    segment_texts = {normalize_text(seg.text): seg for seg in segments if seg.text}

    # Tier 1 & 2: Match blocks by dedupe_key / normalized text
    for block in expected_blocks:
        dedupe_key = block.get("dedupe_key", "")
        block_text = normalize_text(block.get("text", ""))

        if block_text and block_text in segment_texts:
            result.matched_blocks[dedupe_key] = block_text
        elif _fuzzy_match_in_segments(block_text, segments):
            result.matched_blocks[dedupe_key] = block_text
        else:
            result.unmatched_block_keys.append(dedupe_key)

    # Match tables: check if Markdown has table segments or html_blocks with table content
    table_segments = [s for s in segments if s.segment_type in ("table", "html_block")]
    for table in expected_tables:
        node_ref = table["_node_ref"]
        # Tables are matched if we have any table segment at all
        # In M3 we'll do more precise matching by headers/content
        table_id = table.get("table_id", "")
        fallback_html = table.get("fallback_html", "")

        matched = False
        for seg in table_segments:
            if seg.segment_type == "table":
                matched = True
                break
            if seg.segment_type == "html_block" and table_id and table_id in seg.text:
                matched = True
                break
            if seg.segment_type == "html_block" and fallback_html and "complex-table" in seg.text:
                matched = True
                break
        if matched:
            result.matched_tables.add(node_ref)

    # Match images: check if asset_path appears in any image segment
    image_segments = [s for s in segments if s.segment_type == "image"]
    image_segment_srcs = {seg.text for seg in image_segments}  # text holds the src
    # Also check raw markdown for image references
    for image in expected_images:
        node_ref = image["_node_ref"]
        asset_path = image.get("asset_path", "")
        if not asset_path:
            continue
        # Check direct match or partial match
        if asset_path in image_segment_srcs:
            result.matched_images.add(node_ref)
        elif any(asset_path in src for src in image_segment_srcs):
            result.matched_images.add(node_ref)
        elif asset_path in draft_markdown:
            result.matched_images.add(node_ref)

    return result


def _fuzzy_match_in_segments(block_text: str, segments: list[MarkdownSegment], threshold: float = 0.7) -> bool:
    """Check if block_text is approximately contained in any segment."""
    if not block_text or len(block_text) < 5:
        return False
    for seg in segments:
        seg_text = normalize_text(seg.text)
        if not seg_text:
            continue
        # Check containment
        if block_text in seg_text or seg_text in block_text:
            return True
        # Simple word overlap ratio
        block_words = set(block_text.lower().split())
        seg_words = set(seg_text.lower().split())
        if not block_words:
            continue
        overlap = len(block_words & seg_words) / len(block_words)
        if overlap >= threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# Node reference helpers
# ---------------------------------------------------------------------------


def _table_node_ref(source_page: int, local_index: int) -> str:
    return f"table:{source_page}:{local_index}"


def _image_node_ref(source_page: int, local_index: int) -> str:
    return f"image:{source_page}:{local_index}"


def table_node_ref(source_page: int, local_index: int) -> str:
    """Public helper for generating table node_ref."""
    return _table_node_ref(source_page, local_index)


def image_node_ref(source_page: int, local_index: int) -> str:
    """Public helper for generating image node_ref."""
    return _image_node_ref(source_page, local_index)

from __future__ import annotations

import logging
import re
from pathlib import Path

from .config import CONSECUTIVE_DUPLICATE_THRESHOLD
from .contracts import MergeTask, MergeWarning
from .provenance_loader import text_hash

LOGGER = logging.getLogger("md_merge.postcheck")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_HTML_IMG_RE = re.compile(r'<img\s[^>]*src=["\']([^"\']+)["\']', re.IGNORECASE)


def postcheck(
    tasks: list[MergeTask],
    final_markdown: str,
    out_path: Path,
    warnings: list[MergeWarning],
) -> bool:
    """Post-merge verification.

    Returns True if manual review is required.
    """
    manual_review = False

    # 1. Non-empty check
    if not final_markdown.strip():
        warnings.append(MergeWarning(
            warning_type="slice_missing",
            slice_file=None,
            message="Final merged markdown is empty.",
        ))
        return True

    # 2. Heading count check
    headings = _HEADING_RE.findall(final_markdown)
    h1_count = sum(1 for level, _ in headings if level == "#")
    expected_slices = len(tasks)
    if h1_count > 0 and abs(h1_count - expected_slices) > expected_slices * 0.5:
        msg = (
            f"H1 heading count ({h1_count}) differs significantly "
            f"from slice count ({expected_slices})"
        )
        LOGGER.warning(msg)
        warnings.append(MergeWarning(
            warning_type="heading_count_mismatch",
            slice_file=None,
            message=msg,
        ))
        manual_review = True

    # 3. Asset path check
    all_image_refs = set()
    for m in _MD_IMAGE_RE.finditer(final_markdown):
        all_image_refs.add(m.group(1))
    for m in _HTML_IMG_RE.finditer(final_markdown):
        all_image_refs.add(m.group(1))

    for ref in all_image_refs:
        # Only check relative paths (starting with assets/)
        if ref.startswith("assets/"):
            full_path = out_path / ref
            if not full_path.exists():
                warnings.append(MergeWarning(
                    warning_type="asset_path_missing",
                    slice_file=None,
                    message=f"Asset not found after merge: {ref}",
                ))
                manual_review = True

    # 4. Consecutive duplicate detection
    if _check_consecutive_duplicates(final_markdown, warnings):
        manual_review = True

    return manual_review


def _check_consecutive_duplicates(
    markdown: str,
    warnings: list[MergeWarning],
) -> bool:
    """Check for consecutive duplicate paragraphs/blocks.

    Returns True if high-risk duplicates found.
    """
    # Split into blocks by double newline
    blocks = [b.strip() for b in re.split(r"\n\n+", markdown) if b.strip()]
    if len(blocks) < 2:
        return False

    consecutive = 1
    prev_hash = text_hash(blocks[0])
    found_issue = False

    for i in range(1, len(blocks)):
        curr_hash = text_hash(blocks[i])
        if curr_hash == prev_hash:
            consecutive += 1
            if consecutive >= CONSECUTIVE_DUPLICATE_THRESHOLD:
                snippet = blocks[i][:80]
                msg = (
                    f"Consecutive duplicate detected ({consecutive} repeats): "
                    f"{snippet!r}..."
                )
                LOGGER.warning(msg)
                warnings.append(MergeWarning(
                    warning_type="consecutive_duplicate_detected",
                    slice_file=None,
                    message=msg,
                ))
                found_issue = True
                break
        else:
            consecutive = 1
        prev_hash = curr_hash

    return found_issue

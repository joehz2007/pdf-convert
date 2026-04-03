from __future__ import annotations

import logging
from typing import Any

from .config import OVERLAP_COMPARE_MAX_BLOCKS
from .contracts import DedupDecision, MergeBlockRef, MergeTask, MergeWarning
from .merge_planner import AdjacentPair
from .provenance_loader import SliceProvenance

LOGGER = logging.getLogger("md_merge.overlap_resolver")


def resolve_overlaps(
    tasks: list[MergeTask],
    provenance: dict[str, SliceProvenance],
    pairs: list[AdjacentPair],
    warnings: list[MergeWarning],
) -> tuple[list[DedupDecision], dict[str, str]]:
    """Resolve overlap between adjacent slices.

    Returns:
        (dedup_decisions, slice_contents) where slice_contents maps
        slice_file -> final markdown after dedup.
    """
    # Initialize slice contents from provenance all_blocks
    slice_contents: dict[str, str] = {}
    for task in tasks:
        slice_contents[task.slice_file] = task.final_md_file.read_text(encoding="utf-8")

    dedup_decisions: list[DedupDecision] = []

    for pair in pairs:
        left_prov = provenance.get(pair.left.slice_file)
        right_prov = provenance.get(pair.right.slice_file)

        if not left_prov or not right_prov:
            dedup_decisions.append(DedupDecision(
                left_slice_file=pair.left.slice_file,
                right_slice_file=pair.right.slice_file,
                source_page=None,
                match_strategy="none",
                removed_from="none",
                removed_count=0,
                warning="Missing provenance for one or both slices",
            ))
            continue

        decision = _resolve_pair(
            pair, left_prov, right_prov, slice_contents, warnings,
        )
        dedup_decisions.append(decision)

    return dedup_decisions, slice_contents


def _resolve_pair(
    pair: AdjacentPair,
    left_prov: SliceProvenance,
    right_prov: SliceProvenance,
    slice_contents: dict[str, str],
    warnings: list[MergeWarning],
) -> DedupDecision:
    """Resolve overlap for a single adjacent pair.

    Strategy:
    1. Match tail blocks of left with head blocks of right
    2. Use dedupe_key > source_page+hash > asset_ref
    3. Remove matched blocks from right head
    4. Protect heading blocks that start a new chapter
    """
    left_tail = left_prov.tail_blocks
    right_head = right_prov.head_blocks

    if not left_tail or not right_head:
        return DedupDecision(
            left_slice_file=pair.left.slice_file,
            right_slice_file=pair.right.slice_file,
            source_page=None,
            match_strategy="none",
            removed_from="none",
            removed_count=0,
            warning=None,
        )

    # Find matching blocks at the boundary
    matched_right_indices: list[int] = []
    match_strategy: str = "none"
    match_page: int | None = None

    for ri, rb in enumerate(right_head):
        # Only process overlap-marked blocks or blocks within overlap window
        matched = False

        for lb in _left_match_candidates(left_prov, left_tail, rb, pair.left.end_page):
            strategy = _match_blocks(lb, rb)
            if strategy == "none" and _is_repeated_boundary_block(lb, rb, pair):
                strategy = "source_page_text_hash"
            if strategy != "none":
                # Protect: don't remove heading that starts a new chapter
                if _is_chapter_heading(rb, pair.right):
                    if _is_repeated_overlap_heading(lb, rb) or _is_repeated_boundary_block(lb, rb, pair):
                        matched = True
                        match_strategy = strategy
                        match_page = rb.source_page
                        matched_right_indices.append(ri)
                        break
                    LOGGER.debug(
                        "Skipping chapter heading dedup: %s",
                        rb.markdown[:60],
                    )
                    continue

                matched = True
                match_strategy = strategy
                match_page = rb.source_page
                matched_right_indices.append(ri)
                break

        if not matched and matched_right_indices:
            # Stop matching once we hit a non-matching block after some matches
            break

    removed_count = len(matched_right_indices)

    if removed_count > 0:
        # Remove matched blocks from right slice content
        _remove_blocks_from_content(
            pair.right.slice_file,
            right_prov,
            matched_right_indices,
            slice_contents,
        )
        LOGGER.info(
            "Dedup %s→%s: removed %d blocks (strategy=%s)",
            pair.left.slice_file,
            pair.right.slice_file,
            removed_count,
            match_strategy,
        )
    else:
        # Check if there should have been overlap
        has_overlap = any(b.is_overlap for b in right_head) or any(
            b.is_overlap for b in left_tail
        )
        if has_overlap:
            warn_msg = (
                f"Overlap blocks detected but no stable match between "
                f"{pair.left.slice_file} and {pair.right.slice_file}"
            )
            LOGGER.warning(warn_msg)
            warnings.append(MergeWarning(
                warning_type="overlap_match_unstable",
                slice_file=pair.right.slice_file,
                message=warn_msg,
            ))

    return DedupDecision(
        left_slice_file=pair.left.slice_file,
        right_slice_file=pair.right.slice_file,
        source_page=match_page,
        match_strategy=match_strategy,  # type: ignore[arg-type]
        removed_from="right_head" if removed_count > 0 else "none",
        removed_count=removed_count,
        warning=None if removed_count > 0 or not any(
            b.is_overlap for b in right_head
        ) else "Unstable overlap match, content preserved",
    )


def _match_blocks(left: MergeBlockRef, right: MergeBlockRef) -> str:
    """Try to match two blocks. Returns match strategy or 'none'."""
    # Priority 1: dedupe_key
    if (
        left.dedupe_key
        and right.dedupe_key
        and left.dedupe_key == right.dedupe_key
    ):
        return "dedupe_key"

    # Priority 2: source_page + block_type + normalized_text_hash
    if (
        left.source_page == right.source_page
        and left.block_type == right.block_type
        and left.normalized_text_hash
        and right.normalized_text_hash
        and left.normalized_text_hash == right.normalized_text_hash
    ):
        return "source_page_text_hash"

    # Priority 3: asset_ref
    if (
        left.asset_ref
        and right.asset_ref
        and left.asset_ref == right.asset_ref
    ):
        return "asset_ref"

    return "none"


def _is_chapter_heading(block: MergeBlockRef, task: MergeTask) -> bool:
    """Check if a block is a chapter-starting heading that should be protected."""
    if block.block_type != "heading":
        return False
    # Protect headings at the start page of the slice (new chapter boundary)
    if block.source_page == task.start_page:
        md = block.markdown.strip()
        # Only protect top-level headings (# or ##)
        if md.startswith("# ") or md.startswith("## "):
            return True
    return False


def _is_repeated_overlap_heading(left: MergeBlockRef, right: MergeBlockRef) -> bool:
    if left.block_type != "heading" or right.block_type != "heading":
        return False
    if left.source_page != right.source_page:
        return False
    if left.dedupe_key and right.dedupe_key and left.dedupe_key == right.dedupe_key:
        return True
    return bool(
        left.normalized_text_hash
        and right.normalized_text_hash
        and left.normalized_text_hash == right.normalized_text_hash
    )


def _is_repeated_boundary_block(left: MergeBlockRef, right: MergeBlockRef, pair: AdjacentPair) -> bool:
    if pair.left.end_page != pair.right.start_page:
        return False
    if left.block_type != right.block_type:
        return False
    if bool(
        left.normalized_text_hash
        and right.normalized_text_hash
        and left.normalized_text_hash == right.normalized_text_hash
    ):
        return True
    if left.block_type == "heading":
        return _heading_title(left) == _heading_title(right)
    return False


def _heading_title(block: MergeBlockRef) -> str:
    return block.markdown.lstrip("#").strip()


def _remove_blocks_from_content(
    slice_file: str,
    prov: SliceProvenance,
    matched_indices: list[int],
    slice_contents: dict[str, str],
) -> None:
    """Remove matched head blocks from slice content.

    Strategy: find and remove the markdown text of matched blocks
    from the beginning of the slice content.
    """
    content = slice_contents[slice_file]
    blocks_to_remove = [prov.head_blocks[i] for i in sorted(matched_indices)]

    for block in blocks_to_remove:
        block_md = block.markdown.strip()
        if not block_md:
            continue

        # Find and remove the first occurrence of this block
        idx = content.find(block_md)
        if idx != -1:
            # Remove the block and any surrounding blank lines
            before = content[:idx]
            after = content[idx + len(block_md):]

            # Clean up extra blank lines at the junction
            after = after.lstrip("\n")
            if before.endswith("\n\n"):
                before = before.rstrip("\n") + "\n"

            content = before + after

    slice_contents[slice_file] = content


def _left_match_candidates(
    left_prov: SliceProvenance,
    left_tail: list[MergeBlockRef],
    right_block: MergeBlockRef,
    left_end_page: int,
) -> list[MergeBlockRef]:
    candidates = list(left_tail)
    if not right_block.is_overlap or right_block.source_page > left_end_page:
        return candidates

    seen = {
        (block.source_page, block.block_type, block.dedupe_key, block.normalized_text_hash, block.asset_ref, block.markdown)
        for block in candidates
    }
    for block in left_prov.all_blocks:
        key = (
            block.source_page,
            block.block_type,
            block.dedupe_key,
            block.normalized_text_hash,
            block.asset_ref,
            block.markdown,
        )
        if key in seen or block.source_page != right_block.source_page:
            continue
        candidates.append(block)
        seen.add(key)
    return candidates

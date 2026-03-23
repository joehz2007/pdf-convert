from __future__ import annotations

import logging

from .config import MERGE_SEPARATOR_STYLE
from .contracts import MergeTask

LOGGER = logging.getLogger("md_merge.stitcher")


def stitch(
    tasks: list[MergeTask],
    slice_contents: dict[str, str],
    *,
    separator_style: str | None = None,
) -> str:
    """Stitch all slice contents into a single markdown string.

    Order strictly follows task.order_index (tasks must be pre-sorted).
    """
    style = separator_style or MERGE_SEPARATOR_STYLE
    separator = _build_separator(style)

    parts: list[str] = []
    for task in tasks:
        content = slice_contents.get(task.slice_file, "")
        content = content.strip()
        if content:
            parts.append(content)

    result = separator.join(parts)

    # Ensure trailing newline
    if result and not result.endswith("\n"):
        result += "\n"

    LOGGER.info(
        "Stitched %d slices, total %d characters",
        len(parts), len(result),
    )
    return result


def _build_separator(style: str) -> str:
    if style == "thematic_break":
        return "\n\n---\n\n"
    # Default: blank_line
    return "\n\n"

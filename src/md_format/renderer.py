"""Renderer — converts NormalizedDocument to raw Markdown.

Outputs blocks in strict ``source_page + reading_order`` order,
separated by blank lines.  Returns the rendered Markdown string and
render statistics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .contracts import NormalizedDocument

LOGGER = logging.getLogger("md_format.renderer")


@dataclass(slots=True)
class RenderStats:
    """Statistics from the rendering pass."""

    char_count: int = 0
    block_count: int = 0
    table_count: int = 0
    image_count: int = 0


def render(doc: NormalizedDocument) -> tuple[str, RenderStats]:
    """Render a NormalizedDocument into a Markdown string.

    Returns (markdown_string, RenderStats).
    """
    parts: list[str] = []
    stats = RenderStats()

    for page in doc.pages:
        for block in page.blocks:
            md = block.markdown.strip()
            if not md:
                continue

            parts.append(md)
            stats.block_count += 1

            if block.block_type == "table":
                stats.table_count += 1
            elif block.block_type == "image":
                stats.image_count += 1

    rendered = "\n\n".join(parts)
    if rendered:
        rendered += "\n"

    stats.char_count = len(rendered)

    LOGGER.debug(
        "Rendered %d blocks, %d chars, %d tables, %d images",
        stats.block_count,
        stats.char_count,
        stats.table_count,
        stats.image_count,
    )

    return rendered, stats

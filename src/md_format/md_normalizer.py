"""Markdown normalizer — style standardization via mdformat.

Applies ``mdformat`` with ``mdformat-gfm`` to produce consistent
Markdown output (ATX headings, fenced code blocks, uniform list
indentation, pipe table formatting).

This module must NOT delete content blocks.
"""

from __future__ import annotations

import logging

import mdformat

LOGGER = logging.getLogger("md_format.md_normalizer")


def normalize_markdown(markdown: str) -> str:
    """Apply mdformat + mdformat-gfm to standardize Markdown style.

    Returns the normalized Markdown string.
    """
    if not markdown or not markdown.strip():
        return markdown

    try:
        result = mdformat.text(
            markdown,
            options={"wrap": "no"},
            extensions=["gfm"],
        )
        return result
    except Exception:
        LOGGER.warning("mdformat failed, returning original markdown", exc_info=True)
        return markdown

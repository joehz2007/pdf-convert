from __future__ import annotations

# ---------------------------------------------------------------------------
# CLI defaults
# ---------------------------------------------------------------------------

DEFAULT_COPY_ASSETS: bool = True
DEFAULT_OVERWRITE: bool = False
DEFAULT_FAIL_ON_MANUAL_REVIEW: bool = False
DEFAULT_ALLOW_UPSTREAM_MANUAL_REVIEW: bool = False
DEFAULT_LOG_LEVEL: str = "INFO"

# ---------------------------------------------------------------------------
# Overlap comparison
# ---------------------------------------------------------------------------

OVERLAP_COMPARE_MAX_BLOCKS: int = 20

# ---------------------------------------------------------------------------
# Merge separator
# ---------------------------------------------------------------------------

MERGE_SEPARATOR_STYLE: str = "blank_line"  # "blank_line" | "thematic_break"

# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

TEXT_HASH_ALGORITHM: str = "sha256"

# ---------------------------------------------------------------------------
# Post-check thresholds
# ---------------------------------------------------------------------------

MAX_HEADING_LEVEL: int = 6
CONSECUTIVE_DUPLICATE_THRESHOLD: int = 3

# ---------------------------------------------------------------------------
# Generator tag
# ---------------------------------------------------------------------------

GENERATOR_VERSION: str = "phase4-v1"

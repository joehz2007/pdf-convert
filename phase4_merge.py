from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from md_merge.config import (  # noqa: E402
    DEFAULT_COPY_ASSETS,
    DEFAULT_FAIL_ON_MANUAL_REVIEW,
    DEFAULT_LOG_LEVEL,
    DEFAULT_OVERWRITE,
    DEFAULT_ALLOW_UPSTREAM_MANUAL_REVIEW,
)
from md_merge.errors import MdMergeError  # noqa: E402
from md_merge.pipeline import run_pipeline  # noqa: E402

LOGGER = logging.getLogger("md_merge.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 4: Validate, deduplicate overlap regions, and merge "
            "chapter-level Markdown slices into a single deliverable file."
        ),
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Path to the Phase 3 output directory (containing format_manifest.json).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for merged artifacts. Default: <source>_merged/ beside input.",
    )
    parser.add_argument(
        "--copy-assets",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_COPY_ASSETS,
        help=f"Copy assets to output directory for self-contained delivery. Default: {DEFAULT_COPY_ASSETS}.",
    )
    parser.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_OVERWRITE,
        help="Allow overwriting existing output directory. Default: false (fail if exists).",
    )
    parser.add_argument(
        "--fail-on-manual-review",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_FAIL_ON_MANUAL_REVIEW,
        help="Exit with non-zero code if any slice or final result requires manual review.",
    )
    parser.add_argument(
        "--allow-upstream-manual-review",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_ALLOW_UPSTREAM_MANUAL_REVIEW,
        help=(
            "Continue merging even when upstream slices are flagged for manual review. "
            "Default: false (block merging if upstream flags exist)."
        ),
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        help=f"Logging level. Default: {DEFAULT_LOG_LEVEL}.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        result = run_pipeline(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            copy_assets=args.copy_assets,
            overwrite=args.overwrite,
            fail_on_manual_review=args.fail_on_manual_review,
            allow_upstream_manual_review=args.allow_upstream_manual_review,
        )
        LOGGER.info(
            "Phase 4 merge complete: status=%s slices=%s/%s removed_overlap=%s warnings=%s elapsed=%dms",
            result.status,
            result.merged_slices,
            result.total_slices,
            result.removed_overlap_blocks,
            result.warning_count,
            result.elapsed_ms,
        )
        if args.fail_on_manual_review and result.manual_review_required:
            return 1
        return 0 if result.status == "success" else 1
    except MdMergeError as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

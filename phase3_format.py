from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from md_format.config import DEFAULT_LOG_LEVEL, DEFAULT_WORKERS, DEFAULT_COPY_ASSETS  # noqa: E402
from md_format.errors import MdFormatError  # noqa: E402
from md_format.pipeline import run_pipeline  # noqa: E402
from pdf_slicer.log_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger("md_format.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Format and verify Phase 2 draft Markdown against content.json for completeness and structure."
    )
    parser.add_argument("--input-dir", required=True, help="Path to the Phase 2 output directory (containing extract_manifest.json).")
    parser.add_argument("--output-dir", help="Optional output directory for Phase 3 artifacts.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Number of slice-level workers. Default: {DEFAULT_WORKERS}.")
    parser.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Whether to overwrite an existing output directory.",
    )
    parser.add_argument(
        "--fail-on-manual-review",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Exit with non-zero code if any slice requires manual review.",
    )
    parser.add_argument(
        "--copy-assets",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_COPY_ASSETS,
        help=f"Copy Phase 2 assets to output directory. Default: {DEFAULT_COPY_ASSETS}.",
    )
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, help=f"Logging level. Default: {DEFAULT_LOG_LEVEL}.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        manifest = run_pipeline(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            workers=args.workers,
            overwrite=args.overwrite,
            fail_on_manual_review=args.fail_on_manual_review,
            copy_assets=args.copy_assets,
        )
        LOGGER.info(
            "Completed Phase 3 formatting: success=%s failed=%s manual_review=%s total_ms=%s",
            manifest.success_count,
            manifest.failed_count,
            manifest.manual_review_count,
            manifest.total_elapsed_ms,
        )
        if args.fail_on_manual_review and manifest.manual_review_count > 0:
            return 1
        return 0 if manifest.failed_count == 0 else 1
    except MdFormatError as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

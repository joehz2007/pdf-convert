from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pdf_extract.config import DEFAULT_LOG_LEVEL, DEFAULT_WORKERS  # noqa: E402
from pdf_extract.errors import PdfExtractError  # noqa: E402
from pdf_extract.pipeline import run_pipeline  # noqa: E402
from pdf_slicer.log_utils import configure_logging  # noqa: E402

LOGGER = logging.getLogger("pdf_extract.cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract Markdown drafts and structured content from sliced digital PDFs.")
    parser.add_argument("--input-manifest", required=True, help="Path to the Phase 1 manifest.json file.")
    parser.add_argument("--output-dir", help="Optional output directory for Phase 2 artifacts.")
    parser.add_argument("--emit-md", action=argparse.BooleanOptionalAction, default=True, help="Whether to write Markdown draft files.")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Number of slice-level workers. Default: {DEFAULT_WORKERS}.")
    parser.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Whether to overwrite an existing output directory.",
    )
    parser.add_argument("--log-level", default=DEFAULT_LOG_LEVEL, help=f"Logging level. Default: {DEFAULT_LOG_LEVEL}.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    try:
        extract_manifest = run_pipeline(
            manifest_path=args.input_manifest,
            output_dir=args.output_dir,
            emit_md=args.emit_md,
            overwrite=args.overwrite,
            workers=args.workers,
        )
        LOGGER.info(
            "Completed Phase 2 extraction: success=%s failed=%s total_ms=%s",
            extract_manifest.success_count,
            extract_manifest.failed_count,
            extract_manifest.total_elapsed_ms,
        )
        return 0 if extract_manifest.failed_count == 0 else 1
    except PdfExtractError as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())

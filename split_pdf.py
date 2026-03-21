"""Phase 1 CLI 入口。

串联预检、章节识别、切分规划和结果写出四个阶段。
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from time import perf_counter

from pdf_slicer import PdfDocument, PdfSliceWriter, SemanticAnalyzer, SplitPlanner, recognize_chapters
from pdf_slicer.errors import PdfSlicerError
from pdf_slicer.log_utils import configure_logging, measure_stage

LOGGER = logging.getLogger("pdf_slicer.cli")


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Split a large digital PDF into semantic slices.")
    parser.add_argument("input_pdf", help="Path to the source PDF file.")
    parser.add_argument("--output-dir", help="Optional output directory for sliced files.")
    parser.add_argument("--max-pages", type=int, default=20, help="Target maximum pages per slice. Default: 20.")
    parser.add_argument("--log-level", default="INFO", help="Logging level. Default: INFO.")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行 Phase 1 切分流程并返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    metrics: dict[str, int] = {}
    total_start = perf_counter()
    document = None
    try:
        with measure_stage(metrics, "precheck_ms"):
            document = PdfDocument.open(args.input_pdf)

        with measure_stage(metrics, "structure_detect_ms"):
            recognition = recognize_chapters(document)

        analyzer = SemanticAnalyzer(document)
        with measure_stage(metrics, "layout_analysis_ms"):
            planner = SplitPlanner(
                document=document,
                analyzer=analyzer,
                max_pages=args.max_pages,
                hard_max_pages=25,
            )
            slice_plans = planner.plan(recognition.chapters)

        with measure_stage(metrics, "split_write_ms"):
            writer = PdfSliceWriter(document)
            output_dir = writer.write(
                slices=slice_plans,
                fallback_level=recognition.fallback_level,
                output_dir=args.output_dir,
            )

        metrics["total_ms"] = int((perf_counter() - total_start) * 1000)
        LOGGER.info("Completed PDF slicing: output_dir=%s metrics=%s", Path(output_dir), metrics)
        return 0
    except PdfSlicerError as exc:
        metrics["total_ms"] = int((perf_counter() - total_start) * 1000)
        LOGGER.error("%s metrics=%s", exc, metrics)
        return 1
    finally:
        if document is not None:
            document.close()


if __name__ == "__main__":
    sys.exit(main())

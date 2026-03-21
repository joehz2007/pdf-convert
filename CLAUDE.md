# PDF-Convert Project

## Overview
Phase 1 of a multi-phase PDF-to-Markdown pipeline. This phase implements a **Python CLI tool** that splits large digital PDFs into structured sub-files based on chapter boundaries, page limits, and semantic integrity constraints.

## Tech Stack
- **Language**: Python 3.10+
- **Core Dependency**: PyMuPDF >= 1.23.0 (for `page.find_tables()` API)
- **Testing**: pytest >= 8.0.0
- **Deployment**: CLI script (`python split_pdf.py <input.pdf>`)

## Project Structure
```
split_pdf.py              # CLI entry point (Orchestrator)
pdf_slicer/
  __init__.py             # Package exports
  models.py               # ChapterNode, SlicePlan, RecognitionResult dataclasses
  errors.py               # Custom exception hierarchy
  log_utils.py            # Logging config & stage timing
  document.py             # PyMuPDF wrapper (1-based page numbers)
  recognizer.py           # Chapter recognition (TOC/bookmark or layout fallback)
  semantic_analyzer.py    # Semantic block integrity detection (tables/code/paragraphs/figures)
  split_planner.py        # Split strategy planner (merge/split/overlap injection)
  writer.py               # PDF slicing output & manifest.json generation
tests/
  conftest.py             # PDF factory fixture
  test_cli.py             # CLI integration test
  test_document.py        # Document wrapper tests
  test_recognizer.py      # Chapter recognition tests
  test_semantic_analyzer.py # Semantic boundary detection tests
  test_split_planner.py   # Planning logic tests
  test_writer.py          # Output & manifest tests
docs/
  PRD-PDF切分需求.md       # Product Requirements Document (V1.3)
  技术方案-PDF切分(Phase1).md # Technical Implementation Plan
```

## Key Design Decisions
- **Page numbering**: All public APIs use 1-based page numbers; 0-based conversion is encapsulated in `document.py`
- **Three-level fallback**: Level 1 (TOC/bookmarks) -> Level 2 (regex + font heuristics) -> Level 3 (unsupported, error exit)
- **Split rules priority**: P0 (must produce output) > P1 (semantic integrity) > P2 (chapter integrity) > P3 (overlap pages) > P4 (target 20 pages) > P5 (hard limit 25 pages) > P6 (oversized exception)
- **Forward-only greedy merge**: Small chapters merge forward only, never backtrack

## Commands
```bash
# Run the tool
python split_pdf.py <input.pdf> [--output-dir <dir>] [--max-pages 20] [--log-level INFO]

# Run tests
python -m pytest tests/ -q

# Install dependencies
pip install -r requirements.txt
```

## Conventions
- All page numbers in logs, filenames, and manifest.json are 1-based physical page numbers
- Output directory defaults to `<source_filename>_split/` beside the source file
- manifest.json uses enumerated values for `split_mode`, `boundary_reason`, `exception_type`
- Illegal filename characters are replaced with underscores

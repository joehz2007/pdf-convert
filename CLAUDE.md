# PDF-Convert Project

## Overview
Multi-phase PDF-to-Markdown pipeline. Phase 1 splits PDFs, Phase 2 extracts content, Phase 3 formats Markdown, Phase 4 validates and merges into a single deliverable file.

## Tech Stack
- **Language**: Python 3.10+
- **Core Dependencies**: PyMuPDF == 1.27.1, pymupdf4llm == 0.3.4, markdown-it-py == 3.0.0, mdformat == 0.7.21, mdformat-gfm == 0.3.6
- **Testing**: pytest == 7.4.3
- **CLI Scripts**: `split_pdf.py` (Phase 1), `phase2_extract.py` (Phase 2), `phase3_format.py` (Phase 3), `phase4_merge.py` (Phase 4)

## Project Structure
```
split_pdf.py              # Phase 1 CLI — PDF splitting
phase2_extract.py         # Phase 2 CLI — content extraction
phase3_format.py          # Phase 3 CLI — Markdown formatting
phase4_merge.py           # Phase 4 CLI — validation, dedup & merge
pdf_slicer/               # Phase 1 core
src/
  pdf_extract/            # Phase 2 core
  md_format/              # Phase 3 core
  md_merge/               # Phase 4 core
tests/
  test_cli.py
  test_split_planner.py   # Phase 1 tests
  test_phase2_*.py        # Phase 2 tests 
  test_phase3_*.py        # Phase 3 tests 
  test_phase4_*.py        # Phase 4 tests
docs/
  PRD-*.md                # Phases 1-4 Product Requirements
  开发计划-*.md           # Phases 1-4 Development Plans
  技术方案-*.md           # Phases 1-4 Technical Designs
```

## Key Design Decisions
- **Page numbering**: All public APIs use 1-based page numbers; 0-based conversion is encapsulated in `document.py`
- **Three-level fallback**: Level 1 (TOC/bookmarks) -> Level 2 (regex + font heuristics) -> Level 3 (unsupported, error exit)
- **Split rules priority**: P0 (must produce output) > P1 (semantic integrity) > P2 (chapter integrity) > P3 (overlap pages) > P4 (target 20 pages) > P5 (hard limit 25 pages) > P6 (oversized exception)
- **Forward-only greedy merge**: Small chapters merge forward only, never backtrack

## Commands
```bash
# Phase 1: Split PDF
python split_pdf.py <input.pdf> [--output-dir <dir>] [--max-pages 20] [--log-level INFO]

# Phase 2: Extract Content
python phase2_extract.py --input-manifest <manifest.json> [--output-dir <dir>]

# Phase 3: Format Markdown
python phase3_format.py --input-dir <extract_dir> [--output-dir <dir>]

# Phase 4: Merge chapter Markdown into single file
python phase4_merge.py --input-dir <format_dir> [--output-dir <dir>] [--copy-assets] [--overwrite] [--fail-on-manual-review] [--allow-upstream-manual-review]

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

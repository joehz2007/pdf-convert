# PDF-Convert Project

## Overview
Multi-phase PDF-to-Markdown pipeline. Phase 1 splits PDFs, Phase 2 extracts content, Phase 3 formats Markdown, Phase 4 validates and merges into a single deliverable file.

## Tech Stack
- **Language**: Python 3.10+
- **Core Dependencies**: PyMuPDF >= 1.23.0, markdown-it-py == 3.0.0
- **Testing**: pytest
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
    __init__.py
    config.py             # Constants & defaults
    contracts.py          # All dataclasses/enums (MergeTask, MergeBlockRef, DedupDecision, etc.)
    errors.py             # Domain exceptions
    manifest_loader.py    # Load & validate format_manifest.json
    provenance_loader.py  # Load overlap provenance from content.json or markdown fallback
    merge_planner.py      # Generate adjacent pairs & asset plans
    overlap_resolver.py   # Overlap dedup with heading/code protection
    asset_relinker.py     # Copy assets & rewrite image paths
    stitcher.py           # Stitch slices into single markdown
    postcheck.py          # Post-merge validation (headings, duplicates, assets)
    writer.py             # Write final .md, merge_report.json, merge_manifest.json
    pipeline.py           # Top-level orchestrator
tests/
  test_phase4_*.py        # Phase 4 tests (72 tests)
docs/
  技术方案-校验与拼接(Phase4).md
  开发计划-校验与拼接(Phase4).md
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

# Repository Guidelines

## Project Structure & Module Organization
This repository implements a four-phase PDF-to-Markdown pipeline.

- `pdf_slicer/`: Phase 1 logic for PDF inspection, chapter recognition, split planning, and slice writing.
- `src/pdf_extract/`: Phase 2 extraction from sliced PDFs into `content.json`, Markdown drafts, and assets.
- `src/md_format/`: Phase 3 normalization, repair, rendering, coverage audit, and post-checks.
- `src/md_merge/`: Phase 4 validation, overlap removal, asset relinking, and final Markdown merge.
- Top-level CLIs: `split_pdf.py`, `phase2_extract.py`, `phase3_format.py`, `phase4_merge.py`.
- `tests/`: pytest coverage for each phase plus CLI and fixture support in `conftest.py`.
- `docs/`: PRD, phase plans, and technical design notes.

Keep generated outputs in temporary folders such as `*_split`, `*_extract`, `*_format`, and `*_merged`; do not mix them into source packages.

## Build, Test, and Development Commands
- `python -m venv .venv && .\.venv\Scripts\Activate.ps1`: create and activate a local virtual environment.
- `pip install -r requirements.txt`: install runtime and test dependencies.
- `pytest`: run the full test suite configured by `pytest.ini`.
- `pytest tests/test_phase4_pipeline_smoke.py`: run a focused phase-level smoke test.
- `python split_pdf.py input.pdf --output-dir out_split`: run Phase 1 manually.
- `python phase2_extract.py --input-manifest out_split/manifest.json`: run Phase 2.
- `python phase3_format.py --input-dir out_extract`: run Phase 3.
- `python phase4_merge.py --input-dir out_format`: run Phase 4.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, `from __future__ import annotations`, type hints on public functions, and small modules with explicit contracts. Use `snake_case` for files, functions, variables, and test names; use `PascalCase` for classes and error types. Prefer `pathlib.Path` over raw path strings and keep loggers module-scoped.

## Testing Guidelines
Write tests with `pytest`, colocated under `tests/` and named `test_<unit>.py`. Mirror the phase in the filename, for example `test_phase3_writer.py` or `test_phase4_postcheck.py`. Reuse fixtures from `tests/conftest.py` to build synthetic PDFs and manifests instead of checking in sample binaries. Add or update smoke tests whenever a pipeline contract changes.

## Commit & Pull Request Guidelines
Recent history follows concise Conventional Commit prefixes such as `feat:` and `fix:`, usually with the phase and milestone in the subject, for example `feat: Phase 3 M4 ...`. Keep commits scoped to one change set and mention the affected phase explicitly.

Pull requests should summarize the scenario, list touched phases/modules, and include the exact validation commands run. If output structure, manifests, or Markdown rendering changes, include a short before/after example in the PR description.

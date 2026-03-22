from __future__ import annotations

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_WORKERS = 1
DEFAULT_COPY_ASSETS = True

# Coverage thresholds — any coverage < 1.0 triggers an issue
TEXT_COVERAGE_THRESHOLD = 1.0
TABLE_COVERAGE_THRESHOLD = 1.0
IMAGE_COVERAGE_THRESHOLD = 1.0
OVERLAP_COVERAGE_THRESHOLD = 1.0

# Asset path strategy when --copy-assets=false
RELATIVE_ASSET_STRATEGY = "reuse_phase2"

GENERATOR_VERSION = "phase3-v1"

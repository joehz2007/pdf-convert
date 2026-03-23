from __future__ import annotations


class MdMergeError(Exception):
    """Base exception for Phase 4 merge pipeline."""


class InvalidFormatManifestError(MdMergeError):
    """format_manifest.json is missing or structurally invalid."""


class MissingFinalMarkdownError(MdMergeError):
    """Expected final markdown file not found on disk."""


class MissingReviewReportError(MdMergeError):
    """Expected review_report.json not found on disk."""


class UpstreamSliceFailedError(MdMergeError):
    """One or more upstream slices have status != success."""


class OutputExistsError(MdMergeError):
    """Output directory already exists and --overwrite is not set."""


class ProvenanceLoadError(MdMergeError):
    """Failed to load provenance / traceability information."""


class OverlapResolutionError(MdMergeError):
    """Fatal error during overlap resolution."""


class AssetRelinkError(MdMergeError):
    """Fatal error during asset copy / relink."""


class PostMergeVerificationError(MdMergeError):
    """Post-merge verification detected a fatal issue."""

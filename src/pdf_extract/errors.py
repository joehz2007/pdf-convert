from __future__ import annotations


class PdfExtractError(Exception):
    """Base exception for the Phase 2 extractor."""


class MissingSliceError(PdfExtractError):
    """A slice PDF listed in the manifest is missing."""


class InvalidManifestError(PdfExtractError):
    """The Phase 1 manifest is missing required data or is malformed."""


class UnsupportedInputError(PdfExtractError):
    """The input is outside the currently supported Phase 2 scope."""


class EmptyExtractionError(PdfExtractError):
    """The extractor produced no usable Markdown output."""


class PageMappingError(PdfExtractError):
    """Page-level extraction output cannot be mapped back to source pages."""


class AssetExportError(PdfExtractError):
    """Static asset export failed."""


class OutputExistsError(PdfExtractError):
    """The output directory already exists and overwrite is disabled."""

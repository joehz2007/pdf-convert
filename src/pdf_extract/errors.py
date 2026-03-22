from __future__ import annotations


class PdfExtractError(Exception):
    """Base exception for the Phase 2 extractor."""

    error_code = "pdf_extract_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class MissingSliceError(PdfExtractError):
    """A slice PDF listed in the manifest is missing."""

    error_code = "missing_slice"


class InvalidManifestError(PdfExtractError):
    """The Phase 1 manifest is missing required data or is malformed."""

    error_code = "invalid_manifest"


class UnsupportedInputError(PdfExtractError):
    """The input is outside the currently supported Phase 2 scope."""

    error_code = "unsupported_input"


class EmptyExtractionError(PdfExtractError):
    """The extractor produced no usable Markdown output."""

    error_code = "empty_extraction"


class PageMappingError(PdfExtractError):
    """Page-level extraction output cannot be mapped back to source pages."""

    error_code = "page_mapping_error"


class AssetExportError(PdfExtractError):
    """Static asset export failed."""

    error_code = "asset_export_failed"


class OutputExistsError(PdfExtractError):
    """The output directory already exists and overwrite is disabled."""

    error_code = "output_exists"

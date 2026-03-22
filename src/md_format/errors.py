from __future__ import annotations


class MdFormatError(Exception):
    """Base exception for the Phase 3 formatter."""

    error_code = "md_format_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class InvalidExtractManifestError(MdFormatError):
    """The Phase 2 extract_manifest.json is missing required data or is malformed."""

    error_code = "invalid_extract_manifest"


class MissingContentFileError(MdFormatError):
    """A content.json referenced in the extract manifest is missing."""

    error_code = "missing_content_file"


class MissingDraftMarkdownError(MdFormatError):
    """A draft Markdown file referenced in the extract manifest is missing."""

    error_code = "missing_draft_markdown"


class InvalidContentSchemaError(MdFormatError):
    """The content.json structure does not match the expected Phase 2 schema."""

    error_code = "invalid_content_schema"


class MarkdownParseError(MdFormatError):
    """Markdown parsing produced unexpected or invalid results."""

    error_code = "markdown_parse_error"


class AssetReferenceError(MdFormatError):
    """An asset referenced in content.json or Markdown is missing on disk."""

    error_code = "asset_reference_error"


class PostcheckFailedError(MdFormatError):
    """Post-render verification detected structure drift or content loss."""

    error_code = "postcheck_failed"


class OutputExistsError(MdFormatError):
    """The output directory already exists and overwrite is disabled."""

    error_code = "output_exists"

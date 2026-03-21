class PdfSlicerError(Exception):
    """Base exception for the Phase 1 slicer."""


class InputPdfNotFoundError(PdfSlicerError):
    """Input PDF path does not exist."""


class EmptyPdfError(PdfSlicerError):
    """Input PDF contains zero pages."""


class EncryptedPdfError(PdfSlicerError):
    """Input PDF is encrypted or password protected."""


class DamagedPdfError(PdfSlicerError):
    """Input PDF is damaged or unreadable."""


class UnsupportedInputError(PdfSlicerError):
    """Input PDF is outside the current supported scope."""

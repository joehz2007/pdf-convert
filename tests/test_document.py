from __future__ import annotations

import pytest

from pdf_slicer.document import PdfDocument
from pdf_slicer.errors import DamagedPdfError, EncryptedPdfError, InputPdfNotFoundError, UnsupportedInputError


def test_open_pdf_and_expose_1_based_pages(create_pdf):
    pdf_path = create_pdf(
        "sample.pdf",
        pages=[
            {"heading": "Chapter 1 Overview", "body": "First page body"},
            {"body": "Second page body"},
        ],
    )

    document = PdfDocument.open(pdf_path)
    try:
        assert document.total_pages == 2
        assert "First page body" in document.page_text(1)
        assert "Second page body" in document.page_text(2)
    finally:
        document.close()


def test_missing_pdf_raises_not_found(tmp_path):
    with pytest.raises(InputPdfNotFoundError):
        PdfDocument.open(tmp_path / "missing.pdf")


def test_damaged_pdf_raises_error(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(DamagedPdfError):
        PdfDocument.open(broken)


def test_encrypted_pdf_is_rejected(create_pdf):
    pdf_path = create_pdf("encrypted.pdf", pages=[{"body": "secret"}], encrypt=True)
    with pytest.raises(EncryptedPdfError):
        PdfDocument.open(pdf_path)


def test_pdf_without_text_layer_is_rejected(create_pdf):
    pdf_path = create_pdf(
        "image_only.pdf",
        pages=[{"shapes": [{"type": "rect", "rect": (50, 50, 250, 250)}]}],
    )
    with pytest.raises(UnsupportedInputError):
        PdfDocument.open(pdf_path)

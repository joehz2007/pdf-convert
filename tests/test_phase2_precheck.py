from __future__ import annotations

import pytest

from pdf_extract.errors import UnsupportedInputError
from pdf_extract.precheck import validate_supported_pdf


def test_precheck_accepts_text_pdf(create_pdf):
    pdf_path = create_pdf("supported.pdf", pages=[{"heading": "Heading", "body": "Some extractable text here with enough words to pass."}])

    result = validate_supported_pdf(pdf_path)

    assert result.page_count == 1
    assert result.total_chars > 0


def test_precheck_rejects_image_only_pdf(create_pdf):
    pdf_path = create_pdf(
        "image-only.pdf",
        pages=[{"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]}],
    )

    with pytest.raises(UnsupportedInputError):
        validate_supported_pdf(pdf_path)


def test_precheck_rejects_sparse_text_across_many_pages(create_pdf):
    pdf_path = create_pdf(
        "sparse-text.pdf",
        pages=[
            {"body": "one two three four five six"},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
            {"shapes": [{"type": "rect", "rect": (50, 50, 300, 300)}]},
        ],
    )

    with pytest.raises(UnsupportedInputError):
        validate_supported_pdf(pdf_path)

from __future__ import annotations

from pdf_extract.markdown_extractor import extract_markdown_chunks


def test_markdown_extractor_returns_page_chunks(create_pdf):
    pdf_path = create_pdf(
        "markdown-source.pdf",
        pages=[
            {"heading": "Chapter 1 Overview", "body": "This is page one."},
            {"body": "This is page two."},
        ],
    )

    chunks = extract_markdown_chunks(pdf_path)

    assert len(chunks) == 2
    assert "Chapter 1 Overview" in chunks[0]["text"]
    assert "This is page two." in chunks[1]["text"]

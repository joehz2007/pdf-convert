from __future__ import annotations

from pdf_slicer.document import PdfDocument
from pdf_slicer.recognizer import detect_sections, recognize_chapters


def test_recognize_chapters_from_toc(create_pdf):
    pdf_path = create_pdf(
        "toc.pdf",
        pages=[
            {"heading": "Chapter 1 Overview", "body": "content 1"},
            {"body": "content 2"},
            {"heading": "Chapter 2 Design", "body": "content 3"},
        ],
        toc=[[1, "Chapter 1 Overview", 1], [1, "Chapter 2 Design", 3]],
    )
    document = PdfDocument.open(pdf_path)
    try:
        result = recognize_chapters(document)
        assert result.fallback_level == 1
        assert [(chapter.title, chapter.start_page, chapter.end_page) for chapter in result.chapters] == [
            ("Chapter 1 Overview", 1, 2),
            ("Chapter 2 Design", 3, 3),
        ]
    finally:
        document.close()


def test_recognize_chapters_from_toc_preserves_front_matter(create_pdf):
    pdf_path = create_pdf(
        "toc-front-matter.pdf",
        pages=[
            {"body": "cover page"},
            {"heading": "Chapter 1 Overview", "body": "content 1"},
            {"body": "content 2"},
            {"heading": "Chapter 2 Design", "body": "content 3"},
        ],
        toc=[[1, "Chapter 1 Overview", 2], [1, "Chapter 2 Design", 4]],
    )
    document = PdfDocument.open(pdf_path)
    try:
        result = recognize_chapters(document)
        assert result.fallback_level == 1
        assert [(chapter.title, chapter.start_page, chapter.end_page) for chapter in result.chapters] == [
            ("前言", 1, 1),
            ("Chapter 1 Overview", 2, 3),
            ("Chapter 2 Design", 4, 4),
        ]
    finally:
        document.close()


def test_recognize_chapters_collapses_same_start_toc_entries(create_pdf):
    pdf_path = create_pdf(
        "toc-duplicate-start.pdf",
        pages=[
            {"body": "cover page"},
            {"heading": "Chapter 1 Overview", "body": "content 1"},
            {"body": "content 2"},
            {"heading": "Chapter 2 Design", "body": "content 3"},
        ],
        toc=[[1, "Document Title", 2], [1, "Chapter 1 Overview", 2], [1, "Chapter 2 Design", 4]],
    )
    document = PdfDocument.open(pdf_path)
    try:
        result = recognize_chapters(document)
        assert result.fallback_level == 1
        assert [(chapter.title, chapter.start_page, chapter.end_page) for chapter in result.chapters] == [
            ("前言", 1, 1),
            ("Document Title + Chapter 1 Overview", 2, 3),
            ("Chapter 2 Design", 4, 4),
        ]
    finally:
        document.close()


def test_detect_sections_prefers_toc_children(create_pdf):
    pdf_path = create_pdf(
        "section-toc.pdf",
        pages=[
            {"heading": "Chapter 8", "body": "body 1"},
            {"body": "body 2"},
            {"body": "body 3"},
            {"body": "body 4"},
            {"body": "body 5"},
        ],
        toc=[
            [1, "Chapter 8", 1],
            [2, "8.1 Overview", 1],
            [3, "8.1.1 Basic", 1],
            [2, "8.2 Auth", 3],
            [2, "8.3 Submit", 5],
        ],
    )
    document = PdfDocument.open(pdf_path)
    try:
        chapter = recognize_chapters(document).chapters[0]
        sections = detect_sections(document, chapter)
        assert [(section.title, section.start_page, section.end_page, section.level) for section in sections] == [
            ("8.1.1 Basic", 1, 2, 3),
            ("8.2 Auth", 3, 4, 2),
            ("8.3 Submit", 5, 5, 2),
        ]
    finally:
        document.close()


def test_recognize_chapters_from_layout_fallback(create_pdf):
    pdf_path = create_pdf(
        "fallback.pdf",
        pages=[
            {"heading": "Chapter 1 Overview", "body": "content 1"},
            {"body": "content 2"},
            {"heading": "Chapter 2 Design", "body": "content 3"},
        ],
    )
    document = PdfDocument.open(pdf_path)
    try:
        result = recognize_chapters(document)
        assert result.fallback_level == 2
        assert [(chapter.title, chapter.start_page, chapter.end_page) for chapter in result.chapters] == [
            ("Chapter 1 Overview", 1, 2),
            ("Chapter 2 Design", 3, 3),
        ]
    finally:
        document.close()


def test_recognize_chapters_from_layout_preserves_front_matter(create_pdf):
    pdf_path = create_pdf(
        "layout-front-matter.pdf",
        pages=[
            {"body": "cover page"},
            {"heading": "Chapter 1 Overview", "body": "content 1"},
            {"body": "content 2"},
            {"heading": "Chapter 2 Design", "body": "content 3"},
        ],
    )
    document = PdfDocument.open(pdf_path)
    try:
        result = recognize_chapters(document)
        assert result.fallback_level == 2
        assert [(chapter.title, chapter.start_page, chapter.end_page) for chapter in result.chapters] == [
            ("前言", 1, 1),
            ("Chapter 1 Overview", 2, 3),
            ("Chapter 2 Design", 4, 4),
        ]
    finally:
        document.close()


def test_recognizer_returns_full_document_when_no_heading_found(create_pdf):
    pdf_path = create_pdf(
        "plain.pdf",
        pages=[{"body": "plain body page one"}, {"body": "plain body page two"}],
    )
    document = PdfDocument.open(pdf_path)
    try:
        result = recognize_chapters(document)
        assert result.fallback_level == 2
        assert len(result.chapters) == 1
        assert result.chapters[0].start_page == 1
        assert result.chapters[0].end_page == 2
    finally:
        document.close()

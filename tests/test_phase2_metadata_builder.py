from __future__ import annotations

import pytest

from pdf_extract.contracts import SliceTask
from pdf_extract.errors import EmptyExtractionError, PageMappingError
from pdf_extract.markdown_extractor import extract_markdown_chunks
from pdf_extract.metadata_builder import build_content_result, build_dedupe_key


def test_metadata_builder_builds_blocks_and_stats(create_pdf, tmp_path):
    pdf_path = create_pdf(
        "metadata.pdf",
        pages=[
            {"heading": "Chapter 1 Overview", "body": "Paragraph one."},
            {"body": "- item one"},
        ],
    )
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Chapter 1 Overview",
        start_page=1,
        end_page=2,
        overlap_pages=[2],
    )

    chunks = extract_markdown_chunks(pdf_path)
    result = build_content_result(task, chunks)

    assert result.stats["char_count"] > 0
    assert result.stats["table_count"] == 0
    assert result.source_pages[0].blocks
    assert result.source_pages[0].blocks[0]["type"] == "heading"
    assert result.source_pages[0].blocks[0]["dedupe_key"].startswith("1:")
    assert result.source_pages[1].is_overlap is True


def test_metadata_builder_marks_manual_review_for_empty_chunk(create_pdf):
    pdf_path = create_pdf(
        "metadata-warning.pdf",
        pages=[
            {"body": "Page one body."},
            {"body": "Page two body."},
        ],
    )
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Warning Sample",
        start_page=1,
        end_page=2,
    )
    chunks = extract_markdown_chunks(pdf_path)
    chunks[1]["text"] = ""

    result = build_content_result(task, chunks)

    assert result.manual_review_required is True
    assert any(item.startswith("empty_markdown_page:2") for item in result.warnings)


def test_metadata_builder_rejects_page_mapping_mismatch(create_pdf):
    pdf_path = create_pdf(
        "metadata-mismatch.pdf",
        pages=[{"body": "Only one page."}],
    )
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Mismatch",
        start_page=1,
        end_page=1,
    )
    chunks = extract_markdown_chunks(pdf_path)
    chunks[0]["metadata"]["page"] = 2

    with pytest.raises(PageMappingError):
        build_content_result(task, chunks)


def test_metadata_builder_rejects_all_empty_markdown(create_pdf):
    pdf_path = create_pdf(
        "metadata-empty.pdf",
        pages=[{"body": "Only one page."}],
    )
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Empty",
        start_page=1,
        end_page=1,
    )
    chunks = extract_markdown_chunks(pdf_path)
    chunks[0]["text"] = ""

    with pytest.raises(EmptyExtractionError):
        build_content_result(task, chunks)


def test_dedupe_key_is_stable():
    left = build_dedupe_key(3, "A  B\nC", "box123")
    right = build_dedupe_key(3, "A B C", "box123")

    assert left == right

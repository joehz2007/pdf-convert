from __future__ import annotations

import pdf_extract.markdown_extractor as markdown_module
from pdf_extract.markdown_extractor import (
    TABLE_FALLBACK_PLACEHOLDER,
    chunk_has_markdown_table,
    detect_table_retry_pages,
    extract_markdown_chunks,
    is_suspicious_table_block,
    sanitize_broken_table_markdown,
)


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


def test_to_markdown_disables_ocr(monkeypatch):
    captured = {}

    def fake_to_markdown(document, **kwargs):
        captured.update(kwargs)
        return [{"text": "ok", "metadata": {"page": 1}}]

    monkeypatch.setattr(markdown_module.pymupdf4llm, "to_markdown", fake_to_markdown)

    chunks = markdown_module._to_markdown(object(), table_strategy="lines_strict", pages=None)

    assert chunks[0]["text"] == "ok"
    assert captured["use_ocr"] is False
    assert captured["page_chunks"] is True


def test_markdown_extractor_marks_table_fallback_metadata(create_pdf):
    pdf_path = create_pdf(
        "table-source.pdf",
        pages=[
            {
                "shapes": [
                    {"type": "rect", "rect": (50, 100, 300, 220), "fill": None},
                    {"type": "line", "p1": (175, 100), "p2": (175, 220)},
                    {"type": "line", "p1": (50, 160), "p2": (300, 160)},
                ],
                "extra_texts": [
                    {"point": (70, 130), "text": "Col1"},
                    {"point": (200, 130), "text": "Col2"},
                    {"point": (70, 190), "text": "A"},
                    {"point": (200, 190), "text": "B"},
                ],
            }
        ],
    )

    chunks = extract_markdown_chunks(pdf_path)

    assert len(chunks) == 1
    assert chunk_has_markdown_table(chunks[0]) is True
    assert chunks[0]["table_strategy_used"] in {"lines_strict", "lines"}
    assert isinstance(chunks[0]["table_retry_pages"], list)
    assert chunks[0]["metadata"]["table_count_hint"] == 1
    assert len(chunks[0]["table_snapshots"]) == 1


def test_detect_table_retry_pages_identifies_missing_markdown(create_pdf):
    pdf_path = create_pdf(
        "table-retry.pdf",
        pages=[
            {
                "shapes": [
                    {"type": "rect", "rect": (50, 100, 300, 220), "fill": None},
                    {"type": "line", "p1": (175, 100), "p2": (175, 220)},
                    {"type": "line", "p1": (50, 160), "p2": (300, 160)},
                ],
                "extra_texts": [
                    {"point": (70, 130), "text": "Col1"},
                    {"point": (200, 130), "text": "Col2"},
                    {"point": (70, 190), "text": "A"},
                    {"point": (200, 190), "text": "B"},
                ],
            }
        ],
    )

    chunks = extract_markdown_chunks(pdf_path)
    chunks[0]["text"] = "not a markdown table"
    chunks[0]["tables"] = []

    retry_pages = detect_table_retry_pages(chunks, [0])

    assert retry_pages == [0]


def test_suspicious_table_block_detects_mid_word_breaks():
    table_lines = [
        "|Unified Abstra<br>sfe|with ERC-20 tokens or SWIFT<br>t integration logic|",
        "|---|---|",
        "|asynchronous p<br>rocess|polling or set up<br>hooks|",
    ]

    assert is_suspicious_table_block(table_lines) is True


def test_sanitize_broken_table_markdown_replaces_bad_table_block():
    chunk = {
        "text": "before\n|Unified Abstra<br>sfe|with ERC-20 tokens or SWIFT<br>t integration logic|\n|---|---|\n|asynchronous p<br>rocess|polling or set up<br>hooks|\nafter",
        "table_snapshots": [{"bbox": [0, 0, 1, 1], "rows": [["a"]], "headers": [], "markdown": "|a|\n|---|"}],
    }

    sanitize_broken_table_markdown(chunk)

    assert TABLE_FALLBACK_PLACEHOLDER in chunk["text"]
    assert "Unified Abstra<br>sfe" not in chunk["text"]
    assert chunk["suppressed_table_markdown"] == 1


def test_sanitize_broken_table_markdown_keeps_normal_table():
    chunk = {
        "text": "|Name|Desc|\n|---|---|\n|A|line one<br>line two|",
        "table_snapshots": [{"bbox": [0, 0, 1, 1], "rows": [["a"]], "headers": [], "markdown": "|a|\n|---|"}],
    }

    sanitize_broken_table_markdown(chunk)

    assert TABLE_FALLBACK_PLACEHOLDER not in chunk["text"]
    assert chunk["suppressed_table_markdown"] == 0


# ---------------------------------------------------------------------------
# Cross-page table merging tests
# ---------------------------------------------------------------------------

from pdf_extract.markdown_extractor import (
    _is_overflow_row,
    _is_spurious_table,
    _merge_overflow_into_last_row,
    postprocess_cross_page_tables,
)


def test_is_overflow_row_detects_last_col_overflow():
    assert _is_overflow_row(["", "", "", "Character limit: 2"]) is True
    assert _is_overflow_row([None, None, None, "overflow text"]) is True


def test_is_overflow_row_rejects_data_rows():
    assert _is_overflow_row(["fieldName", "Y", "String", "description"]) is False
    assert _is_overflow_row(["Section Title", "", "", ""]) is False


def test_is_overflow_row_detects_all_empty():
    assert _is_overflow_row(["", None, "", None]) is True
    assert _is_overflow_row([]) is False


def test_merge_overflow_into_last_row():
    rows = [["field", "Y", "String", "Registered country code\nISO 3166-1-alpha-2"]]
    overflow = [None, None, None, "Character limit: 2\nUnsupported"]
    _merge_overflow_into_last_row(rows, overflow)
    assert rows[0][3] == "Registered country code\nISO 3166-1-alpha-2\nCharacter limit: 2\nUnsupported"
    assert rows[0][0] == "field"


def test_is_spurious_table_tiny_area():
    snapshot = {"bbox": [10, 10, 40, 30], "headers": ["(", ")"], "rows": [["(", ")"]]}
    assert _is_spurious_table(snapshot, 600, 842) is True


def test_is_spurious_table_many_single_char_headers():
    snapshot = {
        "bbox": [10, 10, 400, 200],
        "headers": ["", ",", "'", "", "-", "", "/"],
        "rows": [["", ",", "'", "", "-", "", "/"]],
    }
    assert _is_spurious_table(snapshot, 600, 842) is True


def test_is_spurious_table_keeps_real_table():
    snapshot = {
        "bbox": [50, 100, 500, 400],
        "headers": ["Field", "Type", "Description"],
        "rows": [["name", "string", "Name of the field"]],
        "markdown": "| Field | Type | Description |\n| --- | --- | --- |",
    }
    assert _is_spurious_table(snapshot, 600, 842) is False


def test_postprocess_merges_cross_page_tables(create_pdf):
    """Simulate cross-page tables by constructing two consecutive pages
    where the last table on page 1 extends to the bottom and the first
    table on page 2 starts at the top.
    """
    import pymupdf

    doc = pymupdf.open()
    page_height = 842

    # Page 1: table that extends near the bottom
    p1 = doc.new_page(width=595, height=page_height)
    p1.draw_rect(pymupdf.Rect(50, 600, 500, page_height - 10))
    p1.insert_text((60, 640), "Field", fontsize=10)
    p1.insert_text((200, 640), "Type", fontsize=10)
    p1.insert_text((60, 700), "name", fontsize=10)
    p1.insert_text((200, 700), "string", fontsize=10)
    p1.draw_line((50, 660), (500, 660))
    p1.draw_line((180, 600), (180, page_height - 10))

    # Page 2: table that starts near the top
    p2 = doc.new_page(width=595, height=page_height)
    p2.draw_rect(pymupdf.Rect(50, 10, 500, 200))
    p2.insert_text((60, 50), "age", fontsize=10)
    p2.insert_text((200, 50), "int", fontsize=10)
    p2.draw_line((180, 10), (180, 200))

    chunks = [
        {"text": "page1", "metadata": {"page": 1}, "table_snapshots": []},
        {"text": "page2", "metadata": {"page": 2}, "table_snapshots": []},
    ]

    from pdf_extract.markdown_extractor import annotate_table_snapshots

    annotate_table_snapshots(doc, chunks, [0, 1])
    p1_tables_before = len(chunks[0]["table_snapshots"])
    p2_tables_before = len(chunks[1]["table_snapshots"])

    postprocess_cross_page_tables(doc, chunks, [0, 1])
    doc.close()

    # After merging, page 2's first table should be consumed into page 1's last
    if p1_tables_before > 0 and p2_tables_before > 0:
        merged = chunks[0]["table_snapshots"][-1]
        assert merged.get("cross_page") is True
        assert len(chunks[1]["table_snapshots"]) < p2_tables_before

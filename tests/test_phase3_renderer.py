from __future__ import annotations

from md_format.contracts import NormalizedBlock, NormalizedDocument, NormalizedPage
from md_format.renderer import RenderStats, render


def _make_doc(pages=None):
    return NormalizedDocument(
        slice_file="test.pdf",
        display_title="Test",
        order_index=1,
        start_page=1,
        end_page=1,
        pages=pages or [],
    )


def _make_page(blocks, source_page=1):
    return NormalizedPage(
        source_page=source_page,
        slice_page=1,
        is_overlap=False,
        blocks=blocks,
    )


def _make_block(block_type, markdown, reading_order=1):
    return NormalizedBlock(
        block_type=block_type,
        source_page=1,
        reading_order=reading_order,
        node_ref=None,
        markdown=markdown,
        is_overlap=False,
    )


class TestRenderer:
    def test_single_paragraph(self):
        doc = _make_doc([_make_page([_make_block("paragraph", "Hello world")])])
        md, stats = render(doc)
        assert "Hello world" in md
        assert stats.block_count == 1
        assert stats.char_count > 0

    def test_blocks_separated_by_blank_lines(self):
        doc = _make_doc([_make_page([
            _make_block("paragraph", "First", reading_order=1),
            _make_block("paragraph", "Second", reading_order=2),
        ])])
        md, _ = render(doc)
        assert "First\n\nSecond" in md

    def test_table_counted(self):
        doc = _make_doc([_make_page([
            _make_block("table", "| A |\n|---|\n| 1 |"),
        ])])
        _, stats = render(doc)
        assert stats.table_count == 1
        assert stats.block_count == 1

    def test_image_counted(self):
        doc = _make_doc([_make_page([
            _make_block("image", "![alt](img.png)"),
        ])])
        _, stats = render(doc)
        assert stats.image_count == 1

    def test_empty_blocks_skipped(self):
        doc = _make_doc([_make_page([
            _make_block("paragraph", ""),
            _make_block("paragraph", "  "),
            _make_block("paragraph", "Visible"),
        ])])
        md, stats = render(doc)
        assert stats.block_count == 1
        assert "Visible" in md

    def test_empty_document(self):
        doc = _make_doc([])
        md, stats = render(doc)
        assert md == ""
        assert stats.block_count == 0
        assert stats.char_count == 0

    def test_multi_page_ordering(self):
        doc = _make_doc([
            _make_page([_make_block("paragraph", "Page 1")], source_page=1),
            _make_page([_make_block("paragraph", "Page 2")], source_page=2),
        ])
        md, stats = render(doc)
        assert md.index("Page 1") < md.index("Page 2")
        assert stats.block_count == 2

    def test_trailing_newline(self):
        doc = _make_doc([_make_page([_make_block("paragraph", "Text")])])
        md, _ = render(doc)
        assert md.endswith("\n")

    def test_render_stats_type(self):
        doc = _make_doc([_make_page([_make_block("paragraph", "Text")])])
        _, stats = render(doc)
        assert isinstance(stats, RenderStats)

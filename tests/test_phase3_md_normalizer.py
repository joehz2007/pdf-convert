from __future__ import annotations

from md_format.md_normalizer import normalize_markdown


class TestMdNormalizer:
    def test_basic_normalization(self):
        md = "# Title\n\nSome text.\n"
        result = normalize_markdown(md)
        assert "# Title" in result
        assert "Some text" in result

    def test_preserves_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        result = normalize_markdown(md)
        assert "A" in result
        assert "B" in result
        assert "|" in result

    def test_preserves_code_fence(self):
        md = "```python\nprint('hello')\n```\n"
        result = normalize_markdown(md)
        assert "```" in result
        assert "print" in result

    def test_preserves_image(self):
        md = "![alt](image.png)\n"
        result = normalize_markdown(md)
        assert "image.png" in result

    def test_empty_input_returns_empty(self):
        assert normalize_markdown("") == ""
        assert normalize_markdown("   ") == "   "

    def test_atx_headings_maintained(self):
        md = "## Section\n\nContent here.\n"
        result = normalize_markdown(md)
        assert "## Section" in result

    def test_list_preserved(self):
        md = "- item 1\n- item 2\n- item 3\n"
        result = normalize_markdown(md)
        assert "item 1" in result
        assert "item 2" in result
        assert "item 3" in result

    def test_html_block_preserved(self):
        md = "<div>\n<table><tr><td>X</td></tr></table>\n</div>\n\n"
        result = normalize_markdown(md)
        assert "<table>" in result

    def test_idempotent(self):
        md = "# Title\n\nParagraph text here.\n\n- item\n"
        first = normalize_markdown(md)
        second = normalize_markdown(first)
        assert first == second

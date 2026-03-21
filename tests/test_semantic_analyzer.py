from __future__ import annotations

from types import SimpleNamespace

from pdf_slicer.semantic_analyzer import SemanticAnalyzer


class FakeDocument:
    total_pages = 3

    def __init__(self, text_dicts, tables=None, images=None):
        self._text_dicts = text_dicts
        self._tables = tables or {}
        self._images = images or {}

    def get_text_dict(self, page_number):
        return self._text_dicts[page_number]

    def find_tables(self, page_number):
        return SimpleNamespace(tables=self._tables.get(page_number, []))

    def get_image_blocks(self, page_number):
        return self._images.get(page_number, [])


class FakeTable:
    def __init__(self, bbox):
        self.bbox = bbox


def _text_block(text, bbox, font="Helvetica"):
    return {
        "type": 0,
        "bbox": bbox,
        "lines": [{"spans": [{"text": text, "font": font}]}],
    }


def test_detects_paragraph_break():
    document = FakeDocument(
        {
            1: {"height": 1000, "blocks": [_text_block("段落未结束", (50, 820, 500, 960))]},
            2: {"height": 1000, "blocks": [_text_block("继续下一页", (50, 20, 500, 120))]},
        }
    )
    analyzer = SemanticAnalyzer(document)
    assert analyzer._has_paragraph_break(1, 2) is True
    assert analyzer.is_safe_split_boundary(1) is False


def test_detects_code_break():
    document = FakeDocument(
        {
            1: {"height": 1000, "blocks": [_text_block("print('a')", (50, 820, 500, 960), font="Courier New")]},
            2: {"height": 1000, "blocks": [_text_block("print('b')", (50, 20, 500, 120), font="Courier New")]},
        }
    )
    analyzer = SemanticAnalyzer(document)
    assert analyzer._has_code_break(1, 2) is True


def test_detects_table_break():
    document = FakeDocument(
        {
            1: {"height": 1000, "blocks": []},
            2: {"height": 1000, "blocks": []},
        },
        tables={
            1: [FakeTable((50, 700, 500, 980))],
            2: [FakeTable((50, 10, 500, 200))],
        },
    )
    analyzer = SemanticAnalyzer(document)
    assert analyzer._has_table_break(1, 2) is True


def test_detects_figure_caption_break():
    document = FakeDocument(
        {
            1: {"height": 1000, "blocks": []},
            2: {"height": 1000, "blocks": [_text_block("图 1 系统结构", (50, 20, 500, 100))]},
        },
        images={
            1: [{"bbox": (50, 500, 500, 900)}],
        },
    )
    analyzer = SemanticAnalyzer(document)
    assert analyzer._has_figure_caption_break(1, 2) is True

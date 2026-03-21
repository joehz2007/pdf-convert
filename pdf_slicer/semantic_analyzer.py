"""语义边界分析模块。

在候选切分点上检查段落、表格、代码块和图注等语义块是否会被切断。
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any


LOGGER = logging.getLogger(__name__)
CAPTION_PATTERN = re.compile(r"^\s*(图|表|figure|fig\.)", re.IGNORECASE)
HEADING_PATTERN = re.compile(
    r"^\s*(第[一二三四五六七八九十百零\d]+章|chapter\s+\d+|\d+\.\s+|\d+\.\d+)",
    re.IGNORECASE,
)
TERMINAL_PUNCTUATION = tuple("。！？.!?;；:：”」』）)]")


class SemanticAnalyzer:
    """语义完整性分析器。"""
    def __init__(self, document):
        self.document = document
        self._logged_breaks: set[tuple[str, int]] = set()

    def is_safe_split_boundary(self, page_number: int) -> bool:
        """判断指定页末是否适合作为切分边界。"""
        # 逐类短路检测边界风险，命中任一语义断裂就认为该页不能直接切开。
        if page_number >= self.document.total_pages:
            return True
        next_page = page_number + 1
        return not any(
            check(page_number, next_page)
            for check in (
                self._has_table_break,
                self._has_code_break,
                self._has_paragraph_break,
                self._has_figure_caption_break,
            )
        )

    def _has_table_break(self, page_a: int, page_b: int) -> bool:
        """检测跨页表格是否会在当前边界被切断。"""
        tables_a = self._table_bboxes(page_a)
        tables_b = self._table_bboxes(page_b)
        if not tables_a or not tables_b:
            return False

        height_a = float(self._page_dict(page_a).get("height", 1))
        height_b = float(self._page_dict(page_b).get("height", 1))
        table_hits_bottom = any(bbox[3] >= height_a * 0.75 for bbox in tables_a)
        table_hits_top = any(bbox[1] <= height_b * 0.25 for bbox in tables_b)
        result = table_hits_bottom and table_hits_top
        if result:
            self._log_break_once("table", page_a)
        return result

    def _has_code_break(self, page_a: int, page_b: int) -> bool:
        last_block = self._last_text_block(page_a)
        first_block = self._first_text_block(page_b)
        if not last_block or not first_block:
            return False
        if not (last_block["is_monospace"] and first_block["is_monospace"]):
            return False
        result = self._near_bottom(last_block, page_a) and self._near_top(first_block, page_b)
        if result:
            self._log_break_once("code", page_a)
        return result

    def _has_paragraph_break(self, page_a: int, page_b: int) -> bool:
        """检测普通段落是否在页末未闭合并延续到下一页。"""
        last_block = self._last_text_block(page_a)
        first_block = self._first_text_block(page_b)
        if not last_block or not first_block:
            return False
        if last_block["is_monospace"] or first_block["is_monospace"]:
            return False
        if self._looks_like_heading(first_block["text"]) or self._looks_like_caption(first_block["text"]):
            return False
        if not (self._near_bottom(last_block, page_a) and self._near_top(first_block, page_b)):
            return False
        result = not last_block["text"].rstrip().endswith(TERMINAL_PUNCTUATION)
        if result:
            self._log_break_once("paragraph", page_a)
        return result

    def _has_figure_caption_break(self, page_a: int, page_b: int) -> bool:
        """检测页底图片与下一页图注的跨页组合。"""
        image_blocks = self._image_blocks(page_a)
        first_text = self._first_text_block(page_b)
        if not image_blocks or not first_text:
            return False
        page_height = float(self._page_dict(page_a).get("height", 1))
        image_near_bottom = any(block.get("bbox", (0, 0, 0, 0))[3] >= page_height * 0.7 for block in image_blocks)
        result = image_near_bottom and self._looks_like_caption(first_text["text"]) and self._near_top(first_text, page_b)
        if result:
            self._log_break_once("figure_caption", page_a)
        return result

    def _log_break_once(self, break_type: str, page_number: int) -> None:
        key = (break_type, page_number)
        if key in self._logged_breaks:
            return
        self._logged_breaks.add(key)
        LOGGER.warning("Semantic break detected at page %d: %s", page_number, break_type)

    @lru_cache(maxsize=256)
    def _page_dict(self, page_number: int) -> dict[str, Any]:
        # 同一页会被多个探测器重复读取，这里做页级缓存避免反复触发 PyMuPDF 解析。
        return self.document.get_text_dict(page_number)

    @lru_cache(maxsize=256)
    def _image_blocks(self, page_number: int) -> tuple[dict[str, Any], ...]:
        return tuple(self.document.get_image_blocks(page_number))

    @lru_cache(maxsize=256)
    def _table_bboxes(self, page_number: int) -> tuple[tuple[float, float, float, float], ...]:
        table_finder = self.document.find_tables(page_number)
        tables = getattr(table_finder, "tables", [])
        return tuple(tuple(table.bbox) for table in tables if getattr(table, "bbox", None))

    @lru_cache(maxsize=256)
    def _extract_text_blocks(self, page_number: int) -> tuple[dict[str, Any], ...]:
        # 统一抽取文本块的最小结构，后续段落/代码/图注判断都复用这份结果。
        page_dict = self._page_dict(page_number)
        extracted = []
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            texts = []
            fonts = []
            for line in block.get("lines", []):
                line_text = "".join(span.get("text", "") for span in line.get("spans", []))
                if line_text.strip():
                    texts.append(line_text.strip())
                for span in line.get("spans", []):
                    fonts.append(str(span.get("font", "")))
            text = " ".join(texts).strip()
            if not text:
                continue
            extracted.append(
                {
                    "text": text,
                    "bbox": tuple(block.get("bbox", (0, 0, 0, 0))),
                    "is_monospace": any(self._is_monospace_font(font) for font in fonts),
                }
            )
        return tuple(extracted)

    def _first_text_block(self, page_number: int) -> dict[str, Any] | None:
        blocks = self._extract_text_blocks(page_number)
        return min(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0])) if blocks else None

    def _last_text_block(self, page_number: int) -> dict[str, Any] | None:
        blocks = self._extract_text_blocks(page_number)
        return max(blocks, key=lambda item: (item["bbox"][3], item["bbox"][0])) if blocks else None

    @staticmethod
    def _is_monospace_font(font_name: str) -> bool:
        lowered = font_name.lower()
        return any(token in lowered for token in ("cour", "mono", "consola", "code"))

    def _near_bottom(self, block: dict[str, Any], page_number: int) -> bool:
        page_height = float(self._page_dict(page_number).get("height", 1))
        return block["bbox"][3] >= page_height * 0.75

    def _near_top(self, block: dict[str, Any], page_number: int) -> bool:
        page_height = float(self._page_dict(page_number).get("height", 1))
        return block["bbox"][1] <= page_height * 0.25

    @staticmethod
    def _looks_like_caption(text: str) -> bool:
        return bool(CAPTION_PATTERN.search(text))

    @staticmethod
    def _looks_like_heading(text: str) -> bool:
        return bool(HEADING_PATTERN.search(text))

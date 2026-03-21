"""章节与小节识别模块。

优先使用 PDF 自带 TOC 结构重建章节树，缺失时再回退到版面启发式识别。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .document import PdfDocument
from .models import ChapterNode, RecognitionResult

TOP_LEVEL_PATTERNS = (
    re.compile(r"^\s*第[一二三四五六七八九十百零\d]+章\b"),
    re.compile(r"^\s*chapter\s+\d+\b", re.IGNORECASE),
    re.compile(r"^\s*\d+\.\s+\S+"),
)

SECTION_PATTERNS = (
    re.compile(r"^\s*\d+\.\d+(?:\.\d+)*\s+\S+"),
    re.compile(r"^\s*section\s+\d+(?:\.\d+)*\b", re.IGNORECASE),
)


def recognize_chapters(document: PdfDocument) -> RecognitionResult:
    """识别顶层章节。

    优先读取一级 TOC；若文档缺少可用 TOC，则回退到版面启发式。
    """
    chapters = _recognize_from_toc(document)
    if chapters:
        return RecognitionResult(chapters=chapters, fallback_level=1)

    chapters = _recognize_from_layout(document)
    return RecognitionResult(chapters=chapters, fallback_level=2)


def detect_sections(document: PdfDocument, chapter: ChapterNode) -> list[ChapterNode]:
    """识别章节内部的小节边界。

    优先使用当前章节范围内的 TOC 子节点；若不可用，再回退到页内标题识别。
    """
    # 章节内部优先复用 PDF 自带 TOC 子节点，只有缺失时才回退到版面启发式识别。
    toc_sections = _detect_sections_from_toc(document, chapter)
    if toc_sections:
        return toc_sections

    candidates = _collect_heading_candidates(document, SECTION_PATTERNS, chapter.start_page, chapter.end_page)
    if not candidates:
        return []

    sections = _build_nodes_from_candidates(candidates, chapter.end_page, level=chapter.level + 1)
    if sections and sections[0].start_page > chapter.start_page:
        sections.insert(
            0,
            ChapterNode(
                title=chapter.title,
                start_page=chapter.start_page,
                end_page=sections[0].start_page - 1,
                level=chapter.level + 1,
            ),
        )
    sections[-1].end_page = chapter.end_page
    return sections


def _recognize_from_toc(document: PdfDocument) -> list[ChapterNode]:
    """根据一级 TOC 生成章节范围。"""
    toc = document.get_toc(simple=True)
    top_level_entries = []
    for entry in toc:
        if len(entry) < 3:
            continue
        level, title, page = entry[0], str(entry[1]).strip(), int(entry[2])
        if level == 1 and title and page > 0:
            top_level_entries.append((title, page))
    top_level_entries = _collapse_same_start_entries(top_level_entries)

    if not top_level_entries:
        return []

    chapters: list[ChapterNode] = []
    total_pages = document.total_pages
    for index, (title, start_page) in enumerate(top_level_entries):
        if index + 1 < len(top_level_entries):
            next_start = top_level_entries[index + 1][1]
            end_page = max(start_page, next_start - 1)
        else:
            end_page = total_pages
        chapters.append(ChapterNode(title=title, start_page=start_page, end_page=end_page, level=1))
    return _prepend_front_matter(chapters)


def _recognize_from_layout(document: PdfDocument) -> list[ChapterNode]:
    """在无 TOC 时，通过版面特征猜测顶层章节。"""
    candidates = _collect_heading_candidates(document, TOP_LEVEL_PATTERNS, 1, document.total_pages)
    if not candidates:
        return [
            ChapterNode(
                title=Path(document.path).stem,
                start_page=1,
                end_page=document.total_pages,
                level=1,
            )
        ]
    return _prepend_front_matter(_build_nodes_from_candidates(candidates, document.total_pages, level=1))


def _detect_sections_from_toc(document: PdfDocument, chapter: ChapterNode) -> list[ChapterNode]:
    """提取指定章节范围内的 TOC 子节点，并换算成 section 区间。"""
    if not hasattr(document, "get_toc"):
        return []

    entries: list[tuple[int, int, str]] = []
    for entry in document.get_toc(simple=True):
        if len(entry) < 3:
            continue
        level, raw_title, raw_page = entry[0], str(entry[1]).strip(), int(entry[2])
        if level <= chapter.level or not raw_title or raw_page <= 0:
            continue
        if raw_page < chapter.start_page or raw_page > chapter.end_page:
            continue
        entries.append((raw_page, level, raw_title))

    if not entries:
        return []

    collapsed: list[tuple[int, int, str]] = []
    # 同页出现多个 TOC 子节点时，保留最后一个更具体的标题，避免生成零跨度 section。
    for page, level, title in entries:
        if collapsed and collapsed[-1][0] == page:
            collapsed[-1] = (page, level, title)
        else:
            collapsed.append((page, level, title))

    sections: list[ChapterNode] = []
    for index, (start_page, level, title) in enumerate(collapsed):
        next_start = collapsed[index + 1][0] if index + 1 < len(collapsed) else chapter.end_page + 1
        end_page = chapter.end_page if index + 1 == len(collapsed) else max(start_page, next_start - 1)
        sections.append(ChapterNode(title=title, start_page=start_page, end_page=end_page, level=level))

    if sections and sections[0].start_page > chapter.start_page:
        sections.insert(
            0,
            ChapterNode(
                title=chapter.title,
                start_page=chapter.start_page,
                end_page=sections[0].start_page - 1,
                level=chapter.level + 1,
            ),
        )
    return sections


def _prepend_front_matter(chapters: list[ChapterNode]) -> list[ChapterNode]:
    if chapters and chapters[0].start_page > 1:
        chapters.insert(
            0,
            ChapterNode(
                title="前言",
                start_page=1,
                end_page=chapters[0].start_page - 1,
                level=1,
            ),
        )
    return chapters


def _collapse_same_start_entries(entries: list[tuple[str, int]]) -> list[tuple[str, int]]:
    # 一级 TOC 常见“文档标题 + 第一章”同页并列，这里合并成一个用户可读标题。
    collapsed: list[tuple[str, int]] = []
    for title, start_page in entries:
        if collapsed and collapsed[-1][1] == start_page:
            previous_title, _ = collapsed[-1]
            combined = previous_title if title in previous_title else f"{previous_title} + {title}"
            collapsed[-1] = (combined, start_page)
        else:
            collapsed.append((title, start_page))
    return collapsed


def _collect_heading_candidates(
    document: PdfDocument,
    patterns: tuple[re.Pattern[str], ...],
    start_page: int,
    end_page: int,
) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    # 每页只取一个候选标题，避免目录页或复杂排版在同页打出多个顶层节点。
    seen_pages: set[int] = set()
    for page_number in range(start_page, end_page + 1):
        page_dict = document.get_text_dict(page_number)
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            block_info = _text_block_to_candidate(block, page_dict, patterns)
            if not block_info:
                continue
            if page_number in seen_pages:
                break
            candidates.append((block_info, page_number))
            seen_pages.add(page_number)
            break
    return candidates


def _build_nodes_from_candidates(
    candidates: list[tuple[str, int]],
    total_pages: int,
    level: int,
) -> list[ChapterNode]:
    nodes: list[ChapterNode] = []
    for index, (title, start_page) in enumerate(candidates):
        next_start = candidates[index + 1][1] if index + 1 < len(candidates) else total_pages + 1
        end_page = total_pages if index + 1 == len(candidates) else max(start_page, next_start - 1)
        nodes.append(ChapterNode(title=title, start_page=start_page, end_page=end_page, level=level))
    return nodes


def _text_block_to_candidate(
    block: dict[str, Any],
    page_dict: dict[str, Any],
    patterns: tuple[re.Pattern[str], ...],
) -> str | None:
    lines = []
    sizes = []
    fonts = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        line_text = "".join(span.get("text", "") for span in spans).strip()
        if line_text:
            lines.append(line_text)
        for span in spans:
            sizes.append(float(span.get("size", 0)))
            fonts.append(str(span.get("font", "")))

    text = " ".join(lines).strip()
    if not text:
        return None

    if any(pattern.search(text) for pattern in patterns):
        return text

    # 没命中显式编号时，再用“页首 + 短文本 + 大字号/加粗”作为弱启发式。
    bbox = block.get("bbox", (0, 0, 0, 0))
    page_height = float(page_dict.get("height", 0) or 1)
    max_size = max(sizes) if sizes else 0
    is_bold = any("bold" in font.lower() for font in fonts)
    near_top = float(bbox[1]) < page_height * 0.3
    is_short = len(text) <= 80
    if near_top and is_short and (max_size >= 16 or (max_size >= 14 and is_bold)):
        return text
    return None

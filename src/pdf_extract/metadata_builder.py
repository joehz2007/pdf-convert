from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path

import pymupdf

from .contracts import ContentResult, PageContent, SliceTask
from .errors import EmptyExtractionError, PageMappingError


def build_content_result(task: SliceTask, page_chunks: list[dict]) -> ContentResult:
    if len(page_chunks) != task.actual_pages:
        raise PageMappingError(
            f"Slice '{task.slice_file}' expected {task.actual_pages} page chunks but got {len(page_chunks)}."
        )

    document = pymupdf.open(str(task.source_path))
    try:
        source_pages: list[PageContent] = []
        warnings: list[str] = []
        char_count = 0
        table_count = 0
        image_count = 0

        for expected_slice_page, chunk in enumerate(page_chunks, start=1):
            metadata = chunk.get("metadata", {})
            chunk_page = int(metadata.get("page", expected_slice_page))
            if chunk_page != expected_slice_page:
                raise PageMappingError(
                    f"Slice '{task.slice_file}' returned page chunk {chunk_page}, expected {expected_slice_page}."
                )

            source_page = task.start_page + expected_slice_page - 1
            markdown = str(chunk.get("text", "")).strip()
            if not markdown:
                warnings.append(f"empty_markdown_page:{source_page}")

            page = document[expected_slice_page - 1]
            blocks = extract_text_blocks(
                page,
                source_page=source_page,
                display_title=task.display_title,
                is_overlap=source_page in task.overlap_pages,
                first_page=(expected_slice_page == 1),
            )
            if markdown and not blocks:
                warnings.append(f"no_blocks_page:{source_page}")

            tables: list[dict] = []
            images: list[dict] = []
            char_count += len(markdown)
            table_count += len(tables)
            image_count += len(images)
            source_pages.append(
                PageContent(
                    slice_page=expected_slice_page,
                    source_page=source_page,
                    is_overlap=source_page in task.overlap_pages,
                    markdown=markdown,
                    blocks=blocks,
                    tables=tables,
                    images=images,
                )
            )
    finally:
        document.close()

    if char_count == 0:
        raise EmptyExtractionError(f"Slice '{task.slice_file}' produced empty Markdown content.")

    return ContentResult(
        slice_file=task.slice_file,
        display_title=task.display_title,
        start_page=task.start_page,
        end_page=task.end_page,
        source_pages=source_pages,
        assets=[],
        stats={
            "char_count": char_count,
            "table_count": table_count,
            "image_count": image_count,
        },
        warnings=warnings,
        manual_review_required=task.manual_review_required or bool(warnings),
    )


def extract_text_blocks(
    page: pymupdf.Page,
    *,
    source_page: int,
    display_title: str,
    is_overlap: bool,
    first_page: bool,
) -> list[dict]:
    page_dict = page.get_text("dict", sort=True)
    text_blocks = [block for block in page_dict.get("blocks", []) if block.get("type") == 0]
    max_font_size = max((_max_font_size(block) for block in text_blocks), default=0.0)
    page_height = float(page.rect.height)

    results: list[dict] = []
    for reading_order, block in enumerate(text_blocks, start=1):
        text = extract_block_text(block)
        if not text:
            continue
        bbox = round_bbox(block.get("bbox", (0, 0, 0, 0)))
        block_type = classify_block(
            text,
            block,
            display_title=display_title,
            first_page=first_page,
            max_font_size=max_font_size,
            page_height=page_height,
            reading_order=reading_order,
        )
        bbox_hash = build_bbox_hash(bbox)
        results.append(
            {
                "type": block_type,
                "text": text,
                "source_page": source_page,
                "bbox": bbox,
                "reading_order": reading_order,
                "is_overlap": is_overlap,
                "dedupe_key": build_dedupe_key(source_page, text, bbox_hash),
            }
        )
    return results


def extract_block_text(block: dict) -> str:
    lines: list[str] = []
    for line in block.get("lines", []):
        spans = [str(span.get("text", "")) for span in line.get("spans", []) if span.get("text")]
        line_text = "".join(spans).strip()
        if line_text:
            lines.append(line_text)
    return "\n".join(lines).strip()


def classify_block(
    text: str,
    block: dict,
    *,
    display_title: str,
    first_page: bool,
    max_font_size: float,
    page_height: float,
    reading_order: int,
) -> str:
    normalized_text = normalize_text(text)
    normalized_title = normalize_text(display_title)
    font_names = {str(span.get("font", "")).lower() for line in block.get("lines", []) for span in line.get("spans", [])}
    font_size = _max_font_size(block)
    bbox = block.get("bbox", (0, 0, 0, 0))
    top = float(bbox[1]) if len(bbox) >= 2 else 0.0
    bottom = float(bbox[3]) if len(bbox) >= 4 else 0.0

    if first_page and normalized_text == normalized_title:
        return "heading"
    if first_page and reading_order == 1 and max_font_size > 0 and font_size >= max_font_size * 0.95 and len(text) <= 120:
        return "heading"
    if is_code_block(text, font_names):
        return "code"
    if is_list_item(text):
        return "list_item"
    if text.lstrip().startswith(">"):
        return "quote"
    if top <= page_height * 0.08 and len(text) <= 80:
        return "header"
    if bottom >= page_height * 0.92 and len(text) <= 80:
        return "footer"
    return "paragraph"


def is_code_block(text: str, font_names: set[str]) -> bool:
    lowered = text.lower()
    if any(name for name in font_names if any(token in name for token in ("courier", "mono", "consolas", "code"))):
        return True
    if "\n" in text and any(line.startswith(("    ", "\t")) for line in text.splitlines()):
        return True
    return lowered.startswith(("def ", "class ", "for ", "if ", "while ", "return "))


def is_list_item(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith(("- ", "* ", "• ")) or (
        len(stripped) > 3 and stripped[0].isdigit() and stripped[1:3] in {". ", ") "}
    )


def round_bbox(bbox: tuple | list) -> list[float]:
    return [round(float(value), 3) for value in bbox]


def build_bbox_hash(bbox: list[float]) -> str:
    payload = json.dumps(bbox, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.split()).strip()


def build_dedupe_key(source_page: int, text: str, bbox_hash: str = "") -> str:
    normalized = normalize_text(text)
    text_hash = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{source_page}:{text_hash}:{bbox_hash}"


def _max_font_size(block: dict) -> float:
    sizes = [float(span.get("size", 0.0)) for line in block.get("lines", []) for span in line.get("spans", [])]
    return max(sizes, default=0.0)

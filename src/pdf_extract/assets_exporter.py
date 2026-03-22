from __future__ import annotations

from pathlib import Path

import pymupdf

from .contracts import ImageNode


def export_page_images(
    document: pymupdf.Document,
    page: pymupdf.Page,
    assets_dir: Path,
    *,
    source_page: int,
    warnings: list[str] | None = None,
) -> list[ImageNode]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    images: list[ImageNode] = []
    page_images = page.get_images(full=True)
    for index, image in enumerate(page_images, start=1):
        try:
            xref = int(image[0])
            rects = page.get_image_rects(xref)
            info = document.extract_image(xref)
            ext = str(info.get("ext") or "png").lower()
            asset_name = f"p{source_page:04d}_img{index:02d}.{ext}"
            asset_path = assets_dir / asset_name
            asset_path.write_bytes(info["image"])
            bbox = list(rects[0]) if rects else [0.0, 0.0, 0.0, 0.0]
            images.append(
                ImageNode(
                    type="image",
                    source_page=source_page,
                    bbox=[round(float(value), 3) for value in bbox],
                    asset_path=f"assets/{asset_name}",
                    width=int(info.get("width", 0)),
                    height=int(info.get("height", 0)),
                    caption=None,
                )
            )
        except Exception as exc:
            if warnings is not None:
                warnings.append(f"image_export_failed:{source_page}:{index}:{exc.__class__.__name__}")
            continue
    return images


def export_table_clip(page: pymupdf.Page, bbox: list[float], assets_dir: Path, *, source_page: int, table_index: int) -> str:
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"p{source_page:04d}_table{table_index:02d}.png"
    asset_path = assets_dir / asset_name
    rect = pymupdf.Rect(bbox)
    pixmap = page.get_pixmap(clip=rect, dpi=150)
    pixmap.save(asset_path)
    return f"assets/{asset_name}"

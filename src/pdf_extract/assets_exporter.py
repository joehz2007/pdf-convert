from __future__ import annotations

from pathlib import Path

import pymupdf

from .contracts import ImageNode

SAFE_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}


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
            bbox = list(rects[0]) if rects else [0.0, 0.0, 0.0, 0.0]
            asset_name, asset_bytes = resolve_image_payload(document, page, xref, info, rects, source_page=source_page, index=index, ext=ext)
            asset_path = assets_dir / asset_name
            asset_path.write_bytes(asset_bytes)
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


def resolve_image_payload(
    document: pymupdf.Document,
    page: pymupdf.Page,
    xref: int,
    info: dict,
    rects: list,
    *,
    source_page: int,
    index: int,
    ext: str,
) -> tuple[str, bytes]:
    raw_bytes = info.get("image")
    if ext in SAFE_IMAGE_EXTENSIONS and isinstance(raw_bytes, (bytes, bytearray)) and raw_bytes:
        return f"p{source_page:04d}_img{index:02d}.{ext}", bytes(raw_bytes)

    png_name = f"p{source_page:04d}_img{index:02d}.png"
    if rects:
        pixmap = page.get_pixmap(clip=rects[0], dpi=150)
        return png_name, pixmap.tobytes("png")

    pixmap = pymupdf.Pixmap(document, xref)
    return png_name, pixmap.tobytes("png")


def export_table_clip(page: pymupdf.Page, bbox: list[float], assets_dir: Path, *, source_page: int, table_index: int) -> str:
    assets_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"p{source_page:04d}_table{table_index:02d}.png"
    asset_path = assets_dir / asset_name
    rect = pymupdf.Rect(bbox)
    pixmap = page.get_pixmap(clip=rect, dpi=150)
    pixmap.save(asset_path)
    return f"assets/{asset_name}"

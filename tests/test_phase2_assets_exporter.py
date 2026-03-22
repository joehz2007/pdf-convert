from __future__ import annotations

import base64

import pymupdf

from pdf_extract.assets_exporter import export_page_images, export_table_clip

PNG_BYTES = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2mQAAAAASUVORK5CYII=")


def test_assets_exporter_writes_page_images(create_pdf, tmp_path):
    pdf_path = create_pdf(
        "assets-source.pdf",
        pages=[
            {
                "images": [{"rect": (100, 100, 180, 180), "stream": PNG_BYTES}],
            }
        ],
    )

    document = pymupdf.open(str(pdf_path))
    try:
        exported = export_page_images(document, document[0], tmp_path / "assets", source_page=3)
    finally:
        document.close()

    assert len(exported) == 1
    assert exported[0].asset_path == "assets/p0003_img01.png"
    assert (tmp_path / exported[0].asset_path).exists()


def test_assets_exporter_continues_when_one_image_fails(tmp_path):
    class FakePage:
        def get_images(self, full=True):
            return [(1,), (2,)]

        def get_image_rects(self, xref):
            return [(10, 10, 20, 20)]

    class FakeDocument:
        def extract_image(self, xref):
            if xref == 2:
                raise RuntimeError("broken image")
            return {"image": PNG_BYTES, "ext": "png", "width": 1, "height": 1}

    warnings: list[str] = []
    exported = export_page_images(FakeDocument(), FakePage(), tmp_path / "assets", source_page=4, warnings=warnings)

    assert len(exported) == 1
    assert exported[0].asset_path == "assets/p0004_img01.png"
    assert any(item.startswith("image_export_failed:4:2") for item in warnings)


def test_assets_exporter_writes_table_clip(create_pdf, tmp_path):
    pdf_path = create_pdf(
        "table-clip.pdf",
        pages=[
            {
                "shapes": [{"type": "rect", "rect": (50, 100, 200, 180), "fill": None}],
            }
        ],
    )

    document = pymupdf.open(str(pdf_path))
    try:
        asset_path = export_table_clip(document[0], [50.0, 100.0, 200.0, 180.0], tmp_path / "assets", source_page=5, table_index=2)
    finally:
        document.close()

    assert asset_path == "assets/p0005_table02.png"
    assert (tmp_path / asset_path).exists()

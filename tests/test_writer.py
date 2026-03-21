from __future__ import annotations

import json

from pdf_slicer.document import PdfDocument
from pdf_slicer.models import SlicePlan
from pdf_slicer.writer import PdfSliceWriter


def test_writer_outputs_default_directory_and_manifest(create_pdf):
    pdf_path = create_pdf(
        "writer.pdf",
        pages=[
            {"heading": "第一章 概述", "body": "第一页"},
            {"body": "第二页"},
            {"heading": "第二章 设计", "body": "第三页"},
        ],
    )
    document = PdfDocument.open(pdf_path)
    try:
        writer = PdfSliceWriter(document)
        output_dir = writer.write(
            slices=[
                SlicePlan(title="第一章 概述", start_page=1, end_page=2, split_mode="chapter"),
                SlicePlan(title="第二章 设计", start_page=3, end_page=3, split_mode="chapter"),
            ],
            fallback_level=1,
        )
        manifest_path = output_dir / "manifest.json"
        assert output_dir.name == "writer_split"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["source_file"] == "writer.pdf"
        assert manifest["fallback_level"] == 1
        assert manifest["slices"][0]["start_page"] == 1
        assert manifest["slices"][0]["slice_file"].endswith(".pdf")
        assert (output_dir / manifest["slices"][0]["slice_file"]).exists()
    finally:
        document.close()

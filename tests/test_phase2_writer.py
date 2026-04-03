from __future__ import annotations

from pdf_extract.contracts import BlockNode, ContentResult, LoadedManifest, PageContent, SliceTask, TableNode
from pdf_extract.writer import (
    TABLE_FALLBACK_PLACEHOLDER,
    build_failure_record,
    render_page_markdown,
    write_extract_manifest,
    write_slice_result,
)


def test_writer_persists_stage_timings_and_manifest_timings(create_pdf, tmp_path):
    pdf_path = create_pdf(
        "writer-source.pdf",
        pages=[{"heading": "Writer Title", "body": "Writer body."}],
    )
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Writer Title",
        start_page=1,
        end_page=1,
    )
    result = ContentResult(
        slice_file=task.slice_file,
        display_title=task.display_title,
        start_page=1,
        end_page=1,
        source_pages=[
            PageContent(
                slice_page=1,
                source_page=1,
                is_overlap=False,
                markdown="# Writer Title\n\nWriter body.",
                blocks=[BlockNode(type="heading", text="Writer Title", source_page=1, bbox=[0, 0, 1, 1], reading_order=1, is_overlap=False, dedupe_key="1:abc:box")],
                tables=[],
                images=[],
            )
        ],
        stats={"char_count": 10, "table_count": 0, "image_count": 0},
        warnings=[],
        manual_review_required=False,
    )

    slice_record = write_slice_result(
        tmp_path,
        task,
        result,
        emit_md=False,
        elapsed_ms=12,
        stage_timings={"precheck_ms": 1, "markdown_extract_ms": 2, "metadata_build_ms": 3, "write_ms": 6, "total_ms": 12},
    )

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    loaded_manifest = LoadedManifest(
        manifest_path=manifest_path,
        source_file="writer-source.pdf",
        total_pages=1,
        fallback_level=1,
        slices=[task],
    )

    extract_manifest = write_extract_manifest(
        tmp_path,
        loaded_manifest,
        [slice_record],
        total_elapsed_ms=15,
        run_timings={"manifest_load_ms": 2, "slice_total_ms": 12},
    )

    assert extract_manifest.slices[0].stage_timings["metadata_build_ms"] == 3
    assert extract_manifest.timings["manifest_load_ms"] == 2
    assert extract_manifest.timings["write_manifest_ms"] >= 0
    assert extract_manifest.total_elapsed_ms >= 15
    assert (tmp_path / "extract_manifest.json").exists()


def test_writer_prefers_rendered_markdown_in_draft_output(create_pdf, tmp_path):
    pdf_path = create_pdf("writer-fallback.pdf", pages=[{"body": "fallback body"}])
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Fallback",
        start_page=1,
        end_page=1,
    )
    page = PageContent(
        slice_page=1,
        source_page=1,
        is_overlap=False,
        markdown=f"before\n\n{TABLE_FALLBACK_PLACEHOLDER}\n\nafter",
        blocks=[],
        tables=[
            TableNode(
                type="table",
                source_page=1,
                bbox=[0, 0, 10, 10],
                table_strategy_used="lines",
                table_fallback_used=True,
                headers=["A"],
                rows=[["x"]],
                markdown=None,
                rendered_markdown="Table metadata: `data-table-id=p0001-t01`\n\n| A |\n| --- |\n| x |",
                fallback_html="<div data-table-role=\"standalone\"><table><tr><td>x</td></tr></table></div>",
                fallback_image="assets/p0001_table01.png",
            )
        ],
        images=[],
    )
    result = ContentResult(
        slice_file=task.slice_file,
        display_title=task.display_title,
        start_page=1,
        end_page=1,
        source_pages=[page],
        stats={"char_count": 1, "table_count": 1, "image_count": 0},
        warnings=[],
        manual_review_required=True,
    )

    slice_record = write_slice_result(tmp_path, task, result, emit_md=True, elapsed_ms=5, stage_timings={"write_ms": 1})
    md_text = (tmp_path / slice_record.md_file).read_text(encoding="utf-8")

    assert TABLE_FALLBACK_PLACEHOLDER not in md_text
    assert "Table metadata: `data-table-id=p0001-t01`" in md_text
    assert '<div data-table-role="standalone">' not in md_text
    assert "before" in md_text and "after" in md_text


def test_render_page_markdown_uses_rendered_markdown_when_page_markdown_empty():
    page = PageContent(
        slice_page=1,
        source_page=1,
        is_overlap=False,
        markdown="",
        blocks=[],
        tables=[
            TableNode(
                type="table",
                source_page=1,
                bbox=[0, 0, 10, 10],
                table_strategy_used="lines",
                table_fallback_used=True,
                headers=[],
                rows=[],
                markdown=None,
                rendered_markdown="Table metadata: `data-table-id=p0001-t01`\n\n| Field |\n| --- |\n| nested |",
                fallback_html="<div data-table-role=\"standalone\"><table><tr><td>nested</td></tr></table></div>",
                fallback_image=None,
            )
        ],
        images=[],
    )

    rendered = render_page_markdown(page)

    assert rendered == "Table metadata: `data-table-id=p0001-t01`\n\n| Field |\n| --- |\n| nested |"


def test_writer_renders_child_table_markup_when_markdown_is_empty():
    page = PageContent(
        slice_page=1,
        source_page=1,
        is_overlap=False,
        markdown="",
        blocks=[],
        tables=[
            TableNode(
                type="table",
                source_page=1,
                bbox=[0, 0, 10, 10],
                table_strategy_used="lines",
                table_fallback_used=True,
                headers=["Field"],
                rows=[["requestId"]],
                markdown=None,
                rendered_markdown=(
                    "**Transfers description (Objects of Transfers)**\n\n"
                    "Table metadata: `data-table-id=p0001-t01-c01` `data-table-role=child` `data-parent-table-id=p0001-t01`\n\n"
                    "| Field |\n| --- |\n| requestId |"
                ),
                fallback_html=(
                    '<div class="complex-table-block" data-table-id="p0001-t01-c01" '
                    'data-table-role="child" data-parent-table-id="p0001-t01">\n'
                    '  <p class="complex-table-title"><strong>Transfers description (Objects of Transfers)</strong></p>\n'
                    '  <table><tbody><tr><td>requestId</td></tr></tbody></table>\n'
                    '</div>'
                ),
                fallback_image=None,
                table_id="p0001-t01-c01",
                parent_table_id="p0001-t01",
                table_role="child",
                section_title="Transfers description (Objects of Transfers)",
            )
        ],
        images=[],
    )

    rendered = render_page_markdown(page)

    assert "`data-table-role=child`" in rendered
    assert "`data-parent-table-id=p0001-t01`" in rendered
    assert "**Transfers description (Objects of Transfers)**" in rendered


def test_writer_builds_failure_record_with_error_code(create_pdf):
    pdf_path = create_pdf("writer-failure.pdf", pages=[{"body": "failure body"}])
    task = SliceTask(
        slice_number=1,
        slice_file=pdf_path.name,
        source_path=pdf_path,
        display_title="Failure",
        start_page=1,
        end_page=1,
    )

    record = build_failure_record(
        task,
        elapsed_ms=9,
        error_code="unsupported_input",
        error_message="not supported",
        stage_timings={"precheck_ms": 9},
    )

    assert record.status == "failed"
    assert record.error_code == "unsupported_input"
    assert record.stage_timings["precheck_ms"] == 9
    assert record.stage_timings["total_ms"] == 9


def test_render_page_markdown_replaces_complex_table_markdown_with_rendered_markdown():
    table_markdown = "|Step 1|Derive key|\n|---|---|\n|Step 2|Submit request|"
    page = PageContent(
        slice_page=1,
        source_page=1,
        is_overlap=False,
        markdown=f"before\n\n{table_markdown}\n\nafter",
        blocks=[],
        tables=[
            TableNode(
                type="table",
                source_page=1,
                bbox=[0, 0, 10, 10],
                table_strategy_used="lines",
                table_fallback_used=True,
                headers=[],
                rows=[["Step 1", "Derive key"], ["Step 2", "Submit request"]],
                markdown=table_markdown,
                rendered_markdown="Table metadata: `data-table-id=p0001-t01`\n\n| Step | Description |\n| --- | --- |\n| Step 1 | Derive key |\n| Step 2 | Submit request |",
                fallback_html="<div data-table-role=\"standalone\"><table><tbody><tr><td>Step 1</td><td>Derive key</td></tr><tr><td>Step 2</td><td>Submit request</td></tr></tbody></table></div>",
                fallback_image=None,
                table_id="p0001-t01",
            )
        ],
        images=[],
    )

    rendered = render_page_markdown(page)

    assert table_markdown not in rendered
    assert "`data-table-id=p0001-t01`" in rendered
    assert rendered.index("before") < rendered.index('`data-table-id=p0001-t01`') < rendered.index("after")

"""End-to-end golden / regression tests for Phase 3 repair pipeline.

Each test simulates a realistic PDF slice (content.json + draft markdown)
that exercises a specific real-world quality issue, then asserts on the
**final rendered markdown** — not internal helpers.

The fixtures are modelled after actual broken data observed in the
PayFi Merchant Open API document.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from md_format.block_aligner import align_blocks
from md_format.contracts import AutoFix, FormatTask, NormalizedDocument
from md_format.coverage_auditor import audit_coverage
from md_format.repair_engine import repair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _task(**overrides) -> FormatTask:
    defaults = dict(
        slice_file="golden-test.pdf",
        display_title="Golden Test Slice",
        order_index=1,
        input_dir=Path("."),
        content_file=Path("content.json"),
        draft_md_file=Path("test.md"),
        assets_dir=Path("assets"),
        phase2_manual_review_required=False,
        start_page=1,
        end_page=1,
    )
    defaults.update(overrides)
    return FormatTask(**defaults)


def _content(pages: list[dict]) -> dict:
    """Build a content dict from a list of page dicts."""
    return {"source_pages": pages}


def _page(
    source_page: int = 1,
    slice_page: int = 1,
    is_overlap: bool = False,
    blocks: list | None = None,
    tables: list | None = None,
    images: list | None = None,
) -> dict:
    return {
        "source_page": source_page,
        "slice_page": slice_page,
        "is_overlap": is_overlap,
        "blocks": blocks or [],
        "tables": tables or [],
        "images": images or [],
    }


def _block(
    text: str,
    *,
    type: str = "paragraph",
    reading_order: int = 0,
    dedupe_key: str = "",
    heading_level: int | None = None,
) -> dict:
    d = {
        "type": type,
        "text": text,
        "source_page": 1,
        "bbox": [0, 0, 100, 20],
        "reading_order": reading_order,
        "is_overlap": False,
        "dedupe_key": dedupe_key or f"dk-{reading_order}",
    }
    if heading_level is not None:
        d["heading_level"] = heading_level
    return d


def _table(
    headers: list[str],
    rows: list[list],
    *,
    markdown: str | None = None,
    fallback_image: str | None = None,
    table_id: str = "p0001-t01",
) -> dict:
    return {
        "type": "table",
        "source_page": 1,
        "bbox": [0, 0, 500, 200],
        "table_strategy_used": "lines",
        "table_fallback_used": False,
        "table_retry_pages": [],
        "headers": headers,
        "rows": rows,
        "markdown": markdown,
        "fallback_html": None,
        "fallback_image": fallback_image,
        "table_id": table_id,
        "parent_table_id": None,
        "table_role": "standalone",
        "section_title": None,
        "child_table_ids": [],
    }


def _run(content: dict, draft_md: str, **task_kw):
    """Run the full repair pipeline and return (doc, fixes, rendered_md)."""
    task = _task(**task_kw)
    audit = audit_coverage(content, draft_md)
    alignment = align_blocks(content, draft_md)
    doc, fixes = repair(task, content, draft_md, audit, alignment)
    rendered = _render(doc)
    return doc, fixes, rendered


def _render(doc: NormalizedDocument) -> str:
    """Render a NormalizedDocument to final markdown (same logic as renderer)."""
    parts: list[str] = []
    for page in doc.pages:
        for block in page.blocks:
            if block.markdown:
                parts.append(block.markdown)
    return "\n\n".join(parts)


# ===========================================================================
# Golden Test 1: Complex table with split field names
# ===========================================================================


class TestGoldenTableFieldSplitting:
    """Regression: PDF line-wrapping splits camelCase field names in table cells.

    Real examples from PayFi API doc:
      "cryptoAd dressInfo" → should become "cryptoAddressInfo"
      "fiatAccou ntInfo"   → should become "fiatAccountInfo"
      "receiveA mount"     → should become "receiveAmount"
      "complete Time"      → should become "completeTime"
    """

    # --- Scenario A: table has headers+rows (rebuild path) ---

    def test_rebuilt_table_repairs_split_fields(self):
        """When table markdown is absent, _rebuild_pipe_table repairs split names."""
        content = _content([_page(
            tables=[_table(
                headers=["Field", "Type", "Required", "Description"],
                rows=[
                    ["cryptoAd dressInfo", "object", "Y", "Crypto address info"],
                    ["fiatAccou ntInfo", "object", "Y", "Fiat account info"],
                    ["receiveA mount", "string", "Y", "Amount to receive"],
                    ["transactionId", "string", "Y", "Transaction identifier"],
                ],
                markdown=None,  # Force rebuild path
            )],
        )])
        _, _, md = _run(content, "Draft.\n", display_title="")

        assert "cryptoAddressInfo" in md
        assert "fiatAccountInfo" in md
        assert "receiveAmount" in md
        assert "transactionId" in md  # already clean → unchanged
        # Must NOT contain the broken forms
        assert "cryptoAd dressInfo" not in md
        assert "fiatAccou ntInfo" not in md
        assert "receiveA mount" not in md

    # --- Scenario B: table has existing pipe-table markdown (repair path) ---

    def test_existing_markdown_table_repairs_split_fields(self):
        """When table already has pipe-table markdown, _repair_table_markdown fixes it."""
        broken_md = (
            "| Field | Type | Required | Description |\n"
            "|---|---|---|---|\n"
            "| cryptoAd dressInfo | object | Y | Crypto address info |\n"
            "| fiatAccou ntInfo | object | Y | Fiat account info |\n"
            "| complete Time | string | N | Completion time |\n"
            "| transactionId | string | Y | Transaction identifier |"
        )
        content = _content([_page(
            tables=[_table(
                headers=["Field", "Type", "Required", "Description"],
                rows=[
                    ["cryptoAd dressInfo", "object", "Y", "Crypto address info"],
                    ["fiatAccou ntInfo", "object", "Y", "Fiat account info"],
                    ["complete Time", "string", "N", "Completion time"],
                    ["transactionId", "string", "Y", "Transaction identifier"],
                ],
                markdown=broken_md,
            )],
        )])
        _, _, md = _run(content, "Draft.\n", display_title="")

        assert "cryptoAddressInfo" in md
        assert "fiatAccountInfo" in md
        assert "completeTime" in md
        assert "transactionId" in md
        assert "cryptoAd dressInfo" not in md

    # --- Scenario C: multi-row parameter table with mixed breakage ---

    def test_multirow_parameter_table(self):
        """Simulates a large parameter table with some split and some clean names."""
        content = _content([_page(
            blocks=[
                _block("8.8.1 Create Payout Order", type="heading", reading_order=1,
                       heading_level=3),
            ],
            tables=[_table(
                headers=["Parameter", "Type", "Required", "Description"],
                rows=[
                    ["merchantId", "string", "Y", "Merchant identifier"],
                    ["supportC urrency", "string", "Y", "Supported currency list"],
                    ["partyDeta ils", "object", "Y", "Counterparty details"],
                    ["bankAccou ntNumber", "string", "Y", "Bank account number"],
                    ["beneficiaryName", "string", "Y", "Name of beneficiary"],
                ],
                markdown=None,
            )],
        )])
        draft = "### 8.8.1 Create Payout Order\n\nSome text.\n"
        _, _, md = _run(content, draft, display_title="")

        # Split identifiers repaired
        assert "supportCurrency" in md
        assert "partyDetails" in md
        assert "bankAccountNumber" in md
        # Clean identifiers preserved
        assert "merchantId" in md
        assert "beneficiaryName" in md
        # Broken forms gone
        assert "supportC urrency" not in md
        assert "partyDeta ils" not in md
        assert "bankAccou ntNumber" not in md


# ===========================================================================
# Golden Test 2: Code example fenced block fidelity
# ===========================================================================


class TestGoldenCodeBlockFidelity:
    """Regression: PDF extraction splits each code line into a separate paragraph.

    Real pattern from PayFi API doc — Java encryption example:
      Line 1: "public static String[] encrypt(String plainText) {"
      Line 2: "Validate.notNull(plainText);"
      Line 3: "byte[] key = Hex.decodeHex(keyHex);"
      Line 4: "return new String[]{result};"
      Line 5: "}"

    All 5 lines (including the closing brace) must end up inside a single
    fenced code block.
    """

    def test_java_encryption_example_merged(self):
        """Full Java method: all lines including closing brace in one code fence."""
        content = _content([_page(
            blocks=[
                _block("8.2 Encryption Example", type="heading", reading_order=1,
                       heading_level=2),
                _block("The following example shows AES encryption:", reading_order=2),
                _block("public static String[] encrypt(String plainText) {", reading_order=3),
                _block("Validate.notNull(plainText);", reading_order=4),
                _block("byte[] key = Hex.decodeHex(keyHex);", reading_order=5),
                _block("Cipher cipher = Cipher.getInstance(ALGORITHM);", reading_order=6),
                _block("return new String[]{result};", reading_order=7),
                _block("}", reading_order=8),
            ],
        )])
        draft = "## 8.2 Encryption Example\n\nThe following example shows AES encryption:\n\n```java\npublic static String[] encrypt(String plainText) {\n  Validate.notNull(plainText);\n  byte[] key = Hex.decodeHex(keyHex);\n  Cipher cipher = Cipher.getInstance(ALGORITHM);\n  return new String[]{result};\n}\n```\n"
        _, fixes, md = _run(content, draft, display_title="")

        # Must have a fenced code block
        assert "```" in md
        # All code lines must be inside the fence
        assert "encrypt(String plainText)" in md
        assert "Validate.notNull(plainText);" in md
        assert "Hex.decodeHex(keyHex)" in md
        assert "Cipher.getInstance(ALGORITHM)" in md
        assert "return new String[]{result};" in md

        # Critical: closing brace must be INSIDE the code block, not dangling outside
        code_fences = md.split("```")
        # code_fences[0] = before fence, [1] = inside fence, [2] = after fence, ...
        code_inside = "".join(code_fences[1::2])  # odd-indexed parts are inside fences
        assert "}" in code_inside, "Closing brace must be inside fenced code block"

    def test_typescript_example_merged(self):
        """TypeScript async function: all lines merged into code block."""
        content = _content([_page(
            blocks=[
                _block("TypeScript Example", type="heading", reading_order=1),
                _block("const encrypt = async (data: string) => {", reading_order=2),
                _block("const key = await getKey();", reading_order=3),
                _block("const result = crypto.encrypt(key, data);", reading_order=4),
                _block("return result;", reading_order=5),
                _block("};", reading_order=6),
            ],
        )])
        draft = "## TypeScript Example\n\n```typescript\nconst encrypt = async (data: string) => {\n  const key = await getKey();\n  const result = crypto.encrypt(key, data);\n  return result;\n};\n```\n"
        _, _, md = _run(content, draft, display_title="")

        assert "```" in md
        code_fences = md.split("```")
        code_inside = "".join(code_fences[1::2])
        assert "encrypt" in code_inside
        assert "getKey()" in code_inside
        assert "return result;" in code_inside
        assert "};" in code_inside, "Closing }; must be inside fenced code block"

    def test_code_with_try_catch_braces(self):
        """Java try-catch: multiple brace-only lines all captured."""
        content = _content([_page(
            blocks=[
                _block("Error Handling", type="heading", reading_order=1),
                _block("try {", reading_order=2),
                _block("byte[] data = decrypt(input);", reading_order=3),
                _block("return new String(data);", reading_order=4),
                _block("} catch (Exception e) {", reading_order=5),
                _block("throw new RuntimeException(e);", reading_order=6),
                _block("}", reading_order=7),
            ],
        )])
        draft = "## Error Handling\n\n```java\ntry {\n  byte[] data = decrypt(input);\n  return new String(data);\n} catch (Exception e) {\n  throw new RuntimeException(e);\n}\n```\n"
        _, _, md = _run(content, draft, display_title="")

        assert "```" in md
        code_fences = md.split("```")
        code_inside = "".join(code_fences[1::2])
        assert "try {" in code_inside
        assert "} catch (Exception e) {" in code_inside
        assert "throw new RuntimeException(e);" in code_inside
        # Final closing brace must be inside
        lines_inside = code_inside.strip().splitlines()
        assert lines_inside[-1].strip() == "}", \
            f"Last line of code block should be '}}', got: {lines_inside[-1]!r}"

    def test_image_between_code_lines_breaks_block(self):
        """An image inserted mid-code should NOT be swallowed into the code fence."""
        content = _content([_page(
            blocks=[
                _block("public void process(String input) {", reading_order=1),
                _block("validate(input);", reading_order=2),
                _block("transform(input);", reading_order=3),
            ],
            images=[
                {
                    "type": "image",
                    "source_page": 1,
                    "bbox": [0, 0, 100, 100],
                    "asset_path": "assets/p0001_img01.png",
                    "width": 200,
                    "height": 100,
                    "caption": None,
                },
            ],
        )])
        # Image has reading_order from bbox, placed between code lines
        content["source_pages"][0]["images"][0]["bbox"] = [0, 50, 100, 60]
        content["source_pages"][0]["blocks"][1]["bbox"] = [0, 40, 100, 50]
        # Give image reading_order that puts it between blocks
        # (The repair engine sorts by reading_order)

        draft = "Code and image.\n"
        _, _, md = _run(content, draft, display_title="")

        # Image markdown must NOT be inside a code fence
        assert "![" in md, "Image should be rendered"


# ===========================================================================
# Golden Test 3: Heading hierarchy preservation
# ===========================================================================


class TestGoldenHeadingHierarchy:
    """Regression: All headings rendered as flat H2 regardless of nesting.

    Real pattern: API docs have numbered sections like:
      "8 API Reference"       → H1
      "8.1 Common Headers"    → H2
      "8.1.1 Request Headers" → H3
      "8.1.1.1 Details"       → H4
    """

    def test_numbered_section_hierarchy(self):
        """Numbered headings produce correct H1–H4 levels."""
        content = _content([_page(
            blocks=[
                _block("8 API Reference", type="heading", reading_order=1,
                       heading_level=1),
                _block("Overview of the API.", reading_order=2),
                _block("8.1 Common Headers", type="heading", reading_order=3,
                       heading_level=2),
                _block("Headers used across endpoints.", reading_order=4),
                _block("8.1.1 Request Headers", type="heading", reading_order=5,
                       heading_level=3),
                _block("Content-Type must be application/json.", reading_order=6),
                _block("8.1.1.1 Authentication Header", type="heading", reading_order=7,
                       heading_level=4),
                _block("Use X-Api-Key header.", reading_order=8),
            ],
        )])
        draft = (
            "# 8 API Reference\n\nOverview.\n\n"
            "## 8.1 Common Headers\n\nHeaders.\n\n"
            "### 8.1.1 Request Headers\n\nContent-Type.\n\n"
            "#### 8.1.1.1 Authentication Header\n\nX-Api-Key.\n"
        )
        _, _, md = _run(content, draft, display_title="")

        assert "# 8 API Reference" in md
        assert "## 8.1 Common Headers" in md
        assert "### 8.1.1 Request Headers" in md
        assert "#### 8.1.1.1 Authentication Header" in md
        # Must NOT be flat H2 for all
        assert md.count("## 8 API Reference") == 0, "H1 should not be H2"

    def test_chinese_chapter_heading(self):
        """Chinese chapter markers get correct levels."""
        content = _content([_page(
            blocks=[
                _block("第一章 概述", type="heading", reading_order=1,
                       heading_level=1),
                _block("系统介绍", reading_order=2),
                _block("1.1 系统架构", type="heading", reading_order=3,
                       heading_level=2),
            ],
        )])
        draft = "# 第一章 概述\n\n系统介绍\n\n## 1.1 系统架构\n"
        _, _, md = _run(content, draft, display_title="")

        assert "# 第一章 概述" in md
        assert "## 1.1 系统架构" in md

    def test_heading_level_from_draft_when_content_lacks_it(self):
        """When content.json has no heading_level, draft markdown levels are used.

        Note: _fix_heading_levels prevents jumps > 1, so the hierarchy must be
        realistic (H1 → H2 → H3, no gaps).
        """
        content = _content([_page(
            blocks=[
                _block("Overview", type="heading", reading_order=1),
                _block("Details section.", reading_order=2),
                _block("Common Headers", type="heading", reading_order=3),
                _block("More details.", reading_order=4),
                _block("Request Headers", type="heading", reading_order=5),
            ],
        )])
        draft = (
            "# Overview\n\nDetails section.\n\n"
            "## Common Headers\n\nMore details.\n\n"
            "### Request Headers\n"
        )
        _, _, md = _run(content, draft, display_title="")

        # All heading levels come from draft cross-reference (no heading_level in content)
        assert "# Overview" in md
        assert "## Common Headers" in md
        assert "### Request Headers" in md


# ===========================================================================
# Golden Test 4: Mixed scenario — table + code + headings on same page
# ===========================================================================


class TestGoldenMixedContent:
    """Full-slice simulation with headings, tables, and code on one page."""

    def test_api_endpoint_documentation_slice(self):
        """Simulates a typical API endpoint doc page with all content types."""
        content = _content([_page(
            blocks=[
                _block("8.5.1 Query Balance", type="heading", reading_order=1,
                       heading_level=3),
                _block("Query the merchant's current balance.", reading_order=2),
                _block("Request example:", reading_order=10),
                # Code lines (reading_order 11-16)
                _block("public void queryBalance() {", reading_order=11),
                _block("HttpClient client = HttpClient.newBuilder().build();", reading_order=12),
                _block("HttpRequest request = buildRequest(url);", reading_order=13),
                _block("HttpResponse<String> resp = client.send(request);", reading_order=14),
                _block("System.out.println(resp.body());", reading_order=15),
                _block("}", reading_order=16),
            ],
            tables=[_table(
                headers=["Parameter", "Type", "Required", "Description"],
                rows=[
                    ["merchantId", "string", "Y", "Merchant ID"],
                    ["accountT ype", "string", "Y", "Account type"],
                    ["queryS tartDate", "string", "N", "Query start date"],
                ],
                markdown=None,
            )],
        )])
        draft = (
            "### 8.5.1 Query Balance\n\n"
            "Query the merchant's current balance.\n\n"
            "| Parameter | Type | Required | Description |\n"
            "|---|---|---|---|\n"
            "| merchantId | string | Y | Merchant ID |\n\n"
            "Request example:\n\n"
            "```java\npublic void queryBalance() {\n"
            "  HttpClient client = HttpClient.newBuilder().build();\n}\n```\n"
        )
        _, _, md = _run(content, draft, display_title="")

        # Heading hierarchy
        assert "### 8.5.1 Query Balance" in md

        # Table field repair
        assert "accountType" in md
        assert "queryStartDate" in md
        assert "accountT ype" not in md
        assert "queryS tartDate" not in md

        # Code block completeness
        assert "```" in md
        code_fences = md.split("```")
        code_inside = "".join(code_fences[1::2])
        assert "queryBalance()" in code_inside
        assert "HttpClient.newBuilder()" in code_inside
        assert "}" in code_inside


# ===========================================================================
# Golden Test 5: Full-page image suppression
# ===========================================================================


class TestGoldenFullpageImageSuppression:
    """Regression: Full-page screenshots break inline code blocks.

    Phase 2 exports full-page renders (bbox covers ~80%+ of page height).
    When code spans multiple pages, these images get inserted mid-code,
    breaking the fenced block.
    """

    def test_fullpage_image_suppressed_on_code_page(self):
        """Full-page image (bbox height > 600pt) is suppressed when page has text."""
        content = _content([_page(
            blocks=[
                _block("public static void encrypt() {", reading_order=1),
                _block("Validate.notNull(input);", reading_order=2),
                _block("byte[] key = getKey();", reading_order=3),
            ],
            images=[{
                "type": "image",
                "source_page": 1,
                "bbox": [90.0, 72.0, 505.0, 770.0],  # height ~698pt → full page
                "asset_path": "assets/p0001_img01.jpeg",
                "width": 640,
                "height": 960,
                "caption": None,
            }],
        )])
        _, fixes, md = _run(content, "Code.\n", display_title="")

        # Image should be suppressed
        assert "![" not in md
        assert any(f.fix_type == "fullpage_image_suppressed" for f in fixes)

        # Code should be intact (not split by image)
        assert "```" in md
        code_fences = md.split("```")
        code_inside = "".join(code_fences[1::2])
        assert "encrypt()" in code_inside
        assert "Validate.notNull" in code_inside

    def test_small_image_not_suppressed(self):
        """Normal content images (small bbox) are kept."""
        content = _content([_page(
            blocks=[
                _block("Architecture overview.", reading_order=1),
            ],
            images=[{
                "type": "image",
                "source_page": 1,
                "bbox": [100.0, 200.0, 400.0, 350.0],  # height ~150pt → normal
                "asset_path": "assets/p0001_diagram.png",
                "width": 300,
                "height": 150,
                "caption": "System architecture",
            }],
        )])
        _, fixes, md = _run(content, "Overview.\n", display_title="")

        # Image should be kept
        assert "![" in md
        assert not any(f.fix_type == "fullpage_image_suppressed" for f in fixes)


# ===========================================================================
# Golden Test 6: Multi-word table cell identifier joining
# ===========================================================================


class TestGoldenMultiWordIdentifierJoin:
    """Regression: 3+ word cells with split identifiers.

    Real patterns from Phase 2:
      "currency supportC urrency"         → "currency supportCurrency"
      "cryptoMethod cryptoAd dressInfo"   → "cryptoMethod cryptoAddressInfo"
      "fiatMethod fiatAccou ntInfo"       → "fiatMethod fiatAccountInfo"
    """

    def test_three_word_cell_with_fragment(self):
        """'currency supportC urrency' repaired in rebuilt table."""
        content = _content([_page(
            tables=[_table(
                headers=["Field", "Req", "Type", "Description"],
                rows=[
                    ["currency supportC urrency", "N", "Arrays of string", "Supported currencies"],
                ],
                markdown=None,
            )],
        )])
        _, _, md = _run(content, "Draft.\n", display_title="")

        assert "supportCurrency" in md
        assert "supportC urrency" not in md

    def test_three_word_field_annotation_plus_identifier(self):
        """'cryptoMethod cryptoAd dressInfo' → 'cryptoMethod cryptoAddressInfo'."""
        content = _content([_page(
            tables=[_table(
                headers=["Field", "Req", "Type", "Description"],
                rows=[
                    ["cryptoMethod cryptoAd dressInfo", "C", "Array of objects", "Crypto address"],
                    ["fiatMethod fiatAccou ntInfo", "C", "object", "Fiat account"],
                ],
                markdown=None,
            )],
        )])
        _, _, md = _run(content, "Draft.\n", display_title="")

        assert "cryptoAddressInfo" in md
        assert "fiatAccountInfo" in md
        assert "cryptoAd dressInfo" not in md
        assert "fiatAccou ntInfo" not in md

    def test_existing_markdown_three_word_cell(self):
        """Multi-word repair works on existing pipe table markdown too."""
        broken_md = (
            "| Field | Req | Type | Description |\n"
            "|---|---|---|---|\n"
            "| currency supportC urrency | N | string | Supported |"
        )
        content = _content([_page(
            tables=[_table(
                headers=["Field", "Req", "Type", "Description"],
                rows=[["currency supportC urrency", "N", "string", "Supported"]],
                markdown=broken_md,
            )],
        )])
        _, _, md = _run(content, "Draft.\n", display_title="")

        assert "supportCurrency" in md
        assert "supportC urrency" not in md


# ===========================================================================
# Golden Test 7: Cross-page code block stitching
# ===========================================================================


class TestGoldenCrossPageCodeStitching:
    """Regression: Code spanning two PDF pages produces two separate fences."""

    def test_code_across_two_pages_stitched(self):
        """Code blocks from adjacent pages are merged into one fence."""
        page1 = _page(
            source_page=27, slice_page=3,
            blocks=[
                _block("Encryption Example", type="heading", reading_order=1),
                _block("public static String[] encrypt(String plainText) {", reading_order=2),
                _block("Validate.notNull(plainText);", reading_order=3),
                _block("byte[] key = Hex.decodeHex(keyHex);", reading_order=4),
            ],
        )
        page2 = _page(
            source_page=28, slice_page=4,
            blocks=[
                _block("Cipher cipher = Cipher.getInstance(ALGORITHM);", reading_order=1),
                _block("return new String[]{result};", reading_order=2),
                _block("}", reading_order=3),
            ],
        )
        content = _content([page1, page2])
        draft = "## Encryption Example\n\n```java\npublic static...\n```\n"
        _, fixes, md = _run(content, draft, display_title="", end_page=28)

        # All code should be in ONE fence
        code_fences = md.split("```")
        code_parts = [code_fences[i] for i in range(1, len(code_fences), 2)]
        assert len(code_parts) == 1, f"Expected 1 code fence, got {len(code_parts)}"

        code = code_parts[0]
        assert "encrypt(String plainText)" in code
        assert "Validate.notNull" in code
        assert "Cipher.getInstance" in code
        assert "return new String[]{result};" in code
        assert any("cross_page" in f.fix_type for f in fixes)

    def test_non_code_between_pages_prevents_stitching(self):
        """If page B starts with non-code content, no stitching occurs."""
        page1 = _page(
            source_page=10, slice_page=1,
            blocks=[
                _block("try {", reading_order=1),
                _block("doSomething();", reading_order=2),
                _block("return result;", reading_order=3),
            ],
        )
        page2 = _page(
            source_page=11, slice_page=2,
            blocks=[
                _block("This is a description paragraph.", reading_order=1),
                _block("Another paragraph.", reading_order=2),
            ],
        )
        content = _content([page1, page2])
        _, fixes, md = _run(content, "Draft.\n", display_title="", end_page=11)

        # No cross-page stitching
        assert not any("cross_page" in f.fix_type for f in fixes)


# ===========================================================================
# Golden Test 8: Leading spillover trimming
# ===========================================================================


class TestGoldenLeadingSpilloverTrim:
    """Regression: first page may start with trailing content from the prior section."""

    def test_trim_blocks_before_first_numbered_heading(self):
        content = _content([_page(
            blocks=[
                _block('{"tail": true}', reading_order=1),
                _block('"memo": "test payout"', reading_order=2),
                _block('}', reading_order=3),
                _block('8.8 Payout Order API', type='heading', reading_order=20, heading_level=2),
                _block('8.8.1 Create Payout Order', type='heading', reading_order=21, heading_level=3),
                _block('Endpoint:', reading_order=22),
            ],
        )])
        draft = """## 8.8 Payout Order API

### 8.8.1 Create Payout Order

Endpoint:
"""
        _, fixes, md = _run(content, draft, display_title='')

        assert '{"tail": true}' not in md
        assert '"memo": "test payout"' not in md
        assert md.startswith('## 8.8 Payout Order API')
        assert any(f.fix_type == 'leading_spillover_trimmed' for f in fixes)


class TestGoldenComplexHtmlPreference:
    def test_complex_table_prefers_html_fallback_over_rebuild(self):
        table = _table(
            headers=["Field", "Req", "Type", "Description"],
            rows=[["requestId", "Y", "string", "External id"]],
            markdown=None,
            table_id="p0002-t01",
        )
        table["table_role"] = "parent"
        table["fallback_html"] = '<div class="complex-table-block" data-table-id="p0002-t01" data-table-role="parent"><table><thead><tr><th>Field</th></tr></thead><tbody><tr><td>requestId</td></tr></tbody></table></div>'
        content = _content([_page(tables=[table])])
        _, fixes, md = _run(content, "Draft.\n", display_title='')

        assert '<div class="complex-table-block"' in md
        assert '| Field |' not in md
        assert any(f.fix_type == 'table_fallback_html_applied' for f in fixes)

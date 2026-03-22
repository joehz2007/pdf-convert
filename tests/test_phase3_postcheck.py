from __future__ import annotations

from md_format.postcheck import PostcheckResult, postcheck


class TestPostcheck:
    def test_stable_markdown_passes(self):
        md = "# Title\n\nParagraph text.\n"
        result = postcheck(md, md)
        assert result.passed is True
        assert len(result.issues) == 0

    def test_empty_output_fails(self):
        result = postcheck("# Title\n\nText.\n", "")
        assert result.passed is False
        assert any(i.issue_type == "format_parse_unstable" for i in result.issues)

    def test_whitespace_only_output_fails(self):
        result = postcheck("# Title\n\nText.\n", "   \n\n  ")
        assert result.passed is False

    def test_minor_formatting_changes_pass(self):
        pre = "# Title\n\nSome text here.\n\n- item 1\n- item 2\n"
        post = "# Title\n\nSome text here.\n\n- item 1\n- item 2\n"
        result = postcheck(pre, post)
        assert result.passed is True

    def test_significant_block_drift_fails(self):
        pre = "# A\n\n## B\n\n## C\n\n## D\n\n## E\n\n## F\n\n## G\n\n## H\n\n## I\n\n## J\n"
        # Remove most blocks
        post = "# A\n\n## B\n"
        result = postcheck(pre, post)
        assert result.passed is False
        assert any(i.issue_type == "format_parse_unstable" for i in result.issues)

    def test_asset_reference_check(self):
        pre = "![img](assets/p1.png)\n"
        post = "![img](assets/p1.png)\n"
        result = postcheck(pre, post, asset_paths=["assets/p1.png"])
        assert result.passed is True
        assert not any(i.issue_type == "asset_not_found" for i in result.issues)

    def test_missing_asset_reference_warning(self):
        pre = "![img](assets/p1.png)\n"
        post = "Some text without image.\n"
        result = postcheck(pre, post, asset_paths=["assets/p1.png"])
        asset_issues = [i for i in result.issues if i.issue_type == "asset_not_found"]
        assert len(asset_issues) == 1
        assert asset_issues[0].severity == "warning"

    def test_returns_postcheck_result(self):
        result = postcheck("text\n", "text\n")
        assert isinstance(result, PostcheckResult)
        assert result.pre_block_count >= 0
        assert result.post_block_count >= 0

    def test_block_counts_recorded(self):
        pre = "# A\n\nText.\n\n- item\n"
        result = postcheck(pre, pre)
        assert result.pre_block_count == result.post_block_count
        assert result.pre_block_count > 0

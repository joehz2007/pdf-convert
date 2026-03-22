"""Post-render verifier — validates final Markdown stability.

Re-parses the final Markdown and checks that the structure has not
drifted significantly from the pre-normalization version.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .block_aligner import parse_markdown_segments
from .contracts import AuditIssue

LOGGER = logging.getLogger("md_format.postcheck")

# Maximum allowed block count drift ratio before flagging instability
_MAX_BLOCK_DRIFT_RATIO = 0.2


@dataclass(slots=True)
class PostcheckResult:
    """Result of the post-render verification."""

    passed: bool
    issues: list[AuditIssue]
    pre_block_count: int = 0
    post_block_count: int = 0


def postcheck(
    pre_normalize_markdown: str,
    post_normalize_markdown: str,
    *,
    asset_paths: list[str] | None = None,
) -> PostcheckResult:
    """Verify that normalization did not break the Markdown structure.

    Checks:
    1. Final Markdown is non-empty
    2. Block count has not drifted significantly
    3. Asset references still exist in the output
    """
    issues: list[AuditIssue] = []

    # Check non-empty
    if not post_normalize_markdown or not post_normalize_markdown.strip():
        issues.append(AuditIssue(
            issue_type="format_parse_unstable",
            severity="error",
            source_page=None,
            reading_order=None,
            node_ref=None,
            message="Post-normalization Markdown is empty.",
            auto_fixable=False,
        ))
        return PostcheckResult(passed=False, issues=issues)

    # Parse both versions
    pre_segments = parse_markdown_segments(pre_normalize_markdown)
    post_segments = parse_markdown_segments(post_normalize_markdown)

    pre_count = len(pre_segments)
    post_count = len(post_segments)

    # Check block count drift
    if pre_count > 0:
        drift = abs(post_count - pre_count) / pre_count
        if drift > _MAX_BLOCK_DRIFT_RATIO:
            issues.append(AuditIssue(
                issue_type="format_parse_unstable",
                severity="error",
                source_page=None,
                reading_order=None,
                node_ref=None,
                message=(
                    f"Block count drifted significantly after normalization: "
                    f"{pre_count} -> {post_count} (drift={drift:.1%})"
                ),
                auto_fixable=False,
            ))

    # Check asset references
    if asset_paths:
        for asset_path in asset_paths:
            if asset_path and asset_path not in post_normalize_markdown:
                issues.append(AuditIssue(
                    issue_type="asset_not_found",
                    severity="warning",
                    source_page=None,
                    reading_order=None,
                    node_ref=None,
                    message=f"Asset reference lost after normalization: {asset_path}",
                    auto_fixable=False,
                ))

    passed = not any(i.severity == "error" for i in issues)

    return PostcheckResult(
        passed=passed,
        issues=issues,
        pre_block_count=pre_count,
        post_block_count=post_count,
    )

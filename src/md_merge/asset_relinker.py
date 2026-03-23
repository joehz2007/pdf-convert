from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from .contracts import AssetRelink, MergeTask, MergeWarning

LOGGER = logging.getLogger("md_merge.asset_relinker")


def relink_assets(
    tasks: list[MergeTask],
    slice_contents: dict[str, str],
    out_path: Path,
    *,
    copy_assets: bool,
    warnings: list[MergeWarning],
) -> list[AssetRelink]:
    """Copy assets and rewrite markdown image paths.

    Returns list of AssetRelink records.
    """
    relinks: list[AssetRelink] = []
    assets_root = out_path / "assets"

    for task in tasks:
        target_subdir = f"{task.order_index:03d}-{_safe_dirname(task.display_title)}"
        content = slice_contents.get(task.slice_file, "")

        if copy_assets and task.assets_dir and task.assets_dir.exists():
            dest = assets_root / target_subdir
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(task.assets_dir, dest)
                LOGGER.debug("Copied assets %s -> %s", task.assets_dir, dest)
            except OSError as e:
                msg = f"Failed to copy assets for {task.slice_file}: {e}"
                LOGGER.warning(msg)
                warnings.append(MergeWarning(
                    warning_type="asset_copy_failed",
                    slice_file=task.slice_file,
                    message=msg,
                ))

        # Rewrite markdown image paths
        new_content, new_relinks = _rewrite_paths(
            content, task, target_subdir, warnings,
        )
        slice_contents[task.slice_file] = new_content
        relinks.extend(new_relinks)

    return relinks


def _rewrite_paths(
    content: str,
    task: MergeTask,
    target_subdir: str,
    warnings: list[MergeWarning],
) -> tuple[str, list[AssetRelink]]:
    """Rewrite asset paths in markdown content."""
    relinks: list[AssetRelink] = []

    # Rewrite Markdown images: ![alt](assets/foo.png) -> ![alt](assets/subdir/foo.png)
    def _replace_md_img(m: re.Match) -> str:
        prefix = m.group(1)  # ![alt]
        asset_path = m.group(2)  # original path after assets/
        new_path = f"assets/{target_subdir}/{asset_path}"
        relinks.append(AssetRelink(
            slice_file=task.slice_file,
            original_path=f"assets/{asset_path}",
            rewritten_path=new_path,
        ))
        return f"{prefix}({new_path})"

    content = re.sub(
        r"(!\[[^\]]*\])\(assets/([^)]+)\)",
        _replace_md_img,
        content,
    )

    # Rewrite HTML img src: src="assets/foo.png" -> src="assets/subdir/foo.png"
    def _replace_html_img(m: re.Match) -> str:
        quote_prefix = m.group(1)  # src="  or src='
        asset_path = m.group(2)
        new_path = f"assets/{target_subdir}/{asset_path}"
        relinks.append(AssetRelink(
            slice_file=task.slice_file,
            original_path=f"assets/{asset_path}",
            rewritten_path=new_path,
        ))
        return f"{quote_prefix}{new_path}"

    content = re.sub(
        r"""(src=["'])assets/([^"']+)""",
        _replace_html_img,
        content,
    )

    return content, relinks


def _safe_dirname(title: str) -> str:
    illegal = r'<>:"/\|?*'
    result = title
    for ch in illegal:
        result = result.replace(ch, "_")
    return result.strip(". ")

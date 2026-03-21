"""切分规划模块。

负责把识别出的章节结构转换成最终切片计划，并应用语义边界校验、重叠页保留和超限标记。
"""

from __future__ import annotations

import logging
from dataclasses import replace

from .models import ChapterNode, SlicePlan
from .recognizer import detect_sections


LOGGER = logging.getLogger(__name__)
OVERSIZED_EXCEPTIONS = {"oversized_section", "oversized_semantic_block"}


class SplitPlanner:
    """根据章节结构生成最终切片计划。"""
    def __init__(
        self,
        document,
        analyzer,
        max_pages: int = 20,
        hard_max_pages: int = 25,
        min_merge_pages: int = 6,
    ):
        self.document = document
        self.analyzer = analyzer
        self.max_pages = max_pages
        self.hard_max_pages = hard_max_pages
        self.min_merge_pages = min_merge_pages
        self.chapter_start_pages: set[int] = set()

    def plan(self, chapters: list[ChapterNode]) -> list[SlicePlan]:
        """生成完整切片计划。

        顺序为：小章合并、超大章拆分、语义边界校验、重叠页注入、异常标记归一化。
        """
        # 记录所有结构起始页，后续在章节或 section 边界上优先做重叠保留。
        self.chapter_start_pages = {chapter.start_page for chapter in chapters[1:]}
        base_plans: list[SlicePlan] = []
        index = 0
        while index < len(chapters):
            merged_plan, next_index = self._try_merge_small_chapters(chapters, index)
            if merged_plan is not None:
                base_plans.append(merged_plan)
                index = next_index
                continue

            chapter = chapters[index]
            if chapter.page_span <= self.hard_max_pages:
                base_plans.append(
                    SlicePlan(
                        title=chapter.title,
                        start_page=chapter.start_page,
                        end_page=chapter.end_page,
                        split_mode="chapter",
                        boundary_reason="chapter_boundary",
                        toc_level=chapter.level,
                    )
                )
            else:
                base_plans.extend(self._split_large_chapter(chapter))
            index += 1

        semantically_adjusted = self._apply_semantic_boundary_pass(base_plans)
        overlapped = self._inject_overlap_pages(semantically_adjusted)
        return self._normalize_plan_flags(overlapped)

    def _try_merge_small_chapters(self, chapters: list[ChapterNode], start_index: int) -> tuple[SlicePlan | None, int]:
        """尝试把连续小章合并成一个切片。"""
        chapter = chapters[start_index]
        if chapter.page_span > self.max_pages:
            return None, start_index

        grouped = [chapter]
        group_start = chapter.start_page
        group_end = chapter.end_page
        next_index = start_index + 1

        while next_index < len(chapters):
            # 小章合并不是无限向后吞并，只合到“可接受体量”就停，避免前几章全部并成一个大块。
            current_pages = group_end - group_start + 1
            if len(grouped) >= 2 and current_pages >= self.min_merge_pages:
                break

            next_chapter = chapters[next_index]
            if next_chapter.page_span > self.max_pages:
                break
            combined_pages = next_chapter.end_page - group_start + 1
            if combined_pages > self.max_pages:
                break
            grouped.append(next_chapter)
            group_end = next_chapter.end_page
            next_index += 1

        if len(grouped) < 2:
            return None, start_index

        merged_title = " + ".join(item.title for item in grouped)
        return (
            SlicePlan(
                title=merged_title,
                start_page=group_start,
                end_page=group_end,
                split_mode="merge",
                boundary_reason="chapter_boundary",
                toc_level=min(item.level for item in grouped),
            ),
            next_index,
        )

    def _split_large_chapter(self, chapter: ChapterNode) -> list[SlicePlan]:
        """拆分超过阈值的大章节。

        优先按识别到的小节组包；若仍无法满足约束，再退回物理切分。
        """
        sections = detect_sections(self.document, chapter)
        if sections:
            # section 起始页也纳入重叠页候选，这样结构页能在相邻切片中双向保留。
            self.chapter_start_pages.update(section.start_page for section in sections[1:])
            planned = self._pack_sections(chapter, sections)
            if planned:
                return planned
        return self._physical_split(chapter)

    def _pack_sections(self, chapter: ChapterNode, sections: list[ChapterNode]) -> list[SlicePlan]:
        """按小节组包生成切片，允许在硬上限内浮动。"""
        plans: list[SlicePlan] = []
        buffer: list[ChapterNode] = []
        for section in sections:
            if section.page_span > self.hard_max_pages:
                if buffer:
                    plans.append(self._plan_from_sections(buffer))
                    buffer = []
                plans.append(
                    SlicePlan(
                        title=section.title,
                        start_page=section.start_page,
                        end_page=section.end_page,
                        split_mode="section",
                        boundary_reason="section_boundary",
                        exception_type="oversized_section",
                        manual_review_required=True,
                        toc_level=section.level,
                    )
                )
                continue

            if not buffer:
                buffer = [section]
                continue

            combined_pages = section.end_page - buffer[0].start_page + 1
            # section 组包允许浮动到 25 页，20 页只是目标值，不是绝对截断线。
            if combined_pages <= self.hard_max_pages:
                buffer.append(section)
            else:
                plans.append(self._plan_from_sections(buffer))
                buffer = [section]

        if buffer:
            plans.append(self._plan_from_sections(buffer))

        if len(plans) == 1 and plans[0].start_page == chapter.start_page and plans[0].end_page == chapter.end_page:
            if plans[0].actual_pages > self.hard_max_pages:
                return []
        return plans

    def _plan_from_sections(self, sections: list[ChapterNode]) -> SlicePlan:
        first = sections[0]
        last = sections[-1]
        title = first.title if len(sections) == 1 else f"{first.title} - {last.title}"
        return SlicePlan(
            title=title,
            start_page=first.start_page,
            end_page=last.end_page,
            split_mode="section",
            boundary_reason="section_boundary",
            toc_level=min(section.level for section in sections),
        )

    def _physical_split(self, chapter: ChapterNode) -> list[SlicePlan]:
        """在无可用结构信息时，按页数和语义边界做物理切分。"""
        plans: list[SlicePlan] = []
        current_start = chapter.start_page
        while current_start <= chapter.end_page:
            remaining = chapter.end_page - current_start + 1
            if remaining <= self.hard_max_pages:
                # 最后一段只要不超过硬上限，就直接保留，避免为了凑 20 页再做一次无意义切分。
                plans.append(
                    SlicePlan(
                        title=chapter.title,
                        start_page=current_start,
                        end_page=chapter.end_page,
                        split_mode="physical",
                        boundary_reason="fallback_physical" if remaining <= self.max_pages else "semantic_integrity",
                        toc_level=chapter.level,
                    )
                )
                break

            desired_end = current_start + self.max_pages - 1
            normal_upper_bound = min(current_start + self.hard_max_pages - 1, chapter.end_page - 1)
            safe_end = self._find_nearest_safe_boundary(current_start, desired_end, normal_upper_bound)
            if safe_end is not None:
                plans.append(
                    SlicePlan(
                        title=chapter.title,
                        start_page=current_start,
                        end_page=safe_end,
                        split_mode="physical",
                        boundary_reason="page_limit" if safe_end == desired_end else "semantic_integrity",
                        toc_level=chapter.level,
                    )
                )
                current_start = safe_end + 1
                continue

            oversized_end = self._find_first_safe_boundary_forward(normal_upper_bound + 1, chapter.end_page - 1)
            if oversized_end is not None:
                plans.append(
                    SlicePlan(
                        title=chapter.title,
                        start_page=current_start,
                        end_page=oversized_end,
                        split_mode="physical",
                        boundary_reason="semantic_integrity",
                        exception_type="oversized_semantic_block",
                        manual_review_required=True,
                        toc_level=chapter.level,
                    )
                )
                current_start = oversized_end + 1
                continue

            plans.append(
                SlicePlan(
                    title=chapter.title,
                    start_page=current_start,
                    end_page=chapter.end_page,
                    split_mode="physical",
                    boundary_reason="semantic_integrity",
                    exception_type="oversized_section",
                    manual_review_required=True,
                    toc_level=chapter.level,
                )
            )
            break
        return plans

    def _apply_semantic_boundary_pass(self, plans: list[SlicePlan]) -> list[SlicePlan]:
        """对初稿切分点执行统一的 F3 语义校验。"""
        adjusted = [replace(plan, overlap_pages=list(plan.overlap_pages)) for plan in plans]
        for index in range(len(adjusted) - 1):
            current = adjusted[index]
            nxt = adjusted[index + 1]
            boundary = current.end_page
            original_next_start = nxt.start_page
            if boundary >= nxt.end_page:
                continue
            if self.analyzer.is_safe_split_boundary(boundary):
                continue
            if original_next_start in self.chapter_start_pages and boundary + 1 == original_next_start:
                continue

            lower_bound = current.start_page
            upper_bound = nxt.end_page - 1
            normal_upper_bound = min(current.start_page + self.hard_max_pages - 1, upper_bound)
            safe_boundary = self._find_nearest_safe_boundary(
                lower_bound,
                boundary,
                normal_upper_bound,
                prefer_forward=True,
            )
            if safe_boundary is None:
                safe_boundary = self._find_first_safe_boundary_forward(normal_upper_bound + 1, upper_bound)

            if safe_boundary is None:
                current.boundary_reason = "semantic_integrity"
                current.exception_type = current.exception_type or "oversized_semantic_block"
                current.manual_review_required = True
                continue

            current.end_page = safe_boundary
            nxt.start_page = safe_boundary + 1
            current.boundary_reason = "semantic_integrity"
            nxt.boundary_reason = "semantic_integrity"
            if current.actual_pages > self.hard_max_pages:
                current.exception_type = current.exception_type or "oversized_semantic_block"
                current.manual_review_required = True
        return adjusted

    def _find_nearest_safe_boundary(
        self,
        lower_bound: int,
        desired: int,
        upper_bound: int,
        prefer_forward: bool = False,
    ) -> int | None:
        if upper_bound < lower_bound:
            return None
        max_offset = max(desired - lower_bound, upper_bound - desired)
        for offset in range(max_offset + 1):
            backward = desired - offset
            forward = desired + offset
            if prefer_forward and offset > 0:
                if lower_bound <= forward <= upper_bound and self.analyzer.is_safe_split_boundary(forward):
                    return forward
                if lower_bound <= backward <= upper_bound and self.analyzer.is_safe_split_boundary(backward):
                    return backward
                continue
            if lower_bound <= backward <= upper_bound and self.analyzer.is_safe_split_boundary(backward):
                return backward
            if offset == 0:
                continue
            if lower_bound <= forward <= upper_bound and self.analyzer.is_safe_split_boundary(forward):
                return forward
        return None

    def _find_first_safe_boundary_forward(self, lower_bound: int, upper_bound: int) -> int | None:
        for page_number in range(lower_bound, upper_bound + 1):
            if self.analyzer.is_safe_split_boundary(page_number):
                return page_number
        return None

    def _inject_overlap_pages(self, plans: list[SlicePlan]) -> list[SlicePlan]:
        """在结构起始页或标题过渡页上注入双向重叠。"""
        adjusted = [replace(plan, overlap_pages=list(plan.overlap_pages)) for plan in plans]
        for index in range(len(adjusted) - 1):
            current = adjusted[index]
            nxt = adjusted[index + 1]
            if nxt.start_page <= current.end_page:
                continue

            candidate_page = nxt.start_page
            start_text = self.document.page_text(candidate_page)
            end_text = self.document.page_text(current.end_page)
            # 结构起始页优先重叠；若不是结构页，再退回到标题文本命中规则。
            should_overlap = candidate_page in self.chapter_start_pages or self._should_overlap(
                current.title,
                nxt.title,
                start_text,
                end_text,
            )
            if should_overlap:
                current.end_page = candidate_page
                nxt.start_page = candidate_page
                if candidate_page not in current.overlap_pages:
                    current.overlap_pages.append(candidate_page)
                if candidate_page not in nxt.overlap_pages:
                    nxt.overlap_pages.append(candidate_page)
                if current.actual_pages > self.hard_max_pages:
                    LOGGER.warning("Overlap injection expanded slice beyond hard max: %s", current.title)
                    current.exception_type = current.exception_type or "oversized_semantic_block"
                    current.manual_review_required = True
        return adjusted

    def _normalize_plan_flags(self, plans: list[SlicePlan]) -> list[SlicePlan]:
        normalized = [replace(plan, overlap_pages=list(plan.overlap_pages)) for plan in plans]
        # 某些切片在边界微调后会回到 25 页以内，需要把过期的超限标记清理掉。
        for plan in normalized:
            if plan.actual_pages <= self.hard_max_pages and plan.exception_type in OVERSIZED_EXCEPTIONS:
                plan.exception_type = None
                plan.manual_review_required = False
        return normalized

    @staticmethod
    def _should_overlap(current_title: str, next_title: str, next_page_text: str, current_page_text: str) -> bool:
        current_variants = SplitPlanner._title_tokens(current_title)
        next_variants = SplitPlanner._title_tokens(next_title)
        return any(token and token in next_page_text for token in current_variants) or any(
            token and token in current_page_text for token in next_variants
        )

    @staticmethod
    def _title_tokens(title: str) -> list[str]:
        tokens = [token.strip() for token in title.split(" + ")]
        filtered = []
        for token in tokens:
            if not token:
                continue
            if any(ord(char) > 127 for char in token):
                if len(token) >= 2:
                    filtered.append(token)
            elif len(token) >= 4:
                filtered.append(token)
        return filtered

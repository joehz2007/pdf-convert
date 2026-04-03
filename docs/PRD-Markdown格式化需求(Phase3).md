# 产品需求文档（PRD）：大型 PDF 转 MD 项目 - Phase 3（Markdown 格式化）

| 文档版本 | 作者 | 日期 | 状态 |
| :--- | :--- | :--- | :--- |
| **V1.0** | Codex 协作整理 | 2026-04-02 | 草稿（待评审） |

---

## 变更记录

| 版本 | 变更内容 |
| :--- | :--- |
| V1.0 | 基于 `docs/需求.txt`、Phase 2 技术方案与既有 Phase 3 技术方案，补齐 Phase 3 独立需求文档，明确完整性校对、格式修复、输出契约、NFR 与验收标准 |

---

## 1. 产品概述

### 1.1 项目背景
Phase 2 已能从切片 PDF 中提取 Markdown 草稿与结构化 `content.json`，但草稿结果仍可能存在标题层级不稳、列表格式混乱、表格渲染不一致、图片路径待清洗、以及块级遗漏风险。为了交付“可发布、可合并”的章节级 Markdown，需要在 Phase 3 中对草稿结果进行完整性对账与格式修复。

### 1.2 目标定义
本项目聚焦于 **PDF 转 Markdown 的第三阶段：Markdown 格式化与校对**。

其核心目标是：实现一个 **Python CLI 工具**，消费 Phase 2 输出的 `content.json`、`extract_manifest.json` 与资源文件，并可选读取 Markdown 草稿作为辅助提示，对每个切片执行**完整性对账、结构修复与样式标准化**，输出可直接进入 Phase 4 的最终版 Markdown、单切片 `review_report.json` 与全局 `format_manifest.json`。

> **关键约定**：Phase 3 的核心不是重新抽取 PDF 内容，也不是依赖 Phase 2 的 draft 直接做字符串修补，而是以 `content.json` 为事实基线构建中间表示，再确定性输出最终版 Markdown。若存在 Phase 2 draft，其作用仅限于辅助对照、调试或在少量信息缺失时提供弱提示。
>
> **职责边界**：Phase 3 不负责自由改写原文、不负责摘要或翻译、不负责 overlap 去重，这些能力要么不在本期范围，要么属于 Phase 4。

### 1.3 适用场景
- 将 Phase 2 输出的章节级 Markdown 草稿修复为统一、可发布的标准 Markdown。
- 对提取结果做块级完整性对账，减少正文、表格、代码、图片说明遗漏。
- 为 Phase 4 提供顺序稳定、路径稳定、质量状态明确的章节级最终 Markdown。

---

## 2. 系统阶段规划（Context）

- **Phase 1: PDF 结构化切分模块**：负责输出切片 PDF 与 `manifest.json`。
- **Phase 2: PDF 内容提取模块**：负责输出 `content.json`、`extract_manifest.json` 与资源文件，并可选输出 Markdown 草稿。
- **Phase 3: Markdown 格式化模块（当前范围）**：负责基于 `content.json` 的完整性对账、结构修复、样式标准化、校对报告与格式化清单输出。
- **Phase 4: 校验与拼接模块**：负责基于 Phase 2/3 追溯信息执行 overlap 去重与最终合并。

---

## 3. 功能需求（核心校对与格式化规则）

系统核心逻辑是一个以 **完整性优先、结构修复优先于美观、保留追溯结果** 为原则的格式化与审计链路。

### 3.1 规则优先级决策表

| 优先级 | 规则 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| **P0** | 校对结果必须可审计 | 硬约束 | 无论成功或失败，必须输出可追踪的校对状态与报告 |
| **P1** | 内容完整性优先于样式美观 | 硬约束 | 不得为了 Markdown 美观而删除、压缩或忽略原始有效内容 |
| **P2** | `content.json` 为事实基线 | 硬约束 | 完整性判断、缺失修复、风险提示必须以结构化内容为依据 |
| **P3** | 结构修复与样式标准化 | 强约束 | 需修复标题、列表、表格、代码块、图片引用等结构问题 |
| **P4** | 输出契约稳定 | 强约束 | 最终版 `.md`、`review_report.json`、`format_manifest.json` 必须稳定产出 |
| **P5** | overlap 不在本阶段去重 | 强约束 | Phase 3 可保留 overlap 内容与标记，但不得擅自跨切片删除 |

补充决策规则：

- 当“草稿可直接阅读”与“事实对账发现缺失”冲突时，必须优先相信 `content.json` 并修复缺失或提升人工复核标记。
- 对无法自动修复的问题，必须在 `review_report.json` 和 `format_manifest.json` 中记录，不得静默跳过。
- 对 Phase 2 已标记人工复核的切片，Phase 3 必须继承并保留风险状态。

### 功能1：消费 Phase 2 输出（F1 - Upstream Consumption）

- 系统必须读取 Phase 2 输出目录中的：
  - `extract_manifest.json`
  - `content.json`
  - `assets/`
- 若存在草稿 `.md`，可读取为辅助提示；若不存在，不得阻断主流程。
- 至少消费以下字段：
  - `extract_manifest.json`：`source_manifest`、`source_file`、`generator_version`、`total_slices`、`slices[].slice_file`、`slices[].content_file`、`slices[].md_file`、`slices[].status`、`slices[].manual_review_required`
  - `content.json`：`slice_file`、`display_title`、`start_page`、`end_page`、`source_pages[].source_page`、`source_pages[].is_overlap`、`source_pages[].blocks`、`source_pages[].tables`、`source_pages[].images`、`manual_review_required`、`warnings`

补充说明：

- `source_pages[].markdown` 若存在，可作为页级调试快照或辅助诊断信息消费；但它不是 Phase 3 正确性的硬前置字段，更不是事实判断的唯一依据。
- 对嵌套表格，`source_pages[].tables` 中应能提供父子引用关系和推荐渲染策略，供 Phase 3 优先输出纯 Markdown 结构。

### 功能2：完整性对账（F2 - Coverage Audit）

- 系统必须对“候选输出 Markdown / 最终输出 Markdown”与 `content.json` 的块级内容执行完整性对账。
- 至少应检测：
  - 块级内容缺失
  - 块级顺序明显错乱
  - overlap 页相关内容是否仍被保留
  - 表格、代码块、图片说明是否明显丢失
- 若存在 Phase 2 draft，可额外做差异比对，但该比对结果仅作为诊断信息，不得覆盖事实判断。
- 对账结论必须落入 `review_report.json`，并形成可供后续聚合的结构化问题列表。

### 功能3：结构修复（F3 - Structural Repair）

- 系统必须基于 `content.json` 构建规范化中间表示，并在该中间表示上执行结构修复，至少覆盖：
  - 标题层级与标题语法
  - 列表项与缩进
  - 代码块围栏
  - 表格结构
  - 图片引用与图注相邻性
  - 段落断裂、空行与常见 Markdown 语法问题
- 修复应以“尽量不改变原文内容”为前提，不得进行自由改写。
- 若存在 Phase 2 draft，可用于补充 heading level、代码 fence 等弱提示，但不得替代结构化事实。

### 功能4：样式标准化（F4 - Style Normalization）

- 系统必须将最终输出收敛为统一的 Markdown 书写风格。
- 标准化范围至少包括：
  - 标题与正文之间的空行规则
  - 列表和代码块的统一格式
  - 表格输出优先使用 GFM 兼容格式
  - 图片路径与链接路径规范化
- 对嵌套表格，优先使用子章节、列表、引用说明等纯 Markdown 结构表达父子关系。
- 无法稳定标准化的复杂结构可保留 warning 或截图回退，但不得直接删除；复杂 HTML 不是默认目标格式。

### 功能5：输出最终版 Markdown（F5 - Final Markdown Output）

- 每个成功处理的切片必须输出最终版 Markdown。
- 输出文件名应保持与切片 PDF 同名，便于 Phase 4 直接按顺序合并。
- 最终版 Markdown 必须：
  - 可直接阅读
  - 与 `content.json` 对账后无明显遗漏，或已标记人工复核
  - 保持切片级顺序稳定
  - 在无 draft 输入时仍可稳定生成

### 功能6：输出 `review_report.json` 与 `format_manifest.json`（F6 - Review and Task Manifests）

- 每个切片必须输出 `review_report.json`，至少包含：
  - `slice_file`
  - `final_md_file`
  - `status`
  - `manual_review_required`
  - `coverage`
  - `issues`
  - `warnings`
- 全局必须输出 `format_manifest.json`，至少包含：
  - `source_extract_manifest`
  - `source_file`
  - `created_at`
  - `generator_version`
  - `total_slices`
  - `slices[]`
- `slices[]` 中至少包含：
  - `slice_file`
  - `display_title`
  - `order_index`
  - `start_page`
  - `end_page`
  - `final_md_file`
  - `review_report_file`
  - `status`
  - `manual_review_required`

### 功能7：资源路径处理（F7 - Asset Path Stability）

- Phase 3 必须保证最终 Markdown 中的资源路径稳定可用。
- 支持两种模式：
  - `copy`：将 Phase 2 `assets/` 复制到 Phase 3 输出目录
  - `reuse_phase2`：复用 Phase 2 `assets/` 并改写为相对路径
- 当资源路径无法稳定解析时，必须在报告中记录 warning，必要时标记人工复核。

### 功能8：异常处理与人工复核（F8 - Review Escalation）

- 满足以下任一条件时，应标记 `manual_review_required=true`：
  - Phase 2 已标记人工复核
  - 对账发现缺失块但无法自动修复
  - 表格、代码、图片或路径问题可能影响可读性或后续合并
  - 上游切片 `status=failed`
- 对 `status=failed` 的上游切片，Phase 3 不得伪造成功结果，必须在 `format_manifest.json` 中记录为失败或跳过状态。

---

## 4. 非功能性需求（NFRs）

### 性能要求

- 标准测试环境建议定义为：**8 核 CPU、16GB RAM、SSD、本地文件系统、Windows 11 或同等级 Linux 环境**。
- 建议验收目标：
  - 单个 **20 页以内切片**的校对与格式化耗时控制在 **3 秒以内**。
  - 全量格式化耗时应明显低于 Phase 2 内容提取耗时。
- 日志至少输出以下阶段耗时：
  - `manifest_load_ms`
  - `normalize_ms`
  - `repair_ms`
  - `render_ms`
  - `audit_ms`
  - `write_ms`
  - `total_ms`

### 容错性

- 单切片失败不得导致整批格式化任务无法输出 `format_manifest.json`。
- 对结构异常、资源缺失、上游结果不完整等情况，系统必须输出明确问题记录。
- 对无法自动修复但又不应阻断整体任务的情况，应提升 `manual_review_required`，而不是中断所有切片处理。

### 鲁棒性

- 相同输入重复运行时，最终 Markdown 与报告结构应保持稳定。
- 最终 Markdown 文件名、切片顺序和资源路径策略必须稳定，便于 Phase 4 消费。
- 问题记录应结构化，便于测试、CI 或后续汇总统计。

### 部署形态

- **Python CLI 脚本**，直接在命令行中执行。
- 基础调用方式：`python phase3_format.py --input-dir <extract_dir> [--output-dir <dir>] [--workers N] [--copy-assets]`

---

## 5. 验收标准

1. 输入一个合法的 Phase 2 输出目录，系统能够逐切片输出最终版 `.md`、`review_report.json` 与全局 `format_manifest.json`。
2. 抽查任一切片，确认最终版 Markdown 在标题、列表、代码块、表格和图片引用方面明显优于 Phase 2 草稿，且不出现内容静默删减。
3. 抽查任一 `review_report.json`，确认包含完整性对账结果、问题列表、warning 和人工复核标记。
4. 对包含 overlap 页的切片，确认 Phase 3 保留 overlap 内容与相关标记，不提前执行跨切片去重。
5. 对图片资源采用 `copy` 或 `reuse_phase2` 两种模式时，确认最终 Markdown 中图片路径可解析且在报告中有明确记录。
6. 对上游 `status=failed` 或 `manual_review_required=true` 的切片，确认 Phase 3 继承并保留风险状态，不伪造完全成功结果。
7. 整批任务中若存在局部切片失败，仍能输出全局 `format_manifest.json` 并准确汇总成功、失败、跳过与人工复核状态。
8. `--help` 可用；非法路径、缺失 `content.json` 等场景有清晰错误提示；当草稿 `.md` 缺失但 `content.json` 完整时，主流程仍可继续。
9. 在约定测试环境下，单个 20 页以内切片的校对与格式化性能满足第 4 节定义的目标。

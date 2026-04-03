# 产品需求文档（PRD）：大型 PDF 转 MD 项目 - Phase 2（PDF 内容提取）

| 文档版本 | 作者 | 日期 | 状态 |
| :--- | :--- | :--- | :--- |
| **V1.0** | Codex 协作整理 | 2026-04-02 | 草稿（待评审） |

---

## 变更记录

| 版本 | 变更内容 |
| :--- | :--- |
| V1.0 | 基于 `docs/需求.txt`、Phase 1 PRD 以及既有 Phase 2 技术方案，补齐 Phase 2 独立需求文档，明确目标、边界、输出契约、NFR 与验收标准 |

---

## 1. 产品概述

### 1.1 项目背景
Phase 1 已将大型 PDF 按章节与语义边界切分为可独立处理的 PDF 切片。为了继续完成“大型 PDF 转 Markdown”主链路，需要在 Phase 2 中把每个切片中的正文、标题、列表、表格、代码、图片等内容提取为结构化结果与 Markdown 草稿，并为后续校对和合并阶段保留稳定的追溯信息。

### 1.2 目标定义
本项目聚焦于 **PDF 转 Markdown 的第二阶段：PDF 内容提取**。

其核心目标是：实现一个 **Python CLI 工具**，消费 Phase 1 输出的切片 PDF 与 `manifest.json`，针对**数字原生或具备可提取文本层的 PDF 切片**执行确定性内容提取，输出结构化 `content.json`、资源文件与全局 `extract_manifest.json`，并可选输出与切片 PDF 同名的 Markdown 草稿，供人工检查、调试与后续阶段辅助对照使用。

> **关键约定**：Phase 2 的职责是“提取”和“保留追溯”，不是做最终精排。`content.json` 才是下游正确性的事实契约；若输出 `.md`，其定位仅为 **draft（草稿）**，用于人工检查、调试和辅助对照，不作为 Phase 3 的权威事实输入。
>
> **OCR 边界**：本期 Phase 2 仍不建设 OCR 主链路，仅支持数字原生或具备可提取文本层的 PDF 切片。纯扫描 PDF、无有效文本层 PDF 统一视为不支持输入。

### 1.3 适用场景
- 将 Phase 1 输出的章节级 PDF 切片批量转换为 Markdown 草稿。
- 为后续完整性校对、格式修复、跨切片去重与合并提供块级追溯数据。
- 为图片、表格、代码块等复杂内容保留结构化落地结果，降低后续阶段的信息丢失风险。
- **Word 导出 PDF**：支持从 Microsoft Word 导出的 PDF，包括无边框/隐形线条表格、样式驱动的代码段、多级列表和带图号的图注。Word 导出 PDF 是主要输入来源之一，其表格线条、字体嵌入和缩进方式与数字原生 PDF 存在差异，需在表格检测、代码识别和图注绑定中针对性适配。

---

## 2. 系统阶段规划（Context）

本节用于明确 Phase 2 在整体链路中的位置，后续技术方案、任务拆解与测试计划统一以本 PRD 为准。

- **Phase 1: PDF 结构化切分模块**：负责按章节、页数和语义完整性输出切片 PDF 与 `manifest.json`。
- **Phase 2: PDF 内容提取模块（当前范围）**：负责从切片 PDF 中提取结构化内容、文档树和资源文件，输出 `content.json`、`assets/` 与 `extract_manifest.json`；Markdown 草稿仅为可选辅助产物。
- **Phase 3: Markdown 格式化模块**：负责基于 Phase 2 的结构化事实输出检查内容是否完整，修复结构与样式问题，输出最终版 Markdown 与校对报告。
- **Phase 4: 校验与拼接模块**：负责基于 Phase 2/3 保留下来的追溯信息执行 overlap 去重和最终 Markdown 合并。

---

## 3. 功能需求（核心提取规则）

系统核心逻辑是一个以 **完整提取、稳定追溯、失败隔离** 为原则的内容提取链路。具体规则如下。

### 3.1 规则优先级决策表

| 优先级 | 规则 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| **P0** | 全局任务必须完成汇总 | 硬约束 | 单切片失败不能导致整批任务无结果，必须输出 `extract_manifest.json` |
| **P1** | 内容完整性与顺序稳定 | 硬约束 | 不得随意丢失正文、标题、列表、表格、代码、图片引用等可提取内容 |
| **P2** | 结构化追溯信息完整 | 硬约束 | 必须输出页级、块级、重叠页、资源和文档结构等后续阶段依赖的数据 |
| **P3** | 文档树与专门能力独立可验证 | 强约束 | 文档结构、复杂表格、代码块、图片图注等能力必须可独立测试和演进 |
| **P4** | Markdown 草稿仅为辅助产物 | 强约束 | 若输出同名 `.md`，其默认用于人工检查和调试，不得成为下游正确性的唯一依据 |
| **P5** | 复杂内容保守降级 | 强约束 | 复杂表格、图片、代码等无法完美提取时，应优先保留结构关系、Markdown 表达和 warning，不得静默丢失 |
| **P6** | 不支持输入与异常隔离 | 强约束 | 对纯扫描或损坏切片，应明确记录失败原因并继续处理其他切片 |

补充决策规则：

- 当“Markdown 美观性”与“内容不遗漏”冲突时，以“不遗漏”优先。
- 当某类复杂块无法完美转成标准 Markdown 时，优先保留原始信息、结构关系、截图或告警，而不是直接丢弃。
- 对嵌套表格，默认目标不是生成复杂 HTML，而是先识别父子表关系，再尽量用章节/子章节、列表、引用说明等纯 Markdown 结构表达。
- overlap 页内容必须保留在结果中，不在 Phase 2 进行跨切片去重。
- 任一切片即使失败，也必须在 `extract_manifest.json` 中写入状态、错误原因与人工复核标记。

### 功能1：消费 Phase 1 切片输入（F1 - Slice Input Consumption）

- 系统必须读取 Phase 1 输出目录中的 `manifest.json` 与切片 PDF。
- 至少消费以下字段：
  - `source_file`
  - `total_pages`
  - `fallback_level`
  - `slices[].slice_file`
  - `slices[].start_page`
  - `slices[].end_page`
  - `slices[].overlap_pages`
  - `slices[].display_title`
  - `slices[].manual_review_required`
- 切片处理顺序默认按 `manifest.json` 中切片顺序执行，以便后续阶段恢复章节顺序。

### 功能2：切片级确定性内容提取（F2 - Deterministic Extraction）

- 系统必须针对每个切片提取可见正文与结构化内容，至少覆盖：
  - 标题
  - 段落
  - 列表
  - 表格
  - 代码块
  - 图片及图片引用
- 提取结果必须尽量保持原始阅读顺序，避免明显错位、乱序和大段遗漏。
- 对于可提取的文本层内容，不得仅输出图片占位而省略文本正文。
- 对于 overlap 页，必须保留 `is_overlap` 标记，供 Phase 4 去重使用。

### 功能3：文档结构建模与专门能力模块（F3 - Structured Extraction Capabilities）

- 系统必须把 PDF 视为“具有章节和块级层次的文档树”，而不是纯文本流。
- `content.json` 与 `extract_manifest.json` 必须配合记录：
  - 全局文档结构
  - 切片与章节节点映射关系
  - 单切片内 section tree / block tree
- 为保证复杂场景可测、可演进，Phase 2 至少应具备以下独立能力模块：
  - 文档结构模块：负责章节、标题层级、段落归属和 section tree 建模
  - 表格提取模块：负责复杂表格、嵌套表格、跨页表格的独立处理，并显式识别表格父子关系
  - 代码块提取模块：负责代码区域识别、边界保留、语言候选与 fenced code 友好输出
  - 资源模块：负责图片导出、图注绑定与资源路径生成

### 功能4：可选输出同名 Markdown 草稿（F4 - Optional Draft Markdown Output）

- 系统可以输出与切片 PDF 同名的 Markdown 草稿文件，建议默认开启，并允许通过显式参数关闭。
- Markdown 草稿需满足：
  - 基本可读
  - 章节标题与正文顺序可辨识
  - 表格、代码块、图片引用尽量以 Markdown 形式表达
  - 无法完美表达时可保守回退，但不得静默丢失内容
- 草稿输出仅承担“人工检查 / 调试 / 辅助对照”职责，不承担下游权威事实契约，也不承担最终发布排版职责。

### 功能5：输出结构化 `content.json`（F5 - Structured Content Output）

- 每个成功切片必须输出 `content.json`，作为 Phase 2 的规范化事实输出。
- `content.json` 至少应包含：
  - 切片元数据：`slice_file`、`display_title`、`start_page`、`end_page`
  - 文档结构：`document_outline`、`sections`
  - 章节映射：`section_refs`，用于表达“当前切片覆盖了哪些章节节点 / 节点区间”
  - 页级信息：`source_pages[].source_page`、`slice_page`、`is_overlap`
  - Markdown 快照：`source_pages[].markdown`（建议保留，用于调试和人工抽查；不是下游事实判断的唯一依据）
  - 块级信息：`source_pages[].blocks`
  - 表格信息：`source_pages[].tables`（对嵌套表格至少应能表达 `table_kind`、父子引用关系和推荐渲染策略）
  - 图片信息：`source_pages[].images`
  - 风险信息：`manual_review_required`、`warnings`
- `content.json` 中的页码口径需与 Phase 1 `manifest.json` 保持一致，对用户可见页码采用 **1-based 物理页码**。

### 功能6：复杂内容与资源输出（F6 - Complex Content and Assets）

- 对于图片资源，系统必须导出到切片目录下的 `assets/` 子目录，并在 Markdown 与结构化数据中写入可用引用路径。
- 对于表格，系统应优先输出 Markdown 表格。
- 对于嵌套表格，系统必须先识别其“父表 -> 子表”关系，并优先采用以下表达策略：
  - 外层表保留为 GFM 表格或等价 Markdown 概览表
  - 内层子表提升为紧邻的子章节、列表或引用块
  - 在父表对应行/单元格与子表之间写入可追溯的引用说明
- 若嵌套表格无法稳定映射为纯 Markdown，系统应优先保留结构化关系和 warning，再考虑截图回退；复杂 HTML 不是默认目标产物。
- 对于代码块，应尽量保留换行与缩进结构；若语言未知，可不标注 language，但不得将整段代码压平成普通段落。
- 对于 Word 导出 PDF 中的代码段（通过样式或等宽字体标记而非文本框），应结合字体特征和 bbox 缩进信号综合判断，避免因字体嵌入子集化或使用比例字体而漏检。
- 对于图注、表注等复合内容，应尽量与对应图片或表格保持相邻。
- 图注绑定应优先匹配带有图号模式的文本（如"图 X-X"、"Figure X"），不仅限于图片下方、也应检查图片上方的候选文本。

### 功能7：输出全局 `extract_manifest.json`（F7 - Task Manifest）

- Phase 2 必须为整批任务输出一个全局 `extract_manifest.json`。
- 推荐目录结构如下：

```text
<源文件名>_extract/
  extract_manifest.json
  001-第一章-系统概述/
    source.pdf
    content.json
    第一章 系统概述（1-18）.md
    assets/
  002-第二章-架构设计/
    ...
```

- `extract_manifest.json` 至少应包含：
  - `source_manifest`
  - `source_file`
  - `created_at`
  - `generator_version`
  - `document_outline`
  - `total_slices`
  - `slices[]`
- `slices[]` 中至少应包含：
  - `order_index`
  - `slice_file`
  - `content_file`
  - `section_refs`
  - `md_file`（可为 `null`）
  - `emit_draft_md`
  - `status`
  - `error_message`
  - `manual_review_required`
- `status` 推荐枚举：
  - `success`
  - `failed`
  - `unsupported_input`

### 功能8：异常处理与人工复核标记（F8 - Failure Isolation and Review Flag）

- 满足以下任一条件时，切片应标记 `manual_review_required=true`：
  - 上游 Phase 1 已标记人工复核
  - 表格、代码、图片或页级顺序存在明显不确定性
  - 提取结果出现重要 warning，可能影响后续校对或合并
- 对不支持输入，系统必须：
  - 明确记录失败原因
  - 不生成伪成功的 `.md` 或 `content.json`
  - 继续处理其他切片
  - 在 `extract_manifest.json` 中保留该切片状态

---

## 4. 非功能性需求（NFRs）

### 性能要求

- 标准测试环境建议定义为：**8 核 CPU、16GB RAM、SSD、本地文件系统、Windows 11 或同等级 Linux 环境**。
- 建议验收目标：
  - 平均每个 **20 页以内切片**在 **5 秒以内**完成提取与写盘。
  - 支持多切片并行处理。
- 日志至少输出以下阶段耗时：
  - `manifest_load_ms`
  - `precheck_ms`
  - `markdown_extract_ms`
  - `metadata_build_ms`
  - `write_ms`
  - `total_ms`

### 容错性

- 单切片失败不得导致整批任务崩溃退出。
- 对损坏 PDF、加密 PDF、空切片目录、缺失 `manifest.json` 等情况，系统必须给出明确错误信息。
- 输出目录中不得出现“无状态文件”，即每个切片要么完整成功，要么在清单中明确失败。

### 鲁棒性

- 输出文件命名、路径写入和资源目录结构必须稳定，供后续 Phase 3/4 直接消费。
- 对同一输入重复执行时，结果结构应保持可预测，不得随机变更目录组织与字段命名。
- 块级、页级和资源级追溯信息命名应稳定，便于后续测试与去重逻辑复用。

### 部署形态

- **Python CLI 脚本**，直接在命令行中执行。
- 基础调用方式：`python phase2_extract.py --input-manifest <manifest.json> [--output-dir <dir>] [--workers N]`

---

## 5. 验收标准

1. 输入一个合法的 Phase 1 输出目录，系统能够逐切片输出 `content.json`、`assets/` 与全局 `extract_manifest.json`；若开启草稿输出，还应生成同名 `.md`。
2. 抽查任一成功切片的 `content.json`，确认包含页级来源、块级结构、section tree、重叠页标记与 warning 字段，可供 Phase 3 做完整性对账。
3. 抽查 `extract_manifest.json`，确认能够表达全局文档树、切片顺序和切片与章节节点的映射关系。
4. 输入包含 overlap 页的切片，确认提取结果保留 overlap 内容，并在结构化输出中标记 `is_overlap=true`。
5. 输入包含图片的切片，确认 `assets/` 目录存在且结构化数据中的路径可被后续阶段使用。
6. 输入包含复杂表格、嵌套表格、跨页表格和示例代码的切片，确认表格模块、代码块模块能独立产出稳定结果或明确回退信息。
7. 输入包含嵌套表格的切片，确认 `content.json` 中能表达父表、子表、引用说明和推荐渲染策略，且默认优先指向纯 Markdown 表达而不是复杂 HTML。
8. 输入纯扫描或无有效文本层切片，系统不得伪造成功结果，必须在 `extract_manifest.json` 中明确写入失败或不支持状态。
9. 对单个切片故障场景，整批任务仍能完成并输出全局 `extract_manifest.json`。
10. `--help` 可用；非法路径、缺失输入、非法参数时有清晰错误提示。
11. 在约定测试环境下，平均每个 20 页以内切片的提取与写盘性能满足第 4 节定义的目标。
12. 输入 Word 导出的 PDF 切片（含无边框表格、代码段、带图号图注），确认表格回退到 `text` 策略后可提取、代码段可被识别为 code 类型、图注可正确绑定。
13. 抽查 `content.json`，确认 `document_outline` 字段包含切片内的标题层级树，且 `section_id` 和 `parent_id` 关系正确。

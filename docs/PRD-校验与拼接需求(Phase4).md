# 产品需求文档（PRD）：大型 PDF 转 MD 项目 - Phase 4（校验与拼接）

| 文档版本 | 作者 | 日期 | 状态 |
| :--- | :--- | :--- | :--- |
| **V1.0** | Codex 协作整理 | 2026-04-02 | 草稿（待评审） |

---

## 变更记录

| 版本 | 变更内容 |
| :--- | :--- |
| V1.0 | 基于 `docs/需求.txt`、Phase 3 技术方案与既有 Phase 4 技术方案，补齐 Phase 4 独立需求文档，明确全局校验、overlap 去重、资源重写、输出契约、NFR 与验收标准 |

---

## 1. 产品概述

### 1.1 项目背景
Phase 3 已生成章节级最终版 Markdown，但由于 Phase 1 的切片策略会在章节切换页保留 overlap 内容，最终交付前仍需要一个全局阶段来恢复章节顺序、识别重叠内容、去除重复块、重写资源路径，并输出整本书或整份文档的单文件 Markdown 结果。

### 1.2 目标定义
本项目聚焦于 **PDF 转 Markdown 的第四阶段：全局校验与 Markdown 合并**。

其核心目标是：实现一个 **Python CLI 工具**，消费 Phase 3 输出的最终版 Markdown、`review_report.json` 与 `format_manifest.json`，按章节顺序对所有切片执行**全局校验、相邻 overlap 去重、资源路径重写与最终拼接**，输出 `<源文件名>.md`、`merge_report.json` 与 `merge_manifest.json`。

> **关键约定**：Phase 4 不是重新抽取 PDF 内容，也不是再次做 Markdown 精排，而是基于前 3 个阶段已经建立的追溯信息，把章节级结果收敛为**可交付、可追溯、可复核的单文件 Markdown**。
>
> **去重边界**：Phase 4 仅对**相邻切片间由 overlap 引入的重复内容**执行确定性去重，不对全书任意相似文本做泛化去重，避免误删合法重复段落。

### 1.3 适用场景
- 将章节级最终 Markdown 合并为整本书或整份文档的单文件输出。
- 基于页级、块级和 overlap 标记执行可解释的跨切片去重。
- 收敛资源目录与路径，输出便于交付和归档的最终 Markdown 结果。

---

## 2. 系统阶段规划（Context）

- **Phase 1: PDF 结构化切分模块**：负责输出切片 PDF 与 overlap 页信息。
- **Phase 2: PDF 内容提取模块**：负责输出块级追溯数据、图片资源与 `dedupe_key` 等基础元数据。
- **Phase 3: Markdown 格式化模块**：负责输出章节级最终 Markdown、`review_report.json` 与 `format_manifest.json`。
- **Phase 4: 校验与拼接模块（当前范围）**：负责全局校验、overlap 去重、资源重写、单文件合并与全局报告输出。

---

## 3. 功能需求（核心校验与拼接规则）

系统核心逻辑是一个以 **顺序正确、去重可证明、资源可交付、结果可审计** 为原则的全局合并链路。

### 3.1 规则优先级决策表

| 优先级 | 规则 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| **P0** | 最终结果必须可审计 | 硬约束 | 无论成功或失败，都必须输出 `merge_report.json` 与 `merge_manifest.json` |
| **P1** | 正确性优先于激进去重 | 硬约束 | 宁可保留可疑重复，也不得误删合法正文 |
| **P2** | 仅对相邻 overlap 内容去重 | 硬约束 | 去重范围必须受上游追溯信息约束，避免全局误删 |
| **P3** | 章节顺序与结构稳定 | 强约束 | 合并顺序必须与上游切片顺序一致 |
| **P4** | 资源路径可交付 | 强约束 | 最终 Markdown 中的图片等资源路径必须可解析、可分发 |
| **P5** | 风险继承与人工复核 | 强约束 | 上游风险或本阶段不确定项必须显式写入报告与清单 |

补充决策规则：

- 当纯文本相似度判断与上游 `dedupe_key` / `is_overlap` / `source_page` 冲突时，优先以上游结构化追溯信息为准。
- 对无法确定是否重复的块，应保守保留并标记人工复核，而不是直接删除。
- 若资源复制或路径改写失败导致最终 Markdown 出现不可恢复断链，可升级为致命错误；若仍可交付但存在风险，则标记人工复核。

### 功能1：消费 Phase 3 输出（F1 - Upstream Consumption）

- 系统必须读取 Phase 3 输出目录中的：
  - `format_manifest.json`
  - 最终版 `.md`
  - `review_report.json`
  - `assets/`
- 至少消费以下字段：
  - `format_manifest.json`：`source_extract_manifest`、`source_file`、`generator_version`、`total_slices`、`slices[].slice_file`、`slices[].display_title`、`slices[].order_index`、`slices[].start_page`、`slices[].end_page`、`slices[].final_md_file`、`slices[].review_report_file`、`slices[].status`、`slices[].manual_review_required`
  - `review_report.json`：`slice_file`、`final_md_file`、`status`、`manual_review_required`、`coverage.overlap_pages_expected`、`coverage.overlap_pages_matched`、`issues`、`warnings`

### 功能2：章节顺序恢复与合并前校验（F2 - Ordering and Preconditions）

- 系统必须按 `order_index` 或等价顺序字段恢复章节级切片顺序。
- 合并前必须校验：
  - 切片顺序是否连续且稳定
  - 是否存在上游失败切片
  - 是否存在关键资源缺失
  - 是否存在必须阻断的人工复核状态
- 若不满足合并前提，必须在报告中明确阻断原因。

### 功能3：基于追溯信息的 overlap 去重（F3 - Deterministic Overlap Resolution）

- Phase 4 必须基于 Phase 1/2/3 传递下来的追溯信息识别相邻切片重叠内容。
- 去重时优先使用：
  - `dedupe_key`
  - `is_overlap`
  - `source_page`
  - 块类型
- 仅在结构化信息不足时，才允许退化到 `normalized_text_hash` 或等价纯文本哈希。
- 去重结果必须可追溯，可在 `merge_report.json` 中说明：
  - 哪些块被视为 overlap 重复
  - 删除依据是什么
  - 删除发生在哪两个相邻切片之间

### 功能4：最终 Markdown 拼接（F4 - Final Stitching）

- 系统必须将所有可合并切片按章节顺序拼接为单文件 Markdown。
- 合并过程中应保持：
  - 章节顺序稳定
  - 单切片内部结构不被重新打乱
  - 标题衔接自然，不重复插入无必要的封面或目录页
- 合并后的输出文件命名为：`原文件名.md`。

### 功能5：资源路径重写与交付目录收敛（F5 - Asset Relinking）

- 最终 Markdown 中引用的资源路径必须在交付目录中可用。
- 默认推荐：
  - 将资源复制到 Phase 4 输出目录中
  - 采用避免重名冲突的目录结构，例如按章节子目录归档
- 若用户关闭资源复制，可允许改写为相对指向 Phase 3 目录，但此模式不推荐作为最终交付模式。
- `merge_report.json` 中应记录资源重写前后映射关系。

### 功能6：输出 `merge_report.json` 与 `merge_manifest.json`（F6 - Global Reporting）

- Phase 4 必须输出：
  - `<源文件名>.md`
  - `merge_report.json`
  - `merge_manifest.json`
- `merge_report.json` 至少应包含：
  - 全局状态
  - 去重统计
  - 资源重写结果
  - warnings
  - issues
  - `manual_review_required`
- `merge_manifest.json` 至少应包含：
  - `source_file`
  - `created_at`
  - `generator_version`
  - `status`
  - `manual_review_required`
  - `merged_md_file`
  - `report_file`
  - `slices[]`

### 功能7：异常处理与人工复核（F7 - Review Escalation and Blocking）

- 满足以下任一条件时，最终结果应标记 `manual_review_required=true`：
  - 上游任一切片已标记人工复核
  - overlap 去重存在不确定性
  - 资源路径改写存在风险
  - 合并前校验发现局部缺失但未阻断整体输出
- 满足以下任一条件时，应阻断最终合并成功状态：
  - 上游关键切片失败且无法跳过
  - 资源断链导致最终 Markdown 不可用
  - 章节顺序无法恢复
  - 输出文件无法完整写出

---

## 4. 非功能性需求（NFRs）

### 性能要求

- 标准测试环境建议定义为：**8 核 CPU、16GB RAM、SSD、本地文件系统、Windows 11 或同等级 Linux 环境**。
- 建议验收目标：
  - 单本 **1000 页以内文档**的 Markdown 合并在 **10 秒以内**完成。
  - overlap 去重与资源重写应明显快于 Phase 2 提取和 Phase 3 格式化。
- 日志至少输出以下阶段耗时：
  - `manifest_load_ms`
  - `provenance_load_ms`
  - `overlap_resolve_ms`
  - `asset_relink_ms`
  - `stitch_ms`
  - `postcheck_ms`
  - `write_ms`
  - `total_ms`

### 容错性

- 局部切片风险不得导致报告缺失；即使最终失败，也必须产出 `merge_report.json` 与 `merge_manifest.json`。
- 去重、资源复制、路径改写等步骤必须有明确错误与 warning 记录。
- 不得在无追溯依据的情况下进行激进去重。

### 鲁棒性

- 相同输入重复运行时，章节顺序、去重决策和资源路径组织应保持稳定。
- 去重与资源重写必须可追溯，便于人工复核与测试验证。
- 输出目录结构应便于交付、归档与再次审查。

### 部署形态

- **Python CLI 脚本**，直接在命令行中执行。
- 基础调用方式：`python phase4_merge.py --input-dir <format_dir> [--output-dir <dir>] [--copy-assets]`

---

## 5. 验收标准

1. 输入一个合法的 Phase 3 输出目录，系统能够按章节顺序输出最终单文件 Markdown、`merge_report.json` 与 `merge_manifest.json`。
2. 对存在 overlap 页的相邻切片，确认重复内容被确定性识别并去重，且报告中可追溯去重依据。
3. 对自然重复但不属于 overlap 的正文内容，确认系统不会误删。
4. 抽查最终 Markdown，确认章节顺序与上游一致，切片内部结构未被打乱，输出文件名为 `原文件名.md`。
5. 抽查资源输出，确认最终 Markdown 中的图片等资源路径可解析，且 `merge_report.json` 中记录了资源重写结果。
6. 对上游存在 `manual_review_required=true` 的切片，确认 Phase 4 继承并保留风险状态，不伪造完全成功的交付结论。
7. 对关键上游切片失败、资源断链或顺序无法恢复等阻断场景，确认系统明确失败并在报告中输出原因。
8. `--help` 可用；非法路径、缺失 `format_manifest.json`、缺失必要章节文件等场景有清晰错误提示。
9. 在约定测试环境下，单本 1000 页以内文档的合并性能满足第 4 节定义的目标。

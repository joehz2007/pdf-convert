# 技术实施方案 (Implementation Plan)：大型 PDF 转 MD 项目 - Phase 3

## 1. 目标与范围

基于 [PRD-Markdown格式化需求(Phase3).md](D:\projects01\pdf-convert\docs\PRD-Markdown格式化需求(Phase3).md)、[技术方案-PDF内容提取(Phase2).md](D:\projects01\pdf-convert\docs\技术方案-PDF内容提取(Phase2).md) 以及 [需求.txt](D:\projects01\pdf-convert\docs\需求.txt) 中已经冻结的上下游契约，Phase 3 的职责应收敛为：

- 消费 Phase 2 输出的 `content.json`、`extract_manifest.json`、`assets/`，并可选读取草稿 Markdown 作为辅助提示
- 对每个章节级切片执行**完整性对账**
- 对基于 `content.json` 构建的中间表示执行**结构修复与样式标准化**
- 产出可直接进入 Phase 4 合并的**最终版 Markdown**
- 输出校对报告与全局 `format_manifest.json`，保留问题追踪与人工复核标记

本阶段的核心目标不是“重新生成 Markdown”，也不是对 Phase 2 的 draft 做字符串级修补，而是以 `content.json` 为事实基线，构建中间表示后**确定性输出最终 Markdown**。为满足“内容完整、没有遗漏”的要求，Phase 3 必须以 `content.json` 为事实基线，而不是仅依赖 Markdown 文本本身做格式美化。

### 本期范围

- 支持：Phase 2 已成功提取的数字原生/可提取文本层 PDF 切片结果
- 支持：标题、段落、列表、表格、代码块、图片引用、图注、重叠页标记的校对与格式修复
- 支持：最终版 Markdown 写出、校对报告写出、全局格式化清单写出
- 不支持：人工语义润色、改写原文、翻译、摘要、知识补全
- 不支持：脱离 Phase 2 的孤立 `.md` 文件直接格式化

---

## 2. 阶段边界

为避免与上下游重复建设，边界固定如下：

### Phase 2：内容提取

- 从 PDF 中提取可追溯内容
- 可选生成草稿版 Markdown 作为人工检查产物
- 输出 `content.json` 作为结构化事实来源
- 输出 `extract_manifest.json` 作为任务级清单

### Phase 3：Markdown 格式化

- 基于 `content.json` 检查候选输出 Markdown 是否完整、是否遗漏块级内容
- 修正 Markdown 结构错误和样式不一致问题
- 基于 `content.json` 对缺失块、错位块、格式异常块做确定性修复
- 若存在 draft Markdown，仅将其作为 heading level、代码 fence 等弱提示来源
- 输出最终版 Markdown 与格式化报告

### Phase 4：校验与拼接

- 按章节顺序合并 Phase 3 最终版 Markdown
- 基于 Phase 3/Phase 2 的可追溯信息处理重叠页去重
- 输出整本书或整份文档的最终单文件 Markdown

### 结论

Phase 3 不负责重新抽取 PDF 内容，也不负责自由改写文本，而是负责把 Phase 2 的 `content.json` 收敛为**可发布、可追溯、可合并**的标准 Markdown。若存在 draft，则仅作为辅助对照，不作为事实源。

---

## 3. 输入输出定义

### 3.1 输入

Phase 3 以 Phase 2 输出目录为输入，最小输入集如下：

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

#### `extract_manifest.json` 最低依赖字段

- `source_manifest`
- `source_file`
- `generator_version`
- `total_slices`
- `slices[].slice_file`
- `slices[].content_file`
- `slices[].md_file`
- `slices[].status`
- `slices[].manual_review_required`

> 说明：`slices[].md_file` 可以存在，但仅表示 Phase 2 是否额外输出了草稿 Markdown。Phase 3 的正确性不应建立在该文件必须存在之上。

#### `content.json` 最低依赖字段

- `slice_file`
- `display_title`
- `start_page`
- `end_page`
- `source_pages[].source_page`
- `source_pages[].slice_page`
- `source_pages[].is_overlap`
- `source_pages[].blocks`
- `source_pages[].tables`
- `source_pages[].images`
- `manual_review_required`
- `warnings`

补充说明：

- `source_pages[].markdown` 若存在，可作为调试快照或辅助提示读取；若缺失，不应阻断 `content.json`-first 的主流程。

### 3.2 输出

建议输出目录：

```text
<源文件名>_format/
  format_manifest.json
  001-第一章-系统概述/
    第一章 系统概述（1-18）.md
    review_report.json
    assets/
  002-第二章-架构设计/
    ...
```

#### 输出文件说明

- `同名 .md`：Phase 3 最终版 Markdown，供 Phase 4 合并
- `review_report.json`：单切片校对结果、修复动作、异常与人工复核结论
- `assets/`：复制或复用 Phase 2 资源目录，保证 Markdown 相对路径稳定
- `format_manifest.json`：全局执行清单、统计信息、失败与复核汇总

### 3.3 设计原则

- 最终 Markdown 文件名保持与切片 PDF 同名，便于 Phase 4 直接按顺序合并
- 资源路径优先保持与 Phase 2 一致，避免 Phase 3 修改图片引用语义
- 不覆盖 Phase 2 draft，避免丢失原始提取结果

---

## 4. 系统架构与主流程

### 4.1 架构概览

```text
Phase2 extract_manifest.json + content.json + assets + optional draft .md
        ↓
Phase3 CLI Orchestrator
        ↓
Manifest Loader / Precheck
        ↓
NormalizedDocument Builder
        ↓
Coverage Auditor
        ↓
Optional Draft Hint Resolver
        ↓
Repair Engine
        ↓
Markdown Renderer / Formatter
        ↓
Post-Render Verifier
        ↓
final .md + review_report.json + format_manifest.json
```

### 4.2 主流程

1. 读取 `extract_manifest.json`，构建 `FormatTask` 列表。
2. 校验切片目录、`content.json`、`assets/` 是否存在且相互匹配；若存在 draft Markdown，则登记为辅助输入。
3. 基于 `content.json` 建立**内容覆盖台账**，统计页、块、表格、图片和 overlap 页的期望覆盖范围。
4. 由 `content.json` 构建规范化文档中间表示 `NormalizedDocument`。
5. 若存在 draft Markdown，则解析其 token 流并提取 heading level、代码 fence、局部排版等弱提示。
6. 将弱提示与 `content.json` 结合，输出审计结论：缺失块、重复块、标题层级异常、列表断裂、未闭合代码块、表格损坏、图片路径失效等。
7. 按规则执行修复，更新 `NormalizedDocument`。
8. 由 `renderer.py` 将 `NormalizedDocument` 渲染为候选 Markdown。
9. 由 `md_normalizer.py` 调用 `mdformat + mdformat-gfm` 做样式标准化。
10. 执行二次校验，确认标准化后无新增遗漏、无结构破坏。
11. 写出最终 `.md`、`review_report.json`、`format_manifest.json`。

---

## 5. 技术选型

### 5.1 核心组件

- **Python 3.10+**：CLI 与数据编排
- **markdown-it-py**：使用 `MarkdownIt("gfm-like")` 解析 Markdown，提供稳定 token 流并显式支持表格语法
- **mdformat**：对 Markdown 做幂等化样式格式化
- **mdformat-gfm**：为 `mdformat` 补充 GFM 表格等扩展支持
- **Phase 2 `content.json`**：完整性对账的唯一事实来源
- **标准库 `difflib` / `re` / `unicodedata` / `json`**：文本归一化、模糊对齐、规则修复

以上外部依赖需在 `requirements.txt` 中**显式锁定版本**，避免 Markdown 解析与格式化结果随上游版本漂移。

### 5.2 选型理由

#### 为什么必须保留 `content.json` 作为基线

仅对 Markdown 文本做 parser + formatter，只能解决语法和样式问题，无法证明“没有遗漏内容”。Phase 3 的验收目标里，“完整性”比“格式统一”优先级更高，因此必须以 `content.json` 的页级和块级数据做对账。

#### 为什么使用 `markdown-it-py`

- 能稳定产出 token 流，便于识别标题、列表、代码块、表格、图片和受控扩展块
- 适合做“先解析、后修复、再渲染”的确定性流水线
- 便于在修复后重新解析，做二次校验
- 必须显式使用 `gfm-like` 预设；若使用默认 `commonmark` 预设，pipe table 会被当作普通文本，无法满足 Phase 3 的表格对账要求

#### 为什么使用 `mdformat`

- 负责最后一步样式标准化，降低格式差异
- 适合作为**渲染后整理器**，而不是完整性修复器
- 可统一标题、空行、列表缩进、fence 风格等输出细节
- 对表格场景需配合 `mdformat-gfm`，否则不应假定 pipe table 能被稳定格式化

### 5.3 输出语法基线

Phase 3 统一采用：

- **CommonMark 作为基础语法**
- **GFM 风格管道表格作为简单表格默认表现**
- 对嵌套表格优先使用“概览表 + 子章节/引用说明”的纯 Markdown 表达
- 对确实无法稳定表达的复杂表格，保留图片回退并提升人工复核

统一规则建议如下：

- 标题统一为 ATX 风格：`#` / `##` / `###`
- 代码块统一为 fenced code block
- 列表统一缩进风格，不保留随机混用的制表符和空格
- 简单表格统一为 pipe table
- 嵌套表格优先重组为“概览表 + 子章节/列表 + 引用说明”
- 复杂表格必要时引用 Phase 2 导出的截图

---

## 6. 数据模型设计

本节的数据模型统一落地到 `src/md_format/contracts.py`，避免散落在多个模块中。

### 6.1 任务模型

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FormatTask:
    slice_file: str
    display_title: str
    order_index: int
    input_dir: Path
    content_file: Path
    draft_md_file: Path | None
    assets_dir: Path
    phase2_manual_review_required: bool
```

### 6.2 审计问题模型

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class AuditIssue:
    issue_type: str
    severity: Literal["error", "warning", "info"]
    source_page: int | None
    reading_order: int | None
    node_ref: str | None
    message: str
    auto_fixable: bool
```

`node_ref` 生成规则：

- 普通文本/标题/列表/代码块：直接使用 Phase 2 的 `dedupe_key`
- 表格节点：使用 `table:{source_page}:{local_index}`
- 图片节点：使用 `image:{source_page}:{local_index}`
- 仅页级问题：`node_ref = null`

`severity` 枚举约定：

- `error`：必须修复，或最终升级为人工复核
- `warning`：允许自动修复，但需要保留痕迹
- `info`：仅记录，不影响切片最终状态

建议 `issue_type` 枚举：

- `missing_block`
- `duplicate_block`
- `heading_level_invalid`
- `list_broken`
- `code_fence_unclosed`
- `table_render_failed`
- `image_reference_missing`
- `overlap_lost`
- `asset_not_found`
- `format_parse_unstable`

### 6.3 规范化中间模型

`NormalizedDocument` 是 `repair_engine.py` 的输出、`renderer.py` 的输入，也是 Phase 3 的核心中间表示。

```python
from dataclasses import dataclass, field

@dataclass
class NormalizedBlock:
    block_type: str
    source_page: int
    reading_order: int
    node_ref: str | None
    markdown: str
    is_overlap: bool
    repaired: bool = False
    repair_actions: list[str] = field(default_factory=list)

@dataclass
class NormalizedPage:
    source_page: int
    slice_page: int
    is_overlap: bool
    blocks: list[NormalizedBlock]

@dataclass
class NormalizedDocument:
    slice_file: str
    display_title: str
    order_index: int
    start_page: int
    end_page: int
    pages: list[NormalizedPage]
    warnings: list[str]
    phase2_manual_review_required: bool
    phase3_manual_review_required: bool
    metadata: dict
```

字段约束：

- `pages` 必须按 `source_page ASC` 排序
- `blocks` 必须按 `reading_order ASC` 排序
- `metadata` 至少包含 `source_file`、`content_file`、`draft_md_file`、`asset_mode`

### 6.4 输出结果模型

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class FormatResult:
    slice_file: str
    final_md_file: str
    review_report_file: str
    status: Literal["success", "failed", "skipped_upstream_failed"]
    warning_count: int
    issue_count: int
    auto_fixed_count: int
    manual_review_required: bool
    elapsed_ms: int
```

`status` 枚举约定：

- `success`：当前切片已成功完成格式化并写出最终结果
- `failed`：当前切片在 Phase 3 内部失败，未产出可用最终结果
- `skipped_upstream_failed`：由于 Phase 2 上游切片失败，Phase 3 跳过处理

---

## 7. 模块设计

### 7.0 代码组织约定

Phase 3 的实现约定如下：

- 根入口脚本：`phase3_format.py`
- 核心实现包：`src/md_format/`

建议目录结构：

```text
phase3_format.py
src/
  md_format/
    __init__.py
    config.py
    contracts.py
    errors.py
    manifest_loader.py
    coverage_auditor.py
    block_aligner.py
    repair_engine.py
    renderer.py
    md_normalizer.py
    postcheck.py
    writer.py
    pipeline.py
```

职责边界：

- `contracts.py`：统一放置 dataclass 与输出契约
- `config.py`：阈值、默认参数、路径策略、覆盖率阈值
- `errors.py`：领域异常与错误码
- `pipeline.py`：主流程编排与切片级并发调度
- 其余模块仅依赖 `contracts.py` 与 `config.py`，不自行定义同名模型

### 7.1 `phase3_format.py`

CLI 主入口，负责参数解析、并发调度、全局统计与退出码控制；其余业务逻辑放在 `src/md_format/` 包内。

建议命令格式：

```bash
python phase3_format.py ^
  --input-dir ./book_extract ^
  --output-dir ./book_format ^
  --workers 4
```

建议参数：

- `--input-dir`
- `--output-dir`
- `--workers`
- `--overwrite`
- `--fail-on-manual-review`
- `--copy-assets`

参数约定：

- `--copy-assets` 默认 `true`
- 当 `--copy-assets=false` 时，Phase 3 不复制资源文件，而是将图片引用路径改写为**相对指向 Phase 2 输出目录**的路径，并在输出清单中记录 `asset_mode = "reuse_phase2"`
- `--copy-assets=false` 生成的输出不是自包含交付物，只适用于同机、同目录树下的串联处理

### 7.1.1 `src/md_format/config.py`

负责集中定义配置常量，建议至少包括：

- `DEFAULT_WORKERS`
- `DEFAULT_COPY_ASSETS`
- `TEXT_COVERAGE_THRESHOLD`
- `TABLE_COVERAGE_THRESHOLD`
- `IMAGE_COVERAGE_THRESHOLD`
- `OVERLAP_COVERAGE_THRESHOLD`
- `RELATIVE_ASSET_STRATEGY`

### 7.1.2 `src/md_format/errors.py`

负责定义领域异常，建议至少包括：

- `InvalidExtractManifestError`
- `MissingContentFileError`
- `MissingDraftMarkdownError`（仅在 manifest 显式声明存在 draft 但文件缺失时使用）
- `InvalidContentSchemaError`
- `MarkdownParseError`
- `AssetReferenceError`
- `PostcheckFailedError`

### 7.2 `src/md_format/manifest_loader.py`

负责读取 `extract_manifest.json` 和单切片目录，并转化为内部任务模型。

校验项：

- `extract_manifest.json` 结构合法
- `status=success` 的切片必须存在 `content.json`；若 manifest 显式声明存在 draft `.md`，则其路径也必须有效
- `content.json.slice_file` 与 manifest 中 `slice_file` 一致
- 切片顺序可稳定恢复，供 Phase 4 合并使用
- `status=failed` 的上游切片不进入格式化流程，直接在 `format_manifest.json` 中记录为 `skipped_upstream_failed`

### 7.3 `src/md_format/coverage_auditor.py`

负责完整性对账，是 Phase 3 的核心模块。

#### 审计目标

- 每个 `source_page` 是否在最终文档中有对应内容
- `blocks/tables/images` 是否存在明显缺失
- overlap 页内容是否仍被保留
- 表格、图片是否仍有可访问的 Markdown/资源引用

#### 对账策略

先构建 `content.json` 的**期望覆盖台账**：

- 页面维度：页数、是否 overlap、字符数、块数量
- 块维度：`type`、`text`、`source_page`、`reading_order`、`dedupe_key`
- 表格维度：`headers`、`rows`、`markdown`、`table_kind`、`parent_table_id`、`child_table_refs`、`render_strategy`、`notes`、`fallback_image`
- 图片维度：`asset_path`、`caption`

若存在 draft Markdown，再构建其**辅助覆盖索引**：

- 文本分段索引
- 标题索引
- 列表索引
- 代码块索引
- 表格索引
- 图片链接索引

最后按“页 -> 块 -> 特殊节点”三层对账输出问题。

### 7.4 `src/md_format/block_aligner.py`

负责将可选 draft Markdown 中的文本片段与 `content.json` 的块节点对齐，用作辅助提示而非事实来源。

#### 归一化规则

为降低版式噪声影响，文本对齐前统一做：

1. Unicode `NFKC` 归一化
2. 连续空白折叠为单空格
3. 去除首尾空白
4. 保留标点，不做语义清洗
5. 保留大小写

#### 对齐键优先级

1. `dedupe_key` 精确对齐
2. `source_page + normalized_text` 精确对齐
3. 同页内按相似度与阅读顺序对齐

若块无法稳定对齐，则直接输出 `missing_block` 或 `duplicate_block`，并交给修复引擎处理。

### 7.5 `src/md_format/repair_engine.py`

负责把审计发现的问题转换为确定性修复动作。

#### 修复顺序

1. **完整性修复优先**
2. **结构修复其次**
3. **样式标准化最后**

#### 具体修复规则

##### 标题修复

- 以 `blocks[].type == "heading"` 和 `display_title` 为事实依据
- 缺失顶级标题时自动补写 `# {display_title}`
- 标题层级跳跃超过 1 级时，优先按相邻标题收敛为 `prev_level + 1`
- Setext 风格统一改写为 ATX 风格

##### 段落修复

- 连续正文行且未形成新块时，合并为同一段落
- 因错误换行导致的段内断裂，在不跨块的前提下自动修复
- 对账确认缺失正文块时，按 `reading_order` 将缺失段落插回

##### 列表修复

- 连续列表项必须保持一致的 marker 和缩进层级
- 误识别为普通段落的列表项，可依据 `blocks[].type == "list_item"` 重建
- 列表前后强制补空行，避免被相邻段落吞并

##### 代码块修复

- 未闭合 fence 自动闭合
- 缩进代码块统一转 fenced code block
- 若 `blocks[].type == "code"` 但 Markdown 中缺失，则按原顺序补回
- 已知语言时保留语言标签，未知则使用纯 fence

##### 表格修复

- 简单二维表优先重建为 GFM pipe table
- 缺失表头分隔行时自动补 `| --- |`
- 对复杂表格：
  - 若 `table_kind == "nested"`，优先重组为“概览表 + 子章节/列表 + 引用说明”
  - 若存在 `notes` / `reference_labels`，应优先保留并渲染
  - 若纯 Markdown 仍不稳定，则插入 `fallback_image`
  - 同时标记 `manual_review_required=true`

##### 图片与图注修复

- 校验 `asset_path` 存在
- 缺失图片引用时按当前 `asset_mode` 生成目标路径：
  - `copy`：写为 `![caption](assets/...)`
  - `reuse_phase2`：写为指向 Phase 2 `assets/` 的相对路径
- 缺失图注但 `content.json` 中存在 `caption` 时，以 `alt` 文本回填
- 图片资源丢失则输出高优先级问题并标记人工复核

##### overlap 页修复

- overlap 页对应块若在最终 Markdown 中完全丢失，必须补回
- overlap 内容允许重复存在，不在 Phase 3 擅自去重
- 去重决策统一保留到 Phase 4

### 7.6 `src/md_format/renderer.py`

负责把 `NormalizedDocument` 输出为**原始渲染版 Markdown**，不直接承担最终样式标准化。

渲染原则：

- 块顺序严格遵循 `source_page + reading_order`
- 不改写原文语义，只调整 Markdown 结构
- 标题、段落、列表、代码、表格、图片分别使用稳定模板输出
- 对截图回退或受控扩展块按原样输出，不再次解释

输出结果：

- `rendered_markdown`
- `render_stats`
  - `char_count`
  - `block_count`
  - `table_count`
  - `image_count`

### 7.7 `src/md_format/md_normalizer.py`

负责调用 `mdformat` 与 `mdformat-gfm`，将 `renderer.py` 输出的原始 Markdown 统一为最终样式。

调用位置固定为：

```text
repair_engine -> NormalizedDocument
renderer -> rendered_markdown
md_normalizer -> normalized_markdown
postcheck -> verify(normalized_markdown)
```

约束：

- `md_normalizer.py` 不允许删除内容块
- 若格式化前后解析出的块级结构显著漂移，必须抛出 `PostcheckFailedError`

### 7.8 `src/md_format/postcheck.py`

负责对最终渲染结果做二次验证。

验证项：

- 重新解析后 token 序列稳定
- 所有缺失块问题已消除或已升级为人工复核
- 资源引用路径存在
- overlap 页仍被保留
- 最终 Markdown 非空，字符数与块数在合理范围内

### 7.9 `src/md_format/writer.py`

负责写出最终文件并汇总全局结果。

输出职责：

- 创建单切片输出目录
- 写最终 `.md`
- 写 `review_report.json`
- 复制或复用 `assets/`
- 汇总为 `format_manifest.json`

---

## 8. 关键算法与规则

### 8.1 完整性判定规则

Phase 3 的“没有遗漏”不以全文字符串完全一致作为标准，而以**块级覆盖率**作为主判据：

- 正文块覆盖率 = `matched_text_blocks / expected_text_blocks`
- 表格覆盖率 = `matched_tables / expected_tables`
- 图片覆盖率 = `matched_images / expected_images`
- overlap 页覆盖率 = `matched_overlap_pages / expected_overlap_pages`

建议阈值：

- 文本块覆盖率 `< 1.0`：直接报 `missing_block`
- 表格覆盖率 `< 1.0`：直接报 `table_render_failed`
- 图片覆盖率 `< 1.0`：直接报 `image_reference_missing`
- overlap 页覆盖率 `< 1.0`：直接报 `overlap_lost`

### 8.2 排序与插回策略

当存在缺失块时，插回顺序统一按：

```text
source_page ASC
  -> reading_order ASC
    -> block_type priority
```

其中 `block_type priority` 建议为：

```text
heading < paragraph < list_item < code < table < image
```

### 8.3 简单表格与复杂表格划分

满足以下条件时视为简单表格，可直接输出 GFM 表格：

- 行列规整
- 无明显跨页
- 无合并单元格或仅极少数可安全展开
- `markdown` 字段非空，且可稳定恢复二维结构

满足以下任一条件视为复杂表格：

- 跨页表格
- 合并单元格过多
- 嵌套表格，且父子关系需要展开表达
- 单元格内嵌多段富文本
- `fallback_image` 已被 Phase 2 使用

### 8.4 人工复核触发条件

满足以下任一条件时，切片标记为 `manual_review_required=true`：

- 仍存在 `missing_block`
- 复杂表格只能以图片回退
- 图片资源丢失
- 代码块语言或边界无法稳定恢复
- 二次解析后结构仍不稳定
- Phase 2 已标记 `manual_review_required=true`

---

## 9. 输出数据结构

### 9.1 `review_report.json`

`auto_fixes[].fix_type` 建议枚举如下：

- `heading_normalized`
- `heading_inserted`
- `paragraph_merged`
- `missing_block_restored`
- `list_rebuilt`
- `code_fence_closed`
- `code_block_rebuilt`
- `table_separator_inserted`
- `table_rebuilt`
- `nested_table_restructured`
- `table_fallback_image_applied`
- `image_reference_restored`
- `image_caption_filled`
- `overlap_block_restored`

建议骨架如下：

```json
{
  "slice_file": "第一章 系统概述（1-18）.pdf",
  "final_md_file": "第一章 系统概述（1-18）.md",
  "created_at": "2026-03-21T12:00:00Z",
  "status": "success",
  "manual_review_required": false,
  "coverage": {
    "text_blocks_expected": 120,
    "text_blocks_matched": 120,
    "tables_expected": 3,
    "tables_matched": 3,
    "images_expected": 4,
    "images_matched": 4,
    "overlap_pages_expected": 1,
    "overlap_pages_matched": 1
  },
  "formatted_stats": {
    "char_count": 4231,
    "block_count": 128,
    "table_count": 3,
    "image_count": 4
  },
  "issues": [],
  "auto_fixes": [
    {
      "fix_type": "heading_normalized",
      "source_page": 1,
      "node_ref": "1:ab12cd34:ef56gh78",
      "message": "将 Setext 标题转换为 ATX 标题"
    }
  ],
  "warnings": []
}
```

### 9.2 `format_manifest.json`

建议骨架如下：

```json
{
  "source_extract_manifest": "extract_manifest.json",
  "source_file": "input.pdf",
  "created_at": "2026-03-21T12:00:00Z",
  "generator_version": "phase3-v1",
  "total_slices": 12,
  "success_count": 11,
  "failed_count": 1,
  "manual_review_count": 2,
  "total_issue_count": 8,
  "total_auto_fixed_count": 23,
  "total_elapsed_ms": 15432,
  "slices": [
    {
      "slice_file": "第一章 系统概述（1-18）.pdf",
      "display_title": "第一章 系统概述",
      "order_index": 1,
      "start_page": 1,
      "end_page": 18,
      "final_md_file": "001-第一章-系统概述/第一章 系统概述（1-18）.md",
      "review_report_file": "001-第一章-系统概述/review_report.json",
      "status": "success",
      "issue_count": 0,
      "auto_fixed_count": 2,
      "formatted_char_count": 4231,
      "formatted_block_count": 128,
      "asset_mode": "copy",
      "manual_review_required": false,
      "elapsed_ms": 918
    }
  ]
}
```

---

## 10. 性能与并发设计

### 10.1 性能目标

在 8 核 CPU、16GB RAM、SSD、本地文件系统环境下，建议验收目标：

- 单个 20 页以内切片的校对与格式化耗时控制在 **3 秒以内**
- 支持以切片为粒度的并发处理
- 全量格式化耗时应明显低于 Phase 2 内容提取耗时

### 10.2 并发策略

- 以切片为最小并发单元
- `--workers N` 控制并发度
- 单切片内部保持串行，避免块对齐与修复顺序不稳定

### 10.3 日志耗时项

- `manifest_load_ms`
- `coverage_audit_ms`
- `repair_ms`
- `render_ms`
- `postcheck_ms`
- `write_ms`
- `total_ms`

---

## 11. 验证计划

### 11.1 单元测试

- `test_manifest_loader.py`
  - 合法/非法 `extract_manifest.json`
- `test_coverage_auditor.py`
  - 缺失块、缺失表格、缺失图片、overlap 丢失
- `test_block_aligner.py`
  - 正常对齐、重复块对齐、相似文本对齐
- `test_repair_engine.py`
  - 标题修复、列表修复、代码 fence 修复、表格回退
- `test_renderer.py`
  - 各块类型输出稳定
- `test_postcheck.py`
  - 二次解析稳定性
- `test_writer.py`
  - 最终 `.md`、`review_report.json`、`format_manifest.json` 输出正确

### 11.2 集成测试

准备以下样本：

1. **普通章节 PDF 切片**
   - 校验标题、段落、列表顺序
   - 校验无额外缺失块

2. **含表格与代码块切片**
   - 校验 pipe table 输出
   - 校验 fenced code block 输出

3. **含图片与图注切片**
   - 校验资源路径与 alt/caption 引用

4. **带 overlap 页切片**
   - 校验 overlap 内容未被误删

5. **Phase 2 已标记人工复核切片**
   - 校验 Phase 3 能继承并放大风险提示

### 11.3 人工验收项

- 抽查最终 Markdown 与 `content.json` 对账结果是否一致；若存在 Phase 2 draft，可作为辅助抽检样本
- 抽查嵌套表格是否按预期重组为纯 Markdown 结构，或在必要时退回截图
- 抽查图片路径是否可直接渲染
- 抽查标题层级是否连续、可读
- 抽查 overlap 内容是否仍然存在

---

## 12. 实施顺序建议

### Milestone 1：主链路打通

- 读取 `extract_manifest.json`
- 读取 `content.json`，并接入可选 draft `.md`
- 输出基础版 `format_manifest.json`

### Milestone 2：完整性对账

- 实现 `coverage_auditor`
- 实现 `block_aligner`
- 打通缺失块检测

### Milestone 3：结构修复

- 实现标题、列表、代码块修复
- 实现简单表格重建
- 实现图片路径校验与回填

### Milestone 4：标准化与验收

- 接入 `mdformat`
- 增加 `postcheck`
- 补齐测试、性能指标与人工复核机制

---

## 13. 结论

Phase 3 的正确实现方式，不是把 Phase 2 的 Markdown 再交给一个“格式化工具”简单跑一遍，而是：

- 以 `content.json` 为事实基线，先证明内容没丢
- 以规则引擎修复结构问题，而不是自由重写文本
- 以 `markdown-it-py + mdformat` 完成解析与标准化渲染
- 以 `review_report.json + format_manifest.json` 保留审计与追溯能力

这样才能同时满足 [PRD-Markdown格式化需求(Phase3).md](D:\projects01\pdf-convert\docs\PRD-Markdown格式化需求(Phase3).md) 中“Markdown 格式化”的目标，以及 `需求.txt` 中“逐章节检查内容完整、格式正确、没有遗漏”的要求，并为 Phase 4 合并提供稳定输入。

---

## 参考资料

- CommonMark Spec  
  https://spec.commonmark.org/0.31.2/

- markdown-it-py 官方文档  
  https://markdown-it-py.readthedocs.io/en/latest/using.html

- mdformat 官方文档  
  https://mdformat.readthedocs.io/en/stable/users/style.html

- mdformat-gfm 官方仓库  
  https://github.com/hukkin/mdformat-gfm

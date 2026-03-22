# 技术实施方案 (Implementation Plan)：大型 PDF 转 MD 项目 - Phase 4

## 1. 目标与范围

基于 [PRD-PDF切分需求.md](D:\projects01\pdf-convert\docs\PRD-PDF切分需求.md)、[需求.txt](D:\projects01\pdf-convert\docs\需求.txt) 以及 [技术方案-Markdown格式化(Phase3).md](D:\projects01\pdf-convert\docs\技术方案-Markdown格式化(Phase3).md) 中已经冻结的上下游契约，Phase 4 的职责应收敛为：

- 消费 Phase 3 输出的最终版 Markdown、`review_report.json`、`format_manifest.json`
- 按章节顺序对所有切片 Markdown 执行**全局校验**
- 基于 Phase 1/2/3 传递下来的重叠页与追溯信息执行**确定性去重**
- 生成整本书或整份文档的**单文件 Markdown**
- 输出合并报告与全局 `merge_manifest.json`，保留审计、异常与人工复核结论

本阶段的核心目标不是重新抽取 PDF 内容，也不是再次做 Markdown 格式化，而是把 Phase 3 已经校对好的章节级 Markdown 收敛为**可交付、可追溯、可复核的单文件结果**。

### 本期范围

- 支持：消费 Phase 3 成功输出的章节级最终 Markdown
- 支持：相邻切片间 overlap 内容识别、去重与拼接
- 支持：章节顺序恢复、标题衔接、资源路径重写、全局单文件输出
- 支持：生成 `merge_report.json` 与 `merge_manifest.json`
- 不支持：脱离 Phase 3 的孤立 `.md` 文件直接合并
- 不支持：人工语义润色、摘要、翻译、知识补写
- 不支持：对 Phase 3 已判定失败的切片做兜底重建

---

## 2. 阶段边界

为避免与上游重复建设，边界固定如下：

### Phase 2：内容提取

- 从切片 PDF 中提取 Markdown draft
- 输出 `content.json`、图片资源、页级与块级追溯信息
- 生成 `dedupe_key`、`is_overlap`、`source_page` 等后续去重所需的基础元数据

### Phase 3：Markdown 格式化

- 对 `draft + content.json` 做完整性对账
- 修复标题、列表、代码块、表格、图片引用等结构问题
- 输出章节级最终 Markdown、`review_report.json`、`format_manifest.json`

### Phase 4：校验与拼接

- 校验所有章节级最终 Markdown 是否满足合并前提
- 基于 overlap 追溯信息识别跨切片重复内容
- 仅对**相邻切片的重叠内容**执行确定性去重
- 合并为最终单文件 Markdown，并输出全局报告

### 结论

Phase 4 只处理“全局一致性”和“交付物合并”，不再负责内容提取、结构修复或自由改写文本。这样可以保证职责清晰，也便于问题追溯回具体阶段。

---

## 3. 输入输出定义

### 3.1 输入

Phase 4 以 Phase 3 输出目录为输入，最小输入集如下：

```text
<源文件名>_format/
  format_manifest.json
  001-第一章-系统概述/
    第一章 系统概述（1-18）.md
    review_report.json
    assets/
  002-第二章-架构设计/
    第二章 架构设计（19-35）.md
    review_report.json
    assets/
  ...
```

#### `format_manifest.json` 最低依赖字段

- `source_extract_manifest`
- `source_file`
- `generator_version`
- `total_slices`
- `slices[].slice_file`
- `slices[].display_title`
- `slices[].order_index`
- `slices[].start_page`
- `slices[].end_page`
- `slices[].final_md_file`
- `slices[].review_report_file`
- `slices[].status`
- `slices[].manual_review_required`

#### `review_report.json` 最低依赖字段

- `slice_file`
- `final_md_file`
- `status`
- `manual_review_required`
- `coverage.overlap_pages_expected`
- `coverage.overlap_pages_matched`
- `issues`
- `warnings`

### 3.2 可选追溯输入

为提升 overlap 去重稳定性，Phase 4 建议同时回溯 Phase 2 的 `content.json` 或其在 Phase 3 中继承后的块级索引。最小可用字段如下：

- `source_pages[].source_page`
- `source_pages[].is_overlap`
- `source_pages[].blocks[].dedupe_key`
- `source_pages[].blocks[].type`
- `source_pages[].blocks[].text`
- `source_pages[].images[].asset_path`
- `source_pages[].tables[].markdown`

若上游没有把这些字段直接暴露给 Phase 4，则应由 `provenance_loader.py` 根据 `format_manifest.json -> source_extract_manifest -> content.json` 反向加载。

### 3.3 输出

建议输出目录：

```text
<源文件名>_merged/
  <源文件名>.md
  merge_report.json
  merge_manifest.json
  assets/
    001-第一章-系统概述/
    002-第二章-架构设计/
    ...
```

#### 输出文件说明

- `<源文件名>.md`：最终单文件 Markdown
- `merge_report.json`：全局校验、去重、合并明细与人工复核结论
- `merge_manifest.json`：全局执行清单、统计信息、失败与警告汇总
- `assets/`：按章节目录归档后的资源目录，供最终 Markdown 相对引用

### 3.4 设计原则

- 最终单文件 Markdown 命名固定为：`原文件名.md`
- 最终产物应尽量自包含，优先复制并重写资源路径，不依赖原 Phase 3 目录长期存在
- 去重仅发生在**相邻切片的 overlap 区域**，不做全书范围的激进去重
- 所有自动去重动作都必须落到报告中，支持人工回溯

---

## 4. 系统架构与主流程

### 4.1 架构概览

```text
Phase3 format_manifest.json + final markdown + review_report.json
        ↓
Phase4 CLI Orchestrator
        ↓
Manifest Loader / Precheck
        ↓
Provenance Loader
        ↓
Merge Planner
        ↓
Overlap Resolver
        ↓
Asset Relinker
        ↓
Final Stitcher
        ↓
Post-Merge Verifier
        ↓
<source>.md + merge_report.json + merge_manifest.json
```

### 4.2 主流程

1. 读取 `format_manifest.json`，构建按 `order_index` 排序的 `MergeTask` 列表。
2. 校验每个切片的最终 Markdown、`review_report.json`、资源目录是否存在。
3. 检查是否存在 `status != success` 的切片；若存在，则默认终止整体验证与合并。
4. 通过 `provenance_loader` 加载 overlap 去重所需的块级追溯信息。
5. 由 `merge_planner` 生成章节顺序、切片边界与资源映射计划。
6. 对每一对相邻切片执行 overlap 检测与去重，产出 `DedupDecision` 列表。
7. 由 `asset_relinker` 复制资源并改写 Markdown 中的相对路径。
8. 由 `stitcher` 按顺序拼接章节内容，插入统一分隔策略，生成最终单文件 Markdown。
9. 由 `postcheck` 再次校验章节顺序、重复块清理结果、图片链接、标题结构与非空性。
10. 写出 `<源文件名>.md`、`merge_report.json`、`merge_manifest.json`。

---

## 5. 技术选型

### 5.1 核心组件

- **Python 3.10+**：CLI 与数据编排
- **markdown-it-py**：解析章节级最终 Markdown，构建稳定 token/块边界索引
- **标准库 `pathlib` / `json` / `re` / `unicodedata` / `hashlib` / `shutil`**：路径处理、归一化、哈希与文件复制
- **Phase 2 `content.json` / Phase 3 `review_report.json`**：去重与校验的事实来源

所有外部依赖应在 `requirements.txt` 中显式锁定版本，避免解析结果漂移。

### 5.2 选型理由

#### 为什么 Phase 4 仍需要 Markdown 解析器

即使 Phase 3 已经输出最终版 Markdown，Phase 4 仍需要稳定识别：

- 切片头尾的标题、段落、列表、代码块、图片块
- overlap 区域的可比较块边界
- 资源链接和标题结构是否在拼接后仍然合法

因此仍建议使用 `markdown-it-py` 做块级解析，而不是仅用字符串拼接。

#### 为什么不能只按纯文本比较去重

Phase 1 的 overlap 机制会把同一物理页同时保留在前后切片中，但文档里也可能天然存在：

- 重复出现的警告说明
- 多章共用的表头/页眉文本
- 同名标题或相似开场段

若仅按纯文本去重，容易误删合法内容。Phase 4 应优先使用上游传递的 `dedupe_key`、`source_page`、`is_overlap`、块类型等结构化信息；只有在结构信息缺失时，才退化到 `normalized_text_hash`。

#### 为什么资源目录按章节复制而不是扁平化

Phase 2 生成的图片名通常只保证在单切片内稳定，不保证跨切片全局唯一。Phase 4 若直接扁平复制，容易发生文件名冲突。按章节子目录复制可避免冲突，也便于回溯来源。

### 5.3 参考规范与约束

- CommonMark 规范要求块结构和行级结构有明确优先级，适合作为最终 Markdown 合并后的基本语法约束
- Python `hashlib` 标准库可用于生成稳定的非安全场景内容哈希，适合做块级辅助去重键

---

## 6. 数据模型设计

本节的数据模型统一落地到 `src/md_merge/contracts.py`，避免散落定义。

### 6.1 任务模型

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass
class MergeTask:
    slice_file: str
    display_title: str
    order_index: int
    start_page: int
    end_page: int
    input_dir: Path
    final_md_file: Path
    review_report_file: Path
    assets_dir: Path | None
    manual_review_required: bool
```

### 6.2 块级追溯模型

```python
from dataclasses import dataclass

@dataclass
class MergeBlockRef:
    source_page: int
    block_type: str
    is_overlap: bool
    dedupe_key: str | None
    normalized_text_hash: str | None
    asset_ref: str | None
    markdown: str
```

字段约束：

- `dedupe_key` 优先来自 Phase 2
- `normalized_text_hash` 仅作为退化比对键
- `asset_ref` 用于图片、复杂表格截图等资源类块
- `markdown` 为拼接时使用的最终块内容，不回退到原始 draft

### 6.3 去重决策模型

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class DedupDecision:
    left_slice_file: str
    right_slice_file: str
    source_page: int | None
    match_strategy: Literal["dedupe_key", "source_page_text_hash", "asset_ref", "none"]
    removed_from: Literal["left_tail", "right_head", "none"]
    removed_count: int
    warning: str | None
```

### 6.4 输出结果模型

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class MergeResult:
    source_file: str
    merged_md_file: str
    status: Literal["success", "failed", "aborted_upstream_invalid"]
    total_slices: int
    merged_slices: int
    removed_overlap_blocks: int
    warning_count: int
    manual_review_required: bool
    warnings: list["MergeWarning"]
    elapsed_ms: int
```

### 6.5 告警模型

为避免 Phase 4 继续使用自由文本 warning，建议引入结构化告警模型，便于 CI、质量报告或后续自动化管线按类型聚合。

```python
from dataclasses import dataclass
from typing import Literal

@dataclass
class MergeWarning:
    warning_type: Literal[
        "overlap_match_unstable",
        "overlap_no_provenance",
        "asset_copy_failed",
        "asset_path_missing",
        "page_gap_detected",
        "slice_missing",
        "upstream_manual_review_inherited",
        "consecutive_duplicate_detected",
        "heading_count_mismatch",
    ]
    slice_file: str | None
    message: str
```

---

## 7. 模块设计

### 7.0 代码组织约定

Phase 4 的实现约定如下：

- 根入口脚本：`phase4_merge.py`
- 核心实现包：`src/md_merge/`

建议目录结构：

```text
phase4_merge.py
src/
  md_merge/
    __init__.py
    config.py
    contracts.py
    errors.py
    manifest_loader.py
    provenance_loader.py
    merge_planner.py
    overlap_resolver.py
    asset_relinker.py
    stitcher.py
    postcheck.py
    writer.py
    pipeline.py
```

### 7.1 `phase4_merge.py`

CLI 主入口，负责参数解析、全局调度、退出码与汇总统计。

建议命令格式：

```bash
python phase4_merge.py ^
  --input-dir ./book_format ^
  --output-dir ./book_merged ^
  --copy-assets ^
  --fail-on-manual-review
```

建议参数：

- `--input-dir`
- `--output-dir`
- `--copy-assets`
- `--overwrite`
- `--fail-on-manual-review`
- `--allow-upstream-manual-review`

参数约定：

- `--copy-assets=true` 默认开启，生成自包含交付物
- `--overwrite=true` 时，若输出目录已存在则允许清空后重建；否则直接报错退出，避免覆盖已有交付结果
- `--fail-on-manual-review=true` 时，只要任一章节或最终合并结果需要人工复核，就返回非 0 退出码
- `--allow-upstream-manual-review=true` 时，可在保留风险标记的前提下继续合并

### 7.1.1 `src/md_merge/config.py`

负责集中定义配置常量，建议至少包括：

- `DEFAULT_COPY_ASSETS`
- `DEFAULT_OVERWRITE`
- `DEFAULT_FAIL_ON_MANUAL_REVIEW`
- `DEFAULT_ALLOW_UPSTREAM_MANUAL_REVIEW`
- `OVERLAP_COMPARE_MAX_BLOCKS`
- `MAX_HEADING_LEVEL`
- `MERGE_SEPARATOR_STYLE`
- `TEXT_HASH_ALGORITHM`

### 7.1.2 `src/md_merge/errors.py`

建议定义以下领域异常：

- `InvalidFormatManifestError`
- `MissingFinalMarkdownError`
- `MissingReviewReportError`
- `ProvenanceLoadError`
- `OverlapResolutionError`
- `AssetRelinkError`
- `PostMergeVerificationError`

### 7.2 `src/md_merge/manifest_loader.py`

负责读取 `format_manifest.json` 和切片目录，转化为 `MergeTask` 列表。

校验项：

- `format_manifest.json` 结构合法
- 所有 `status=success` 的切片都必须存在最终 Markdown 与 `review_report.json`
- `order_index` 必须连续可排序，不允许重复
- 若存在 `status!=success` 的切片，则直接阻断默认合并流程

### 7.3 `src/md_merge/provenance_loader.py`

负责加载 overlap 去重所需的追溯信息。

#### 加载优先级

1. 优先读取 Phase 3 已继承或缓存的块级索引
2. 若无，则从 `format_manifest.json -> source_extract_manifest -> content.json` 反向加载
3. 若仍无结构化索引，则退化为基于 Markdown 头尾块的文本哈希比较

#### 输出职责

- 为每个切片构建 `head_blocks` 与 `tail_blocks`
- 标记哪些块来自 `is_overlap=true`
- 为图片、复杂表格截图建立 `asset_ref`

### 7.4 `src/md_merge/merge_planner.py`

负责生成全局拼接计划。

#### 规划项

- 切片顺序恢复
- 每个切片的合并前后分隔策略
- 资源复制与重写策略
- 相邻切片对列表

#### 规则

- 只能按 `order_index ASC` 合并，不允许按文件名字典序推断
- 默认只比较 `(i, i+1)` 相邻切片，不做跨越式多切片去重
- 若相邻切片页码范围不连续，必须输出告警并标记人工复核

### 7.5 `src/md_merge/overlap_resolver.py`

负责识别并移除相邻切片的 overlap 重复内容，是 Phase 4 的核心模块。

#### 去重原则

1. 只处理**相邻切片**
2. 只处理**标记为 overlap 的头尾区域**
3. 只删除“确定可证明相同”的重复块
4. 一旦匹配不稳定，宁可保留重复，也不要误删正文

#### 匹配优先级

1. `dedupe_key` 精确匹配
2. `source_page + block_type + normalized_text_hash` 匹配
3. `asset_ref` 匹配，用于图片和截图类块
4. 无法证明一致时，不去重，只输出 warning

#### 删除策略

- 默认删除**后一个切片开头**的重复 overlap 块，保留前一个切片尾部内容
- 保证章节边界在合并结果中只出现一次，但章节标题本身若是新章节起点，不应被误删
- 若 overlap 页同时含“上一章尾部 + 下一章标题”，应保留下一章标题，并仅移除已证明重复的上一章尾部块

#### 特殊场景

- **标题块**：不能仅因文本相同就删除，必须结合 `source_page` 与位置判断
- **表格块**：若为复杂表格 HTML 或截图回退，优先使用 `asset_ref` 去重
- **代码块**：必须按完整 fenced block 作为最小单元比对，不允许截半删除

### 7.6 `src/md_merge/asset_relinker.py`

负责复制资源并改写 Markdown 相对路径。

#### 复制策略

- 最终目录统一为：`assets/<章节目录>/...`
- 保持原始资源文件名不变，避免上游引用与报告失效
- 若用户关闭 `--copy-assets`，则允许改写为指向 Phase 3 目录的相对路径，但不推荐作为最终交付模式

#### 路径改写规则

- `![alt](assets/foo.png)` → `![alt](assets/001-第一章-系统概述/foo.png)`
- HTML `<img>` 标签中的 `src` 也必须同步改写
- `merge_report.json` 中记录改写前后路径映射，建议单独落在 `asset_relinks` 数组中

### 7.7 `src/md_merge/stitcher.py`

负责把去重后的章节内容顺序拼接为最终 Markdown。

#### 拼接原则

- 保留每个章节在 Phase 3 的最终结构，不再次重排块顺序
- 章节之间统一插入一个空行和一个可配置分隔策略
- 默认不插入额外目录页或封面页，避免超出当前需求

#### 分隔策略建议

- 默认仅插入两个换行，不额外插入 `---`
- 若启用 `MERGE_SEPARATOR_STYLE="thematic_break"`，则在章节间插入 CommonMark 合法的 thematic break

### 7.8 `src/md_merge/postcheck.py`

负责对最终合并结果做二次验证。

验证项：

- 最终 Markdown 非空
- 章节顺序与 `order_index` 一致
- 一级标题数量与切片数量基本一致
- 图片/HTML 资源路径可访问
- overlap 重复块已按决策移除或已记录 warning
- 合并后未出现明显连续重复段落风暴

#### 连续重复检测

为避免拼接残留明显重复内容，可在最终文档上做一个轻量检查：

- 比较相邻块的 `normalized_text_hash`
- 若连续出现超过阈值的完全重复块，输出 warning
- 不自动继续删除，避免二次误删

### 7.9 `src/md_merge/writer.py`

负责写出最终文件并汇总全局结果。

输出职责：

- 创建输出目录
- 写 `<源文件名>.md`
- 写 `merge_report.json`
- 写 `merge_manifest.json`
- 复制资源目录

### 7.10 `src/md_merge/pipeline.py`

负责串联所有模块，是 Phase 4 的顶层编排函数所在位置。

#### 建议函数签名

```python
def run_merge(task_list: list[MergeTask], config: MergeConfig) -> MergeResult:
    ...
```

#### 调用顺序

1. `manifest_loader` 校验输入与任务顺序
2. `provenance_loader` 加载 overlap 去重所需追溯信息
3. `merge_planner` 生成相邻切片对与资源处理计划
4. `overlap_resolver` 产出去重决策
5. `asset_relinker` 复制资源并改写 Markdown 中的链接
6. `stitcher` 生成最终单文件 Markdown
7. `postcheck` 对最终结果执行二次验证
8. `writer` 写出最终产物和报告

#### 异常传播与中断策略

- `manifest_loader`、`provenance_loader`、`postcheck` 的致命错误默认直接中断，不产生部分交付物
- `overlap_resolver` 若匹配不稳定，默认降级为保留重复内容并记录结构化 warning，而不是抛异常中断
- `asset_relinker` 若资源复制失败，默认标记 `manual_review_required=true`；若失败导致最终 Markdown 存在不可恢复的断链，则升级为致命错误
- 若 `config.fail_on_manual_review=true` 且最终结果需要人工复核，则 `pipeline.py` 应返回非 0 退出状态

#### 耗时日志埋点

建议在 `pipeline.py` 统一记录：

- `manifest_load_ms`
- `provenance_load_ms`
- `overlap_resolve_ms`
- `asset_relink_ms`
- `stitch_ms`
- `postcheck_ms`
- `write_ms`
- `total_ms`

---

## 8. 关键算法与规则

### 8.1 文本归一化规则

当必须退化到文本哈希比较时，统一使用以下归一化规则：

1. Unicode 归一化为 `NFKC`
2. 连续空白折叠为单个空格
3. 去除首尾空白
4. 保留标点
5. 保留大小写

说明：

- 不移除标点，是为了降低不同语义句子被误判为相同块的风险
- 不统一大小写，是为了保留代码、缩写和专有名词差异

### 8.2 辅助哈希策略

建议使用：

```text
normalized_text_hash = sha256(normalized_text.encode("utf-8")).hexdigest()
```

此哈希仅用于**非安全场景下的稳定比对**，不承担安全校验职责。

### 8.3 overlap 去重窗口

为了降低误删风险，Phase 4 不应比较整篇文档，而只比较：

- 前一切片末尾的 `N` 个块
- 后一切片开头的 `N` 个块

其中 `N` 建议默认取 `20`，并允许在配置中调整。

### 8.4 去重判定规则

满足以下全部条件时，才允许判定为“可删除重复块”：

1. 来自相邻切片
2. 至少一侧标记为 `is_overlap=true`
3. 满足任一稳定匹配条件：
   - `dedupe_key` 相同
   - `source_page + block_type + normalized_text_hash` 相同
   - `asset_ref` 相同
4. 删除后不会导致下一章节标题丢失

### 8.5 人工复核触发条件

满足以下任一条件时，最终结果标记 `manual_review_required=true`：

- 存在上游切片已被标记人工复核
- 相邻切片 overlap 无法稳定匹配，只能保留重复内容
- 合并后资源路径缺失或复制失败
- 章节顺序异常、页码范围异常或切片缺失
- 连续重复检测命中高风险重复段

---

## 9. 输出数据结构

### 9.1 `merge_report.json`

建议骨架如下：

```json
{
  "source_file": "input.pdf",
  "merged_md_file": "input.md",
  "created_at": "2026-03-22T10:00:00Z",
  "status": "success",
  "manual_review_required": false,
  "summary": {
    "total_slices": 12,
    "merged_slices": 12,
    "adjacent_pairs": 11,
    "removed_overlap_blocks": 34,
    "warning_count": 1
  },
  "asset_relinks": [
    {
      "slice_file": "第一章 系统概述（1-18）.pdf",
      "original_path": "assets/p0003_img01.png",
      "rewritten_path": "assets/001-第一章-系统概述/p0003_img01.png"
    }
  ],
  "pairs": [
    {
      "left_slice_file": "第一章 系统概述（1-18）.pdf",
      "right_slice_file": "第二章 架构设计（19-35）.pdf",
      "match_strategy": "dedupe_key",
      "removed_from": "right_head",
      "removed_count": 3,
      "warning": null
    }
  ],
  "warnings": [
    {
      "warning_type": "upstream_manual_review_inherited",
      "slice_file": "第三章 部署说明（36-52）.pdf",
      "message": "上游切片已标记人工复核，Phase 4 继承该风险标记。"
    }
  ]
}
```

### 9.2 `merge_manifest.json`

建议骨架如下：

```json
{
  "source_format_manifest": "format_manifest.json",
  "source_file": "input.pdf",
  "created_at": "2026-03-22T10:00:00Z",
  "generator_version": "phase4-v1",
  "merged_md_file": "input.md",
  "status": "success",
  "total_slices": 12,
  "merged_slices": 12,
  "manual_review_required": false,
  "removed_overlap_blocks": 34,
  "warning_count": 1,
  "total_elapsed_ms": 2418,
  "slices": [
    {
      "slice_file": "第一章 系统概述（1-18）.pdf",
      "display_title": "第一章 系统概述",
      "order_index": 1,
      "start_page": 1,
      "end_page": 18,
      "status": "merged",
      "manual_review_required": false
    }
  ]
}
```

---

## 10. 性能与并发设计

### 10.1 性能目标

在 8 核 CPU、16GB RAM、SSD、本地文件系统环境下，建议验收目标：

- 单本 1000 页以内文档的 Markdown 合并在 **10 秒以内**完成
- overlap 去重与资源重写应明显快于 Phase 2 提取和 Phase 3 格式化

### 10.2 并发策略

- 主合并链路保持串行，保证输出顺序稳定
- 资源复制与 review_report 预加载可并行
- overlap 去重决策仍建议按相邻切片顺序执行，避免决策上下文混乱

### 10.3 日志耗时项

- `manifest_load_ms`
- `provenance_load_ms`
- `overlap_resolve_ms`
- `asset_relink_ms`
- `stitch_ms`
- `postcheck_ms`
- `write_ms`
- `total_ms`

---

## 11. 验证计划

### 11.1 单元测试

- `test_manifest_loader.py`
  - 合法/非法 `format_manifest.json`
- `test_provenance_loader.py`
  - Phase 3 到 Phase 2 的追溯加载
- `test_overlap_resolver.py`
  - `dedupe_key` 去重、文本哈希退化匹配、标题保护、代码块保护
- `test_asset_relinker.py`
  - 图片路径与 HTML `img` 路径改写
- `test_stitcher.py`
  - 章节顺序拼接与分隔策略
- `test_postcheck.py`
  - 最终标题结构、资源链接、重复检测
- `test_writer.py`
  - 最终 Markdown、`merge_report.json`、`merge_manifest.json` 输出正确

### 11.2 集成测试

准备以下样本：

1. **正常带 overlap 的章节切片**
   - 校验相邻章节重复内容只保留一份
   - 校验章节标题顺序正确

2. **含图片和复杂表格截图的章节切片**
   - 校验资源复制与路径改写
   - 校验截图类资源未丢失

3. **上游已人工复核章节**
   - 校验 Phase 4 能继承并放大风险提示

4. **缺失切片或页码断裂样本**
   - 校验 Phase 4 默认阻断合并

### 11.3 人工验收项

- 抽查章节边界，确认 overlap 内容未重复出现两次
- 抽查章节标题顺序，确认与原文一致
- 抽查最终单文件中的图片、复杂表格截图是否可正常访问
- 抽查 `merge_report.json` 中的去重记录是否可追溯

---

## 12. 实施顺序建议

### Milestone 1：主链路打通

- 读取 `format_manifest.json`
- 读取章节级最终 Markdown
- 输出基础版 `merge_manifest.json`

### Milestone 2：去重能力落地

- 实现 `provenance_loader`
- 实现 `overlap_resolver`
- 打通 `dedupe_key` 优先去重

### Milestone 3：资源与报告完善

- 实现 `asset_relinker`
- 输出 `merge_report.json`
- 补齐人工复核标记

### Milestone 4：验收与稳态

- 增加 `postcheck`
- 补齐单元测试与集成测试
- 收敛性能指标和失败退出码

---

## 13. 结论

Phase 4 的正确实现方式，不是对所有 Markdown 文件做简单的字符串拼接，而是：

- 以 `format_manifest.json` 恢复稳定章节顺序
- 以 Phase 2/3 的追溯信息对 overlap 做确定性去重
- 以资源重写保证最终单文件可交付
- 以 `merge_report.json + merge_manifest.json` 保留可审计、可复核的合并过程

这样才能满足 `需求.txt` 中“将所有 MD 文件按照章节顺序合并，并命名为原文件名.md”的要求，同时延续前 3 个阶段已经建立起来的可追溯性和质量控制能力。

---

## 参考资料

- CommonMark Spec  
  https://spec.commonmark.org/0.31.2/

- Python `hashlib` 官方文档  
  https://docs.python.org/3/library/hashlib.html

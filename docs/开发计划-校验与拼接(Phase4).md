# 开发计划：校验与拼接模块（Phase 4）

## 1. 目的

本开发计划严格基于以下文档执行：

- [PRD-校验与拼接需求(Phase4).md](D:\projects01\pdf-convert\docs\PRD-校验与拼接需求(Phase4).md)
- [技术方案-校验与拼接(Phase4).md](D:\projects01\pdf-convert\docs\技术方案-校验与拼接(Phase4).md)

后续 Phase 4 的编码、测试、评审与验收，统一以本计划为执行基线。若实现过程中需要调整边界、数据结构、模块职责、去重规则或输出契约，必须先更新技术方案与本开发计划，再进入编码。

---

## 2. 范围与约束

### 2.1 当前范围

- 输入来自 Phase 3 输出目录：
  - `format_manifest.json`
  - 最终版 `.md`
  - `review_report.json`
  - `assets/`
- 可选追溯输入来自 Phase 2：
  - `content.json`
  - `dedupe_key`
  - `source_page`
  - `is_overlap`
- 输出：
  - `原文件名.md`
  - `merge_report.json`
  - `merge_manifest.json`
  - `assets/`（复制或复用后供最终单文件引用）

### 2.2 明确不做

- 不重新抽取 PDF 内容
- 不再次做 Markdown 结构修复或样式格式化
- 不引入 OCR、LLM 改写、润色、翻译、摘要
- 不处理脱离 `format_manifest.json` 的孤立 Markdown 文件
- 不对全书范围做激进去重，仅处理相邻切片 overlap 区域

### 2.3 技术约束

- Python 版本：`3.10+`
- 依赖必须写入 `requirements.txt`
- `markdown-it-py` 必须锁定版本
- 最终合并顺序只能以 `order_index` 为准，不允许按文件名字典序推断
- 去重必须优先使用结构化追溯信息，不允许直接全量纯文本去重
- `--copy-assets` 默认 `true`
- `--overwrite=false` 时若输出目录已存在必须直接失败
- `--allow-upstream-manual-review=false` 默认阻断带上游人工复核标记的整体验证与合并

---

## 3. 总体实施策略

采用“先冻结契约，再打通主链路，再补齐去重和资源处理，最后做验收闭环”的顺序推进，分为 4 个里程碑：

1. **M1 项目骨架与契约冻结**
2. **M2 主链路与追溯加载**
3. **M3 overlap 去重与资源重写**
4. **M4 输出、测试与验收闭环**

任何里程碑未达到完成标准，不进入下一阶段。

### 3.1 预估工期

- `M1 项目骨架与契约冻结`：1.0 天
- `M2 主链路与追溯加载`：1.5 天
- `M3 overlap 去重与资源重写`：2.0 天
- `M4 输出、测试与验收闭环`：1.0 天

总预估工期：**5.5 个开发日**

---

## 4. 推荐代码结构

建议新增如下目录结构：

```text
D:\projects01\pdf-convert\
  requirements.txt
  phase4_merge.py
  src\
    md_merge\
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
  tests\
    test_manifest_loader.py
    test_provenance_loader.py
    test_merge_planner.py
    test_overlap_resolver.py
    test_asset_relinker.py
    test_stitcher.py
    test_postcheck.py
    test_writer.py
    test_pipeline_smoke.py
  docs\
    技术方案-校验与拼接(Phase4).md
    开发计划-校验与拼接(Phase4).md
```

说明：

- `phase4_merge.py` 仅做 CLI 入口
- `pipeline.py` 负责主流程编排
- `config.py` 负责默认开关、去重窗口、分隔策略和日志键名
- `contracts.py` 统一定义 `MergeTask`、`MergeBlockRef`、`DedupDecision`、`MergeWarning`、`MergeResult`
- 所有模块不得绕开 `contracts.py` 自行定义同名结构

---

## 5. 数据契约先行

编码开始前，必须先冻结以下数据模型与枚举。

### 5.1 核心数据模型

- `MergeTask`
- `MergeBlockRef`
- `DedupDecision`
- `MergeWarning`
- `MergeResult`
- `MergeReport`
- `MergeManifest`

### 5.2 字段要求

#### `MergeTask`

最低字段：

- `slice_file`
- `display_title`
- `order_index`
- `start_page`
- `end_page`
- `input_dir`
- `final_md_file`
- `review_report_file`
- `assets_dir`
- `manual_review_required`

#### `MergeBlockRef`

最低字段：

- `source_page`
- `block_type`
- `is_overlap`
- `dedupe_key`
- `normalized_text_hash`
- `asset_ref`
- `markdown`

#### `DedupDecision`

最低字段：

- `left_slice_file`
- `right_slice_file`
- `source_page`
- `match_strategy`
- `removed_from`
- `removed_count`
- `warning`

`match_strategy` 允许值：

- `dedupe_key`
- `source_page_text_hash`
- `asset_ref`
- `none`

`removed_from` 允许值：

- `left_tail`
- `right_head`
- `none`

#### `MergeWarning`

最低字段：

- `warning_type`
- `slice_file`
- `message`

`warning_type` 允许值：

- `overlap_match_unstable`
- `overlap_no_provenance`
- `asset_copy_failed`
- `asset_path_missing`
- `page_gap_detected`
- `slice_missing`
- `upstream_manual_review_inherited`
- `consecutive_duplicate_detected`
- `heading_count_mismatch`

#### `MergeResult`

最低字段：

- `source_file`
- `merged_md_file`
- `status`
- `total_slices`
- `merged_slices`
- `removed_overlap_blocks`
- `warning_count`
- `manual_review_required`
- `warnings`
- `elapsed_ms`

`status` 允许值：

- `success`
- `failed`
- `aborted_upstream_invalid`

### 5.3 契约规则

- `merge_manifest.json` 必须保留每个切片的：
  - `slice_file`
  - `display_title`
  - `order_index`
  - `start_page`
  - `end_page`
  - `status`
  - `manual_review_required`
- `merge_report.json` 必须包含：
  - `summary`
  - `pairs`
  - `asset_relinks`
  - `warnings`
- 去重仅允许发生在相邻切片头尾窗口
- `warnings` 必须使用结构化 `warning_type`，不再使用自由文本列表

---

## 6. 里程碑与任务拆解

### M1：项目骨架与契约冻结

目标：完成目录、依赖、CLI、契约与异常模型，为后续去重和拼接能力提供稳定基线。

### T1. 建立项目骨架

- 新增 `requirements.txt`
- 新增 `src/md_merge/`
- 新增 `phase4_merge.py`
- 新增基础测试目录
- 实现 CLI 参数定义：
  - `--input-dir`
  - `--output-dir`
  - `--copy-assets`
  - `--overwrite`
  - `--fail-on-manual-review`
  - `--allow-upstream-manual-review`

完成标准：

- `phase4_merge.py --help` 可执行
- `requirements.txt` 明确锁定 `markdown-it-py`
- CLI 参数帮助文本完整
- `--overwrite`、`--fail-on-manual-review`、`--allow-upstream-manual-review` 行为有明确帮助说明

### T2. 实现 `config.py`

- 定义默认参数
- 定义 overlap 比较窗口
- 定义章节分隔策略
- 定义日志耗时键

完成标准：

- 至少包含：
  - `DEFAULT_COPY_ASSETS`
  - `DEFAULT_OVERWRITE`
  - `DEFAULT_FAIL_ON_MANUAL_REVIEW`
  - `DEFAULT_ALLOW_UPSTREAM_MANUAL_REVIEW`
  - `OVERLAP_COMPARE_MAX_BLOCKS`
  - `MERGE_SEPARATOR_STYLE`
  - `TEXT_HASH_ALGORITHM`
- 模块内不得写死重复常量

### T3. 实现 `contracts.py`

- 定义所有 dataclass / TypedDict / Enum / Literal
- 固化 `status`、`warning_type`、`match_strategy`、`removed_from` 枚举

完成标准：

- 所有模块只依赖 `contracts.py`
- 不出现重复定义的数据结构

### T4. 实现 `errors.py`

- 定义领域异常
- 明确错误码到模块的映射

完成标准：

- 至少覆盖：
  - `InvalidFormatManifestError`
  - `MissingFinalMarkdownError`
  - `MissingReviewReportError`
  - `ProvenanceLoadError`
  - `OverlapResolutionError`
  - `AssetRelinkError`
  - `PostMergeVerificationError`

### T5. 实现 `pipeline.py` 最小骨架

- 串起：
  - `manifest_loader`
  - 占位追溯加载
  - 占位拼接
  - 占位写出
- 实现 `--overwrite` 行为
- 实现 `--fail-on-manual-review` 与 `--allow-upstream-manual-review` 行为

完成标准：

- 主流程调用顺序固定
- `--overwrite=false` 且目标目录存在时明确失败
- `--overwrite=true` 时允许覆盖既有输出
- 默认存在上游人工复核标记时直接阻断；开启 `--allow-upstream-manual-review=true` 后允许继续

### M1 验收门槛

- CLI 可执行
- 契约和异常模型冻结
- `pipeline.py` 主链路骨架可跑通

---

### M2：主链路与追溯加载

目标：完成从 Phase 3 输入到合并前内存模型的主链路，打通追溯信息加载与切片顺序恢复。

### T6. 实现 `manifest_loader.py`

- 读取 `format_manifest.json`
- 构建 `list[MergeTask]`
- 校验切片顺序、页码范围与文件存在性

完成标准：

- `status!=success` 的切片默认阻断整体验证与合并
- 能恢复稳定的 `order_index`
- 能校验最终 `.md`、`review_report.json`、`assets/` 路径存在性

### T7. 实现 `provenance_loader.py`

- 优先读取 Phase 3 已缓存的追溯索引
- 若无则反向加载 Phase 2 `content.json`
- 构建头尾块窗口

完成标准：

- 能为每个切片生成 `head_blocks` 与 `tail_blocks`
- 能标记 `is_overlap`
- 能为图片和截图类节点补 `asset_ref`
- 结构化追溯缺失时写 `overlap_no_provenance` warning

### T8. 实现 `merge_planner.py`

- 生成相邻切片对
- 生成资源复制与重写计划
- 识别页码断裂

完成标准：

- 只生成 `(i, i+1)` 相邻切片对
- 页码范围不连续时写 `page_gap_detected` warning
- 不允许按文件名字典序推断顺序

### T9. 实现 `pipeline.py` 主链路编排

- `manifest_loader`
- `provenance_loader`
- `merge_planner`
- 占位 `overlap_resolver`
- 占位 `asset_relinker`
- 占位 `stitcher`
- 占位 `postcheck`
- `writer`

完成标准：

- 可在无真正去重逻辑时跑通单文件拼接占位链路
- 日志中输出阶段性耗时
- `MergeResult` 与 `merge_manifest.json` 最小骨架可写出

### M2 验收门槛

- 主链路可从 Phase 3 输入跑到 Phase 4 最小输出
- 追溯加载成功或能稳定降级为 warning
- 切片顺序与页码范围校验可验证

---

### M3：overlap 去重与资源重写

目标：完成 Phase 4 的核心能力，即相邻切片 overlap 去重与资源路径重写。

### T10. 实现 `overlap_resolver.py`

- 以相邻切片头尾窗口为比较范围
- 优先用 `dedupe_key`
- 回退到 `source_page + block_type + normalized_text_hash`
- 图片与截图块使用 `asset_ref`

完成标准：

- 只能删除“可证明相同”的重复块
- 匹配不稳定时不删除正文，只写 `overlap_match_unstable` warning
- 默认删除右侧切片头部重复块

### T11. 实现标题与代码块保护规则

- 标题块不允许仅凭文本相同就删除
- 代码块必须按完整 fenced block 比对

完成标准：

- 章节起始标题不会被误删
- 跨块删除不会把代码块截断

### T12. 实现 `asset_relinker.py`

- 复制 `assets/`
- 改写 Markdown 图片路径
- 改写 HTML `img src`
- 产出 `asset_relinks`

完成标准：

- 复制模式下输出 `assets/<章节目录>/...`
- 改写前后路径映射写入 `merge_report.json`
- 资源缺失或复制失败时写：
  - `asset_path_missing`
  - `asset_copy_failed`

### T13. 实现 `stitcher.py`

- 合并去重后的章节内容
- 处理章节间分隔策略

完成标准：

- 顺序严格遵循 `order_index`
- 默认只插入空行，不额外插入多余结构
- 可选 `thematic_break` 分隔策略生效

### M3 验收门槛

- overlap 重复块可以稳定删除
- 标题和代码块保护规则可验证
- 最终 Markdown 中图片路径可访问
- `merge_report.json` 中存在 `pairs` 和 `asset_relinks`

---

### M4：输出、测试与验收闭环

目标：补齐 writer、postcheck、测试、性能和最终验收要求。

### T14. 实现 `postcheck.py`

- 校验最终 Markdown 非空
- 校验章节顺序
- 校验一级标题数量
- 校验资源路径
- 执行连续重复检测

完成标准：

- 可识别：
  - `heading_count_mismatch`
  - `consecutive_duplicate_detected`
- 高风险问题升级 `manual_review_required=true`

### T15. 实现 `writer.py`

- 写最终 `原文件名.md`
- 写 `merge_report.json`
- 写 `merge_manifest.json`
- 处理资源目录复制

完成标准：

- `merge_manifest.json` 至少包含：
  - `source_file`
  - `merged_md_file`
  - `status`
  - `total_slices`
  - `merged_slices`
  - `removed_overlap_blocks`
  - `warning_count`
  - `total_elapsed_ms`
- `slices[]` 保留 `start_page`、`end_page`

### T16. 完善日志与退出码

- 输出各阶段耗时
- 区分成功、失败、上游阻断

完成标准：

- 至少输出：
  - `manifest_load_ms`
  - `provenance_load_ms`
  - `overlap_resolve_ms`
  - `asset_relink_ms`
  - `stitch_ms`
  - `postcheck_ms`
  - `write_ms`
  - `total_ms`
- `--fail-on-manual-review=true` 时，人工复核结果导致非 0 退出

### T17. 完成测试集

- 单元测试
- 集成测试
- smoke test

完成标准：

- 关键路径测试全部通过
- 异常与降级路径有对应断言

### M4 验收门槛

- 测试通过
- 输出目录结构稳定
- 资源复制和路径改写都可验证
- 在标准环境下，单本 1000 页以内文档合并满足 **10 秒以内** 的目标

---

## 7. 测试计划

### 7.1 单元测试清单

- `test_manifest_loader.py`
  - 合法 / 非法 `format_manifest.json`
  - `status!=success` 阻断
- `test_provenance_loader.py`
  - Phase 3 到 Phase 2 的追溯加载
  - 无追溯信息时的 warning
- `test_merge_planner.py`
  - 相邻切片对生成
  - 页码断裂识别
- `test_overlap_resolver.py`
  - `dedupe_key` 精确去重
  - 文本哈希回退匹配
  - 标题保护
  - 代码块保护
- `test_asset_relinker.py`
  - Markdown 图片路径改写
  - HTML `img` 路径改写
  - `asset_relinks` 输出
- `test_stitcher.py`
  - 章节顺序拼接
  - 分隔策略
- `test_postcheck.py`
  - 标题数量校验
  - 连续重复检测
  - 资源路径校验
- `test_writer.py`
  - `merge_report.json`
  - `merge_manifest.json`
  - `slices[].start_page/end_page`
- `test_pipeline_smoke.py`
  - CLI 主链路
  - `--overwrite`
  - `--fail-on-manual-review`
  - `--allow-upstream-manual-review`

### 7.2 集成测试样本

至少准备以下样本：

- 样本 A：正常带 overlap 的章节切片
- 样本 B：含图片资源的章节切片
- 样本 C：含复杂表格截图的章节切片
- 样本 D：带上游人工复核标记的章节切片
- 样本 E：缺失切片或页码断裂样本

### 7.3 smoke test

执行命令：

```bash
python phase4_merge.py --input-dir <format_dir> --output-dir <merge_dir> --copy-assets
```

验证项：

- 进程退出码正确
- 输出目录结构正确
- 最终 `.md`、`merge_report.json`、`merge_manifest.json` 均生成
- 资源路径可以正常访问

---

## 8. 开发顺序约束

为避免返工，开发必须按以下顺序执行，不允许跳步：

1. `requirements.txt`
2. `config.py`
3. `contracts.py`
4. `errors.py`
5. `manifest_loader.py`
6. `provenance_loader.py`
7. `merge_planner.py`
8. `pipeline.py` 最小版
9. `overlap_resolver.py`
10. `asset_relinker.py`
11. `stitcher.py`
12. `postcheck.py`
13. `writer.py`
14. 测试补齐

原因：

- 先冻结契约，再写功能
- 先打通主链路，再补核心去重
- 先完成输出闭环，再做性能和验收收口

---

## 9. DoD（完成定义）

单个任务完成，必须同时满足：

- 代码已实现
- 对应测试已补齐
- 输出结构符合技术方案
- 无新增未解释字段
- 错误处理与日志完整

Phase 4 整体完成，必须同时满足：

- 四个里程碑全部达成
- 所有关键测试通过
- 最终产物可直接交付
- 对上游异常、追溯缺失、资源缺失、重复不稳定等场景有稳定行为

---

## 10. 风险与预案

### 风险 1：追溯信息缺失导致 overlap 无法稳定去重

预案：

- `dedupe_key` 优先
- 无结构化追溯时降级为 warning
- 不稳定时宁可保留重复，不误删正文

### 风险 2：图片或截图资源在复制后断链

预案：

- 统一由 `asset_relinker.py` 处理
- 改写后做路径校验
- 写入 `asset_relinks`

### 风险 3：章节边界误删标题

预案：

- 标题块不做纯文本删除
- 必须结合 `source_page` 与位置判断
- 对起始标题启用保护规则

### 风险 4：拼接后仍残留明显连续重复

预案：

- `postcheck.py` 做连续重复检测
- 输出 `consecutive_duplicate_detected`
- 默认不自动继续删除，避免二次误删

---

## 11. 并行开发建议

若需要多人并行，可按以下边界拆分：

- 开发者 A：`contracts.py`、`config.py`、`errors.py`、`manifest_loader.py`
- 开发者 B：`provenance_loader.py`、`merge_planner.py`
- 开发者 C：`overlap_resolver.py`
- 开发者 D：`asset_relinker.py`、`stitcher.py`、`postcheck.py`、`writer.py`、CLI 与 `pipeline.py`

并行前提：

- 必须先冻结 `contracts.py`
- `warning_type`、`status`、`match_strategy` 枚举不得并行修改
- 合流前先跑 smoke test

---

## 12. 执行建议

建议后续编码采用以下节奏：

- 第 1 轮：完成 M1
- 第 2 轮：完成 M2
- 第 3 轮：完成 M3
- 第 4 轮：完成 M4 与验收收口

每一轮结束后，先跑对应测试并更新文档，再进入下一轮。

---

## 13. 结论

这份开发计划的核心原则是：

- 先契约，后实现
- 先主链路，后去重增强
- 先保证不误删，再追求去重充分
- 所有自动去重、资源重写和阻断行为都必须可追溯

后续 Phase 4 的编码应严格按本计划推进，不应直接从字符串拼接开始跳过追溯与校验链路，否则会失去“可证明正确合并”的核心价值。

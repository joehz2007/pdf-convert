# 开发计划：Markdown 格式化模块（Phase 3）

## 1. 目的

本开发计划严格基于以下文档执行：

- [PRD-PDF切分需求.md](D:\projects01\pdf-convert\docs\PRD-PDF切分需求.md)
- [技术方案-Markdown格式化(Phase3).md](D:\projects01\pdf-convert\docs\技术方案-Markdown格式化(Phase3).md)

后续 Phase 3 的编码、测试、评审与验收，统一以本计划为执行基线。若实现过程中需要调整边界、数据结构、模块职责或输出契约，必须先更新技术方案与本开发计划，再进入编码。

---

## 2. 范围与约束

### 2.1 当前范围

- 输入来自 Phase 2 输出目录：
  - `extract_manifest.json`
  - draft `.md`
  - `content.json`
  - `assets/`
- 输出：
  - 同名最终 `.md`
  - `review_report.json`
  - `format_manifest.json`
  - `assets/`（复制或复用）

### 2.2 明确不做

- 不重新抽取 PDF 内容
- 不引入 OCR
- 不做 LLM 改写、润色、翻译、摘要
- 不在本阶段做 Phase 4 合并与 overlap 去重
- 不接受脱离 `content.json` 的孤立 Markdown 文件直接格式化

### 2.3 技术约束

- Python 版本：`3.10+`
- 依赖必须写入 `requirements.txt`
- `markdown-it-py`、`mdformat`、`mdformat-gfm` 必须锁定版本
- `markdown-it-py` 必须使用 `MarkdownIt("gfm-like")`
- `content.json` 是完整性对账的唯一事实来源
- `md_normalizer.py` 不允许删除内容块
- 对外输出顺序必须保持与 Phase 2 切片顺序一致
- `--copy-assets` 默认 `true`
- `--copy-assets=false` 时必须显式改写图片引用路径，并在输出中标记 `asset_mode=reuse_phase2`

---

## 3. 总体实施策略

采用“先冻结契约，再打通主链路，再补齐修复能力，最后做稳定性收口”的顺序推进，分为 4 个里程碑：

1. **M1 项目骨架与契约冻结**
2. **M2 完整性对账链路**
3. **M3 修复、渲染与标准化**
4. **M4 输出、测试与验收闭环**

任何里程碑未达到完成标准，不进入下一阶段。

### 3.1 预估工期

- `M1 项目骨架与契约冻结`：1.0 天
- `M2 完整性对账链路`：2.0 天
- `M3 修复、渲染与标准化`：2.0 天
- `M4 输出、测试与验收闭环`：1.5 天

总预估工期：**6.5 个开发日**

---

## 4. 推荐代码结构

建议新增如下目录结构：

```text
D:\projects01\pdf-convert\
  requirements.txt
  phase3_format.py
  src\
    md_format\
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
  tests\
    test_manifest_loader.py
    test_coverage_auditor.py
    test_block_aligner.py
    test_repair_engine.py
    test_renderer.py
    test_md_normalizer.py
    test_postcheck.py
    test_writer.py
    test_pipeline_smoke.py
  docs\
    技术方案-Markdown格式化(Phase3).md
    开发计划-Markdown格式化(Phase3).md
```

说明：

- `phase3_format.py` 仅做 CLI 入口
- `pipeline.py` 负责主流程编排
- `config.py` 负责阈值、路径策略、默认开关和日志键名
- `contracts.py` 统一定义 `FormatTask`、`AuditIssue`、`NormalizedDocument`、`FormatResult`
- 所有模块不得绕开 `contracts.py` 自行定义同名结构

---

## 5. 数据契约先行

编码开始前，必须先冻结以下数据模型与枚举。

### 5.1 核心数据模型

- `FormatTask`
- `AuditIssue`
- `NormalizedBlock`
- `NormalizedPage`
- `NormalizedDocument`
- `FormatResult`
- `ReviewReport`
- `FormatManifest`

### 5.2 字段要求

#### `FormatTask`

最低字段：

- `slice_file`
- `display_title`
- `order_index`
- `input_dir`
- `content_file`
- `draft_md_file`
- `assets_dir`
- `phase2_manual_review_required`

#### `AuditIssue`

最低字段：

- `issue_type`
- `severity`
- `source_page`
- `reading_order`
- `node_ref`
- `message`
- `auto_fixable`

`severity` 允许值：

- `error`
- `warning`
- `info`

`issue_type` 允许值：

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

#### `NormalizedDocument`

最低字段：

- `slice_file`
- `display_title`
- `order_index`
- `start_page`
- `end_page`
- `pages`
- `warnings`
- `phase2_manual_review_required`
- `phase3_manual_review_required`
- `metadata`

#### `FormatResult`

最低字段：

- `slice_file`
- `final_md_file`
- `review_report_file`
- `status`
- `warning_count`
- `issue_count`
- `auto_fixed_count`
- `manual_review_required`
- `elapsed_ms`

`status` 允许值：

- `success`
- `failed`
- `skipped_upstream_failed`

### 5.3 契约规则

- `node_ref` 规则必须统一：
  - 普通块使用 `dedupe_key`
  - 表格使用 `table:{source_page}:{local_index}`
  - 图片使用 `image:{source_page}:{local_index}`
- `pages` 必须按 `source_page ASC`
- `blocks` 必须按 `reading_order ASC`
- `review_report.json` 必须包含：
  - `coverage`
  - `formatted_stats`
  - `issues`
  - `auto_fixes`
- `format_manifest.json` 必须包含：
  - 全局统计
  - 切片顺序信息
  - 切片页码范围
  - `asset_mode`

---

## 6. 里程碑与任务拆解

### M1：项目骨架与契约冻结

目标：完成目录、依赖、CLI、契约和最小编排骨架，为后续功能开发提供稳定基线。

### T1. 建立项目骨架

- 新增 `requirements.txt`
- 新增 `src/md_format/`
- 新增 `phase3_format.py`
- 新增基础测试目录
- 实现 CLI 参数定义：
  - `--input-dir`
  - `--output-dir`
  - `--workers`
  - `--overwrite`
  - `--fail-on-manual-review`
  - `--copy-assets`

完成标准：

- `phase3_format.py --help` 可执行
- `requirements.txt` 明确锁定 `markdown-it-py`、`mdformat`、`mdformat-gfm`
- 目录结构与开发计划一致
- CLI 参数帮助文本完整

### T2. 实现 `config.py`

- 定义默认参数
- 定义覆盖率阈值
- 定义 `asset_mode` 与路径策略
- 定义日志耗时键

完成标准：

- 所有阈值集中在 `config.py`
- 模块内不得写死重复常量

### T3. 实现 `contracts.py`

- 定义所有 dataclass / TypedDict / Enum / Literal
- 固化 `status`、`severity`、`fix_type` 枚举
- 固化 `issue_type` 枚举
- 固化 `node_ref` 规则

完成标准：

- 所有模块只依赖 `contracts.py`
- 不出现重复定义的数据结构

### T4. 实现 `errors.py`

- 定义领域异常
- 明确错误码到模块的映射

完成标准：

- 至少覆盖：
  - `InvalidExtractManifestError`
  - `MissingContentFileError`
  - `MissingDraftMarkdownError`
  - `InvalidContentSchemaError`
  - `MarkdownParseError`
  - `AssetReferenceError`
  - `PostcheckFailedError`

### T5. 实现 `pipeline.py` 最小骨架

- 串起：
  - `manifest_loader`
  - 占位审计
  - 占位修复
  - 占位写出
- 实现 `--overwrite` 行为：
  - 目标目录存在且 `--overwrite=false` 时明确失败
  - `--overwrite=true` 时允许覆盖既有输出
- 实现 `--fail-on-manual-review` 行为：
  - 存在 `manual_review_required=true` 的切片时，CLI 可按参数决定是否以非零退出

完成标准：

- 主流程调用顺序固定
- 即使暂未完成修复逻辑，也能以占位方式贯通单切片处理链路
- `--overwrite` 与 `--fail-on-manual-review` 的行为可被独立测试

### T5A. 实现切片级并发执行

- 以切片为最小并发单元
- 使用 `--workers` 控制并发度
- 单切片内部保持串行

完成标准：

- `--workers=1` 与 `--workers>1` 的处理结果一致
- 出错切片不影响全局汇总
- 并发执行不破坏切片顺序与输出稳定性

### M1 验收门槛

- CLI 可执行
- 依赖版本已锁定
- 契约和异常模型冻结
- `pipeline.py` 主链路骨架可跑通

---

### M2：完整性对账链路

目标：完成从 Phase 2 输出到审计问题列表的确定性对账能力。

### T6. 实现 `manifest_loader.py`

- 读取 `extract_manifest.json`
- 构建 `list[FormatTask]`
- 处理 `status=success` 与 `status=failed`

完成标准：

- `status=failed` 的切片直接记录为 `skipped_upstream_failed`
- 能恢复稳定的 `order_index`
- 能校验 `content.json` / draft `.md` / `assets/` 路径存在性

### T7. 实现 `coverage_auditor.py`

- 读取 `content.json`
- 建立页面、块、表格、图片覆盖台账
- 输出 `AuditIssue`

完成标准：

- 能检测：
  - `missing_block`
  - `table_render_failed`
  - `image_reference_missing`
  - `overlap_lost`
- 覆盖率阈值来自 `config.py`

### T8. 实现 `block_aligner.py`

- 对 draft Markdown 与 `content.json` 块做映射
- 支持 `dedupe_key`、`normalized_text`、阅读顺序三层对齐

完成标准：

- 正常块优先按 `dedupe_key` 精确对齐
- 同页近似文本可回退到相似度对齐
- 对齐失败能输出明确问题而非静默跳过

### T9. 实现 `node_ref` 生成与引用

- 普通块使用 `dedupe_key`
- 表格和图片使用稳定派生键
- 页级问题允许 `node_ref=null`

完成标准：

- `AuditIssue`、`review_report.json`、`auto_fixes` 使用同一套 `node_ref`
- 不再出现“同一问题在不同模块引用不同 ID”的情况

### T10. 实现最小审计报告输出

- 先写最小版 `review_report.json`
- 包含 `coverage`、`issues`、`warnings`

完成标准：

- 单切片可输出最小审计结果
- 问题数量可被全局汇总

### M2 验收门槛

- 任意一个切片可输出稳定的 `AuditIssue` 列表
- `review_report.json` 最小骨架生成
- 上游失败切片可被稳定跳过
- `node_ref` 规则与技术方案一致

---

### M3：修复、渲染与标准化

目标：完成问题修复、Markdown 渲染、样式标准化与二次校验闭环。

### T11. 实现 `repair_engine.py` 的标题/段落/列表修复

- 修复标题层级
- 修复段落断裂
- 修复列表断裂

完成标准：

- `heading_normalized`
- `heading_inserted`
- `paragraph_merged`
- `list_rebuilt`
  这类 `fix_type` 可以真实落盘

### T12. 实现代码块修复

- 检测未闭合 fence
- 重建缺失代码块
- 保留语言标签

完成标准：

- `code_fence_closed`
- `code_block_rebuilt`
  可被测试覆盖

### T13. 实现表格与图片修复

- 简单表格重建为 GFM pipe table
- 复杂表格保留 `fallback_html` 或 `fallback_image`
- 图片引用缺失时补回
- 图注缺失时回填 `alt`

完成标准：

- `table_rebuilt`
- `table_fallback_html_applied`
- `table_fallback_image_applied`
- `image_reference_restored`
- `image_caption_filled`
  可被稳定输出

### T14. 实现 overlap 修复

- 检测 overlap 页内容丢失
- 把 overlap 块按原顺序插回

完成标准：

- `overlap_block_restored` 可落盘
- Phase 3 不做 overlap 去重

### T15. 实现 `renderer.py`

- 把 `NormalizedDocument` 转为原始 Markdown
- 输出 `render_stats`

完成标准：

- 输出顺序严格遵循 `source_page + reading_order`
- `render_stats` 至少包含：
  - `char_count`
  - `block_count`
  - `table_count`
  - `image_count`

### T16. 实现 `md_normalizer.py`

- 调用 `mdformat`
- 启用 `mdformat-gfm`
- 保持结构不漂移

完成标准：

- 标题、空行、列表缩进、fence 风格统一
- 格式化前后不允许出现块级内容删除

### T17. 实现 `postcheck.py`

- 重新解析最终 Markdown
- 验证结构与覆盖率
- 发现显著漂移时失败

完成标准：

- 格式化前后结构漂移能被识别
- 资源路径可被校验
- overlap 页仍然存在

### M3 验收门槛

- 单切片可完成“修复 -> 渲染 -> 标准化 -> 二次校验”完整闭环
- `auto_fixes` 可输出稳定枚举
- 复杂表格和图片路径场景可被覆盖

---

### M4：输出、测试与验收闭环

目标：补齐 writer、日志、性能、测试与最终验收要求。

### T18. 实现 `writer.py`

- 写最终 `.md`
- 写 `review_report.json`
- 写 `format_manifest.json`
- 处理 `copy` / `reuse_phase2` 两种 `asset_mode`

完成标准：

- `format_manifest.json` 至少包含：
  - `display_title`
  - `order_index`
  - `start_page`
  - `end_page`
  - `status`
  - `formatted_char_count`
  - `formatted_block_count`
  - `asset_mode`
- `--copy-assets=true` 时复制 `assets/`
- `--copy-assets=false` 时改写为指向 Phase 2 `assets/` 的相对路径

### T19. 完善日志与耗时统计

- `manifest_load_ms`
- `coverage_audit_ms`
- `repair_ms`
- `render_ms`
- `postcheck_ms`
- `write_ms`
- `total_ms`

完成标准：

- 每次运行可看到阶段性耗时
- 异常日志能定位到具体模块和切片

### T20. 完成测试集

- 单元测试
- 集成测试
- smoke test

完成标准：

- 关键路径测试全部通过
- 异常与跳过路径有对应断言

### T21. 完成手工验收清单

- 标题层级抽检
- 表格输出抽检
- 图片引用抽检
- overlap 内容抽检
- Phase 2 草稿与 Phase 3 最终版差异抽检

完成标准：

- 形成固定验收 checklist
- 抽检结果可留档

### M4 验收门槛

- 测试通过
- 输出目录结构稳定
- 两种 `asset_mode` 都可验证
- 在标准环境下，20 页以内切片平均处理时间满足 **3 秒以内** 的目标

---

## 7. 测试计划

### 7.1 单元测试清单

- `test_manifest_loader.py`
  - 合法 / 非法 `extract_manifest.json`
  - `status=failed` 跳过
- `test_coverage_auditor.py`
  - 缺失块
  - 缺失表格
  - 缺失图片
  - overlap 丢失
- `test_block_aligner.py`
  - `dedupe_key` 精确对齐
  - 近似文本对齐
- `test_repair_engine.py`
  - 标题修复
  - 段落修复
  - 列表修复
  - 代码块修复
  - 表格修复
  - 图片修复
  - overlap 修复
- `test_renderer.py`
  - 块顺序稳定
  - `render_stats` 输出
- `test_md_normalizer.py`
  - `mdformat-gfm` 生效
  - 表格语法不丢失
- `test_postcheck.py`
  - 结构漂移识别
  - 资源路径校验
- `test_writer.py`
  - `review_report.json`
  - `format_manifest.json`
  - `asset_mode`
- `test_pipeline_smoke.py`
  - CLI 主链路
  - `--copy-assets`
  - `--overwrite`
  - `--fail-on-manual-review`

### 7.2 集成测试样本

至少准备以下样本：

- 样本 A：普通正文切片
- 样本 B：含 GFM 表格切片
- 样本 C：含代码块切片
- 样本 D：含图片与图注切片
- 样本 E：带 overlap 页切片
- 样本 F：Phase 2 `status=failed` 的切片目录

### 7.3 smoke test

执行命令：

```bash
python phase3_format.py --input-dir <extract_dir> --output-dir <format_dir> --workers 1
```

验证项：

- 进程退出码正确
- 输出目录结构正确
- 最终 `.md`、`review_report.json`、`format_manifest.json` 均生成
- 跳过切片会在全局清单中显示 `skipped_upstream_failed`

---

## 8. 开发顺序约束

为避免返工，开发必须按以下顺序执行，不允许跳步：

1. `requirements.txt`
2. `config.py`
3. `contracts.py`
4. `errors.py`
5. `manifest_loader.py`
6. `coverage_auditor.py`
7. `block_aligner.py`
8. `pipeline.py` 最小版
9. `repair_engine.py`
10. `renderer.py`
11. `md_normalizer.py`
12. `postcheck.py`
13. `writer.py`
14. 测试补齐

原因：

- 先冻结契约，再写功能
- 先验证审计，再做修复
- 先完成结构闭环，再做输出和验收

---

## 9. DoD（完成定义）

单个任务完成，必须同时满足：

- 代码已实现
- 对应测试已补齐
- 输出结构符合技术方案
- 无新增未解释字段
- 错误处理与日志完整

Phase 3 整体完成，必须同时满足：

- 四个里程碑全部达成
- 所有关键测试通过
- 产物能被 Phase 4 直接消费
- 对上游失败、资源缺失、复杂表格等异常场景有稳定行为

---

## 10. 风险与预案

### 风险 1：Formatter 版本漂移导致输出不稳定

预案：

- 锁定 `markdown-it-py`、`mdformat`、`mdformat-gfm`
- 在测试中固定格式化前后关键断言

### 风险 2：基于文本对齐的修复误命中

预案：

- `dedupe_key` 优先
- 近似对齐仅作为回退
- 高风险修复升级人工复核

### 风险 3：复杂表格无法稳定 Markdown 化

预案：

- 先保留 `fallback_html`
- 再回退 `fallback_image`
- 严禁静默丢表

### 风险 4：`--copy-assets=false` 导致路径断裂

预案：

- 改写为相对路径
- 在 `postcheck.py` 做路径存在性校验
- 在 `format_manifest.json` 标记 `asset_mode`

### 风险 5：mdformat 改写后结构漂移

预案：

- `postcheck.py` 做二次解析
- 结构漂移直接失败，不默默写出

---

## 11. 并行开发建议

若需要多人并行，可按以下边界拆分：

- 开发者 A：`contracts.py`、`config.py`、`errors.py`、`manifest_loader.py`
- 开发者 B：`coverage_auditor.py`、`block_aligner.py`
- 开发者 C：`repair_engine.py`、`renderer.py`、`md_normalizer.py`
- 开发者 D：`postcheck.py`、`writer.py`、CLI 与 `pipeline.py`

并行前提：

- 必须先冻结 `contracts.py`
- `fix_type`、`status`、`severity` 枚举不得并行修改
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
- 先对账，后修复
- 先保证不丢内容，再统一 Markdown 样式
- 所有格式化动作都必须受 `content.json` 与二次校验约束

后续 Phase 3 的编码应严格按本计划推进，不应绕过审计链路直接做 Markdown 美化，否则会失去“完整性可证明”的核心价值。

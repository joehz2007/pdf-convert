# 开发计划：PDF 内容提取模块（Phase 2）

## 1. 目的

本开发计划严格基于以下文档执行：

- [技术方案-PDF内容提取(Phase2).md](D:\projects01\pdf-convert\docs\技术方案-PDF内容提取(Phase2).md)

后续 Phase 2 的编码、测试、评审与验收，统一以本计划为执行基线。若实现过程中需要调整边界、数据结构或模块职责，必须先更新本计划与对应技术方案，再开始编码。

---

## 2. 范围与约束

### 2.1 当前范围

- 仅支持 **数字原生 / 具备可提取文本层** 的 PDF 切片
- 输入来自 Phase 1 的 `manifest.json` 与切片 PDF
- 输出：
  - 同名 `.md` 草稿文件
  - `content.json`
  - `extract_manifest.json`
  - `assets/` 图片资源

### 2.2 明确不做

- 不建设 OCR 主链路
- 不支持纯扫描 PDF
- 不实现最终精排 Markdown
- 不在本阶段做 Phase 4 的去重合并逻辑，仅输出去重所需元数据

### 2.3 技术约束

- Python 版本：`3.10+`
- 依赖必须写入 `requirements.txt`
- `PyMuPDF` 和 `PyMuPDF4LLM` 必须锁定版本
- 对外展示页码统一使用 **1-based**
- 对接 `PyMuPDF4LLM pages` 参数时，必须显式转换为 **0-based**

---

## 3. 总体实施策略

采用“先打通主链路，再补齐结构化细节”的顺序推进，分为 4 个里程碑：

1. **M1 最小可用链路**
2. **M2 结构化结果落地**
3. **M3 表格与图片增强**
4. **M4 稳定性与验收闭环**

任何里程碑未通过定义的完成标准，不进入下一阶段。

### 3.1 预估工期

- `M1 最小可用链路`：1.5 天
- `M2 结构化结果落地`：1.5 天
- `M3 表格与图片增强`：2.0 天
- `M4 稳定性与验收闭环`：1.0 天

总预估工期：**6.0 个开发日**

---

## 4. 推荐代码结构

建议新增如下目录结构：

```text
D:\projects01\pdf-convert\
  requirements.txt
  phase2_extract.py
  src\
    pdf_extract\
      __init__.py
      config.py
      contracts.py
      errors.py
      manifest_loader.py
      precheck.py
      markdown_extractor.py
      metadata_builder.py
      assets_exporter.py
      writer.py
      pipeline.py
  tests\
    test_manifest_loader.py
    test_precheck.py
    test_markdown_extractor.py
    test_metadata_builder.py
    test_assets_exporter.py
    test_writer.py
    test_pipeline_smoke.py
  docs\
    技术方案-PDF内容提取(Phase2).md
    开发计划-PDF内容提取(Phase2).md
```

说明：

- `phase2_extract.py` 仅做 CLI 入口
- `pipeline.py` 负责主流程编排
- `config.py` 负责默认阈值、目录命名、并发参数和开关配置
- `contracts.py` 统一定义 `SliceTask`、`PageContent`、`ContentResult`
- 所有模块不得绕开 `contracts.py` 自行拼装不一致的数据结构

---

## 5. 数据契约先行

编码开始前，必须先固化以下数据模型。

### 5.1 核心数据模型

- `SliceTask`
- `PageContent`
- `ContentResult`
- `BlockNode`
- `TableNode`
- `ImageNode`
- `ExtractManifest`

### 5.2 字段要求

#### `SliceTask`

最低字段：

- `slice_file`
- `display_title`
- `start_page`
- `end_page`
- `overlap_pages`
- `manual_review_required`

#### `PageContent`

最低字段：

- `slice_page`
- `source_page`
- `is_overlap`
- `markdown`
- `blocks`
- `tables`
- `images`

#### `ContentResult`

最低字段：

- `slice_file`
- `display_title`
- `start_page`
- `end_page`
- `source_pages`
- `assets`
- `stats`
- `warnings`
- `manual_review_required`

#### `BlockNode`

最低字段：

- `type`
- `text`
- `source_page`
- `bbox`
- `reading_order`
- `is_overlap`
- `dedupe_key`

`type` 允许值：

- `heading`
- `paragraph`
- `code`
- `list_item`
- `quote`
- `header`
- `footer`
- `footnote`

#### `TableNode`

最低字段：

- `type`
- `source_page`
- `bbox`
- `table_strategy_used`
- `table_fallback_used`
- `table_retry_pages`
- `headers`
- `rows`
- `markdown`
- `fallback_html`
- `fallback_image`

#### `ImageNode`

最低字段：

- `type`
- `source_page`
- `bbox`
- `asset_path`
- `width`
- `height`
- `caption`

### 5.3 契约规则

- `content.json` 中每页必须同时包含：
  - `markdown`
  - `blocks`
  - `tables`
  - `images`
- `extract_manifest.json` 必须同时包含：
  - 全局统计
  - 每切片状态
- `stats` 最低必须包含：
  - `char_count`
  - `table_count`
  - `image_count`
- `dedupe_key` 生成规则严格遵循技术方案，不允许各模块各自实现不同版本

---

## 6. 里程碑与任务拆解

## M1：最小可用链路

目标：完成从 Phase 1 输入到同名 `.md` 输出的最短闭环。

### T1. 建立项目骨架

- 新增 `requirements.txt`
- 新增 `src/pdf_extract/`
- 新增 `phase2_extract.py`
- 新增 `config.py`
- 新增基础测试目录
- 实现 CLI 参数定义：
  - `--input-manifest`
  - `--output-dir`
  - `--emit-md`
  - `--workers`
  - `--overwrite`

完成标准：

- 目录结构落盘
- `phase2_extract.py --help` 可执行
- `requirements.txt` 明确锁定 `PyMuPDF`、`PyMuPDF4LLM`
- CLI 参数帮助文本完整

### T2. 实现 `contracts.py`

- 定义所有 dataclass / TypedDict / Enum
- 固化页码基准规则
- 固化异常枚举

完成标准：

- 所有下游模块仅依赖 `contracts.py`
- 不出现重复定义的数据结构

### T3. 实现 `manifest_loader.py`

- 读取 Phase 1 `manifest.json`
- 转换为 `list[SliceTask]`
- 完成基础字段校验

完成标准：

- 无效 `manifest.json` 能给出明确异常
- overlap 页范围校验正确

### T4. 实现 `precheck.py`

- 校验 PDF 是否可打开
- 校验页数是否大于 0
- 校验是否具备有效文本层

完成标准：

- 基于 `page.get_text("text")` 与 `page.get_text("words")` 做逐页统计
- 使用“有效词数或有效字符数低于阈值”规则判定 `unsupported_input`
- 阈值写入 `config.py`
- 对纯扫描 PDF 直接抛 `unsupported_input`
- 不生成任何部分输出

### T5. 实现 `markdown_extractor.py`

- 使用 `PyMuPDF4LLM.to_markdown()`
- 输出 `page_chunks=True`
- 默认 `table_strategy="lines_strict"`

完成标准：

- 能基于单个切片返回页级 Markdown chunks
- 页顺序正确
- 不写图片到磁盘

### T6. 实现 `pipeline.py` 最小编排

流程限定为：

- `manifest_loader`
- `precheck`
- `markdown_extractor`
- 简版 `writer`
- `--emit-md` 控制是否写出 Markdown
- `--overwrite` 控制目标目录已存在时的覆盖行为

完成标准：

- 主流程调用顺序固定且可测试
- `--emit-md=false` 时不写出 Markdown，但不影响 `content.json` / `extract_manifest.json`
- `--overwrite=false` 且目标目录已存在时明确失败
- `--overwrite=true` 时允许覆盖既有输出

### T6A. 实现切片级并发执行

- 以切片为最小并发单元
- 用 `--workers` 控制并发度
- 保证单切片内部仍为串行处理

完成标准：

- 单个切片可产出同名 `.md`
- 多切片可批量运行
- 出错切片不影响总体状态汇总
- `--workers=1` 与 `--workers>1` 的行为一致

### T7. 实现 `writer.py` 最小版本

- 写 `.md`
- 拷贝 `source.pdf`
- 写基础版 `extract_manifest.json`
- 生成编号目录，如 `001-第一章-系统概述/`

完成标准：

- 输出目录结构符合技术方案
- `source.pdf` 已落盘
- `extract_manifest.json` 包含全局计数和切片级状态

### M1 验收门槛

- 至少 1 份数字原生 PDF 样本全链路成功
- `phase2_extract.py --help` 可用
- `.md` 文件命名与切片同名
- `extract_manifest.json` 结构可被后续模块消费

---

## M2：结构化结果落地

目标：输出稳定的 `content.json`，打通 Markdown 与元数据的合流。

### T8. 实现 `metadata_builder.py`

- 接收 page chunks
- 使用 PyMuPDF 读取块结构
- 构建 `PageContent`
- 生成 `ContentResult`
- 计算 `stats`
- 落实 `manual_review_required` 触发规则

完成标准：

- `metadata_builder` 成为唯一合流点
- `writer` 不再自己拼接数据
- `stats` 至少包含 `char_count`、`table_count`、`image_count`
- 人工复核标记逻辑可被测试覆盖

### T9. 实现普通块提取

- `page.get_text("blocks", sort=True)`
- 生成 `BlockNode`
- 计算 `reading_order`

完成标准：

- 每页 `blocks` 非空时结构完整
- `type` 字段统一

### T10. 实现 `dedupe_key`

- 严格按技术方案做文本归一化
- 输出 `normalized_text_hash`
- 拼装 `dedupe_key`

完成标准：

- 相同物理块稳定生成相同键
- 不同块不会大面积碰撞

### T11. 在 `content.json` 中落盘完整页结构

- 每页包含 `markdown / blocks / tables / images`
- 记录 `is_overlap`

完成标准：

- `content.json` 骨架完全符合技术方案
- writer 只序列化 `ContentResult`

### M2 验收门槛

- 任意一个切片的 `content.json` 结构完整
- `blocks` 节点字段齐全
- `dedupe_key` 已生成
- `extract_manifest.json` 全局统计准确

---

## M3：表格与图片增强

目标：补齐 Phase 2 中最容易丢失信息的两个区域。

### T12. 实现表格检测与节点落盘

- 使用 `page.find_tables()`
- 生成 `TableNode`
- 输出 `headers / rows / markdown`

完成标准：

- 常规表格可落成 `TableNode`
- `table_strategy_used` 可追踪

### T13. 实现表格回退策略

- 首次用 `lines_strict`
- 当 `page.find_tables()` 返回数量大于 0，且该页 chunk 中未出现 Markdown 表格特征时，判定为失败页
- 命中失败页后按页单独用 `pages=[source_page - 1]` 回退 `lines`
- 合并回 `base_chunks`

完成标准：

- 页级重试逻辑真实生效
- `table_fallback_used` 落盘
- `table_retry_pages` 落盘

### T14. 实现 `assets_exporter.py`

- 提取图片资源
- 生成稳定命名
- 返回 `ImageNode`

完成标准：

- 图片成功写入 `assets/`
- `asset_path` 可直接被 Markdown 引用

### T15. 实现图注绑定

- 基于图片下方最近文本块匹配
- 绑定为 `caption`

完成标准：

- 常见图注样式可被识别
- 失败时写 warning，而不是静默丢失

### T16. 实现复杂表格回退

- 无法稳定 Markdown 化时：
  - 写 `fallback_html`
  - 或导出截图写 `fallback_image`

完成标准：

- 复杂表格不会静默消失

### M3 验收门槛

- 含表格 PDF 能输出 `TableNode`
- 含图片 PDF 能输出 `ImageNode`
- 页级表格回退逻辑可验证
- 图注绑定有明确成功/失败记录

---

## M4：稳定性与验收闭环

目标：补齐日志、错误处理、测试和最终开发门槛。

### T17. 完善错误模型

- 统一异常类
- 统一错误码
- 区分：
  - `missing_slice`
  - `invalid_manifest`
  - `unsupported_input`
  - `empty_extraction`
  - `page_mapping_error`
  - `asset_export_failed`

完成标准：

- 所有异常都能定位到模块
- CLI 返回码可区分成功/失败

### T18. 完善 `extract_manifest.json`

- 增加：
  - `total_slices`
  - `success_count`
  - `failed_count`
  - `total_warnings`
  - `total_elapsed_ms`
- 补齐切片级字段：
  - `content_file`
  - `md_file`
  - `status`
  - `warning_count`
  - `manual_review_required`
  - `elapsed_ms`

完成标准：

- 可从全局汇总判断一次运行是否可用
- 单切片状态足够支撑 Phase 3/4 消费

### T19. 增加日志与耗时统计

- `manifest_load_ms`
- `precheck_ms`
- `markdown_extract_ms`
- `metadata_build_ms`
- `write_ms`
- `total_ms`

完成标准：

- 每次执行可输出阶段性耗时

### T20. 完成测试集

- 单元测试
- 集成测试
- smoke test

完成标准：

- 关键路径测试全部通过

### M4 验收门槛

- 测试通过
- 对不支持输入能稳定失败
- 输出目录结构稳定
- 文档、CLI、测试结果一致
- 在标准环境下，20 页切片平均处理时间满足 **5 秒以内** 的目标

---

## 7. 测试计划

### 7.1 单元测试清单

- `test_manifest_loader.py`
  - 合法 manifest
  - 缺字段 manifest
  - overlap 页越界
- `test_precheck.py`
  - 正常文本层 PDF
  - 空文本层 PDF
- `test_markdown_extractor.py`
  - `page_chunks` 返回结构
  - 表格回退页级重试
- `test_metadata_builder.py`
  - `blocks` 结构
  - `dedupe_key`
  - `ContentResult` 合流
  - `manual_review_required` 触发条件
- `test_assets_exporter.py`
  - 图片导出
  - 命名规则
- `test_writer.py`
  - `content.json`
  - `extract_manifest.json`
- `test_pipeline_smoke.py`
  - CLI 主链路可执行
  - `--emit-md`
  - `--overwrite`
  - `--workers`

### 7.2 集成测试样本

至少准备以下样本：

- 样本 A：纯正文数字 PDF
- 样本 B：含表格的数字 PDF
- 样本 C：含图片和图注的数字 PDF
- 样本 D：无文本层扫描 PDF

### 7.3 smoke test

执行命令：

```bash
python phase2_extract.py --input-manifest <manifest.json> --output-dir <dir> --emit-md
```

验证项：

- 进程退出码正确
- 输出目录结构正确
- `.md`、`content.json`、`extract_manifest.json` 均生成

---

## 8. 开发顺序约束

为避免返工，开发必须按以下顺序执行，不允许跳步：

1. `requirements.txt`
2. `config.py`
3. `contracts.py`
4. `manifest_loader.py`
5. `precheck.py`
6. `markdown_extractor.py`
7. `writer.py` 最小版
8. `pipeline.py`
9. `metadata_builder.py`
10. `dedupe_key`
11. `assets_exporter.py`
12. 表格回退与复杂表格处理
13. 测试补齐

原因：

- 先固化契约，后写功能
- 先打通输出，后补强结构
- 先主链路，后增强能力

---

## 9. DoD（完成定义）

单个任务完成，必须同时满足：

- 代码已实现
- 对应测试已补齐
- 输出结构符合技术方案
- 无新增未解释字段
- 错误处理与日志完整

Phase 2 整体完成，必须同时满足：

- 四个里程碑全部达成
- 所有关键测试通过
- 产物能被 Phase 3 直接消费
- 对不支持输入稳定失败

---

## 10. 风险与预案

### 风险 1：PyMuPDF4LLM 输出格式版本漂移

预案：

- 锁定版本
- 在测试中固定 page chunk 结构断言

### 风险 2：表格识别不稳定

预案：

- 页级回退
- HTML 回退
- 截图回退

### 风险 3：图片图注绑定误判

预案：

- 仅做近邻绑定
- 绑定失败时输出 warning，不做强绑定

### 风险 4：页码基准混乱

预案：

- 项目内部统一 1-based
- 所有调用 `pages` 参数时显式 `-1`
- 在测试中加入页码偏移断言

---

## 11. 并行开发建议

若需要多人并行，可按以下边界拆分：

- 开发者 A：`contracts.py`、`manifest_loader.py`、`precheck.py`
- 开发者 B：`markdown_extractor.py`、表格回退逻辑
- 开发者 C：`metadata_builder.py`、`assets_exporter.py`
- 开发者 D：`writer.py`、`pipeline.py`、CLI 参数与并发执行

并行前提：

- 必须先冻结 `contracts.py`
- 目录结构和输出契约不得并行修改
- 合流前先跑 smoke test

---

## 12. 执行建议

建议后续编码采用以下节奏：

- 第 1 轮：完成 M1
- 第 2 轮：完成 M2
- 第 3 轮：完成 M3
- 第 4 轮：完成 M4 与测试收口

每一轮结束后，先跑对应测试并更新文档，再进入下一轮。

---

## 13. 结论

这份开发计划的核心原则是：

- 先契约，后实现
- 先主链路，后增强
- 先保证可用，再追求丰富
- 所有增强能力都必须以不破坏主链路为前提

后续 Phase 2 的编码应严格按本计划推进，不应直接跳到图片、表格或复杂优化，而绕过主链路与数据契约。

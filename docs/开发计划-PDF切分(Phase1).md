# 开发计划：大型 PDF 转 MD 项目 - Phase 1（PDF 切分）

## 1. 计划目标

本开发计划严格基于以下两份文档制定，并作为后续编码阶段的唯一执行基线：

- [PRD-PDF切分需求.md](./PRD-PDF切分需求.md)
- [技术方案-PDF切分(Phase1).md](./技术方案-PDF切分(Phase1).md)

当前范围仅实现 **Phase 1：数字文档的 PDF 结构化切分**，明确边界如下：

- 支持：数字原生 PDF、具备可提取文本层的 PDF
- 不支持：扫描版 PDF、无有效文本层 PDF、OCR 场景
- 不建设 OCR 主链路
- 所有对外页码统一为 **1-based**
- `document.py` 是唯一允许执行 0-based 到 1-based 页码转换的模块

---

## 2. 交付目标

Phase 1 完成后，系统应交付以下能力：

1. 通过 CLI 接收输入 PDF 并完成预检
2. 自动识别顶层章节，并在无 TOC 时执行降级识别
3. 基于页数规则、语义完整性规则和过渡页规则生成切分计划
4. 输出切片 PDF 文件到 `<源文件名>_split/`
5. 输出结构化清单 `manifest.json`
6. 输出分阶段性能日志
7. 具备单元测试、集成测试和基本黑盒验收能力

---

## 3. 代码结构规划

建议落地结构如下：

```text
pdf-convert/
  split_pdf.py
  requirements.txt
  pdf_slicer/
    __init__.py
    models.py
    errors.py
    log_utils.py
    document.py
    recognizer.py
    semantic_analyzer.py
    split_planner.py
    writer.py
  tests/
    test_document.py
    test_recognizer.py
    test_semantic_analyzer.py
    test_split_planner.py
    test_writer.py
    test_cli.py
  docs/
    test_samples/
```

模块职责约束：

- `models.py`：统一定义 `ChapterNode`、`SlicePlan`
- `document.py`：统一 PDF 访问、异常拦截、文本层预检、页码转换
- `recognizer.py`：章节识别与降级分流
- `semantic_analyzer.py`：F3 语义完整性守护
- `split_planner.py`：F2/F4 切分规划与超限异常处理
- `writer.py`：PDF 切片写盘、命名、输出目录、`manifest.json`
- `split_pdf.py`：CLI 编排与分阶段计时

---

## 4. 里程碑计划

### M0：项目初始化

目标：建立可编码、可测试、可运行的最小工程骨架。

任务：

1. 创建项目目录结构
2. 创建 `requirements.txt`
3. 配置 `pytest`
4. 实现 `pdf_slicer/log_utils.py`
5. 配置基础日志输出
6. 创建空 CLI 入口 `split_pdf.py`

`log_utils.py` 负责：

- 日志格式初始化
- 日志级别配置
- 分阶段计时工具封装
- 统一输出 `precheck_ms`、`structure_detect_ms`、`layout_analysis_ms`、`split_write_ms`、`total_ms`

完成标准：

- 仓库结构创建完成
- 测试框架可执行
- CLI 可运行并输出基础帮助信息

预估工期：`0.5 天`

---

### M1：基础设施层

目标：先稳定输入边界与页码基准，为后续所有模块提供统一基础。

任务：

1. 实现 `pdf_slicer/models.py`
2. 实现 `pdf_slicer/errors.py`
3. 实现 `pdf_slicer/document.py`
4. 补充 `tests/test_document.py`

实现要点：

- `ChapterNode`、`SlicePlan` 所有页码均为 1-based
- `document.py` 内部读取 PyMuPDF 0-based 页码，对外统一转为 1-based
- 拦截文件不存在、损坏、空文件、加密文件、无文本层文件
- 暴露 `get_toc()`、`find_tables()`、`get_text_blocks()`、`get_image_blocks()`

完成标准：

- 页码基准无歧义
- 文本层预检可用
- 文档打开与异常分支有单元测试覆盖

预估工期：`1 天`

---

### M2：章节识别引擎

目标：完成 Level 1 与 Level 2 的章节识别逻辑。

任务：

1. 实现 `pdf_slicer/recognizer.py`
2. 实现 TOC 驱动的章节识别
3. 实现无 TOC 时的正则 + 样式启发式识别
4. 补充 `tests/test_recognizer.py`

实现要点：

- Level 1：通过 TOC 计算章节区间
- 最后一章 `end_page = total_pages`
- Level 2：基于章节编号、字号、加粗、几何位置重建章节边界
- Level 3：对于无文本层输入，直接返回“不支持输入”

完成标准：

- 可生成完整 `List[ChapterNode]`
- 尾章页码计算正确
- 无 TOC 场景有降级识别结果

预估工期：`1.5 天`

---

### M3：语义完整性分析器

目标：实现 F3 的四类边界破坏检测。

任务：

1. 实现 `pdf_slicer/semantic_analyzer.py`
2. 实现 `_has_paragraph_break()`
3. 实现 `_has_table_break()`
4. 实现 `_has_code_break()`
5. 实现 `_has_figure_caption_break()`
6. 补充 `tests/test_semantic_analyzer.py`

实现要点：

- 段落：基于文本块尾部、标点、阅读顺序
- 表格：基于 `page.find_tables()`
- 代码块：基于等宽字体、缩进样式、连续文本块特征
- 图注：基于图片块与下邻近文本块几何关系
- 对外统一暴露 `is_safe_split_boundary(doc, page_num)`

完成标准：

- 四类语义块均有检测方法
- 测试覆盖“允许切分”和“禁止切分”两类结果

预估工期：`2 天`

---

### M4：切分规划器

目标：把章节信息和语义检测结果整合成稳定切分计划。

任务：

1. 实现 `pdf_slicer/split_planner.py`
2. 实现小章向后贪心合并
3. 实现大章按小节拆分
4. 实现 F3 驱动的切分点移动
5. 实现无安全边界时的超限切片兜底
6. 实现 F4 过渡页注入
7. 补充 `tests/test_split_planner.py`

实现要点：

- 只能向后合并，不能向前回溯
- 切分点移动失败时，按 P6 生成超限切片
- 超限切片必须写入：
  - `exception_type`
  - `manual_review_required=true`
  - `boundary_reason=semantic_integrity`
- 相邻切片在章节切换页上必须执行双向冗余

完成标准：

- 能产出最终 `List[SlicePlan]`
- 覆盖正常切分、合并、超限、重叠页四类用例

预估工期：`1.5 天`

---

### M5：输出层

目标：完成切片文件和 `manifest.json` 的稳定输出。

任务：

1. 实现 `pdf_slicer/writer.py`
2. 实现非法字符替换
3. 实现默认输出目录 `<源文件名>_split/`
4. 实现用户指定输出目录覆盖
5. 实现 `manifest.json` 生成
6. 补充 `tests/test_writer.py`

实现要点：

- 文件命名格式：`<章节名>（<起始页>-<结束页>）.pdf`
- 输出目录默认遵循 PRD
- `manifest.json` 字段和枚举必须与 PRD 完全一致
- 所有对外页码输出均为 1-based

完成标准：

- 可成功生成切片 PDF
- `manifest.json` 结构正确、字段完整
- 输出目录规则正确

预估工期：`1 天`

---

### M6：CLI 集成

目标：打通端到端执行链路。

任务：

1. 实现 `split_pdf.py`
2. 参数解析
3. 模块编排
4. 日志与性能计时
5. 补充 `tests/test_cli.py`

建议参数：

- `input.pdf`
- `--output-dir`
- `--max-pages`
- `--help`

计时键要求：

- `precheck_ms`
- `structure_detect_ms`
- `layout_analysis_ms`
- `split_write_ms`
- `total_ms`

完成标准：

- CLI 可跑通完整链路
- 帮助信息齐全
- 错误提示清晰
- 日志包含所有计时项

预估工期：`1 天`

---

### M7：集成验收与性能校准

目标：完成 Phase 1 的交付前验证。

任务：

1. 准备测试样本
2. 执行黑盒测试
3. 记录性能数据
4. 输出验收结论

样本要求：

1. 带 TOC 的数字原生 PDF
2. 无 TOC 但有文本层的 PDF
3. 无文本层/扫描版 PDF

验收重点：

- 文件命名正确
- 页码范围正确
- 重叠页正确保留
- 段落/表格/代码块/图注不被错误截断
- `manifest.json` 可被 Phase 2 消费
- Level 1 / Level 2 性能满足要求

预估工期：`1-1.5 天`

---

## 5. 依赖关系与执行顺序

必须严格按以下顺序推进：

1. `M0 -> M1`
2. `M1 -> M2 + M3`
3. `M2 + M3 -> M4`
4. `M4 -> M5`
5. `M5 -> M6`
6. `M6 -> M7`

约束说明：

- 未完成 `M1`，禁止开始 `split_planner.py`
- 未完成 `M3` 四类语义测试，禁止进行端到端联调
- 未确认 `manifest.json` 与 PRD 对齐，禁止冻结 writer 输出

---

## 6. 并行开发建议

若有 2 名开发者，可按以下方式并行：

### 开发者 A

- M1：`document.py`、`models.py`、`errors.py`
- M2：`recognizer.py`
- M4：`split_planner.py`
- M6：`split_pdf.py`

### 开发者 B

- M3：`semantic_analyzer.py`
- M5：`writer.py`
- M7：测试样本与黑盒验证

### 合流节点

合流 1：

- `M1` 完成后，统一页码基准与异常模型

合流 2：

- `M2`、`M3` 完成后，由开发者 A 接手 `M4 split_planner.py`

合流 3：

- `M4`、`M5` 完成后，进行 CLI 串联

---

## 7. 测试计划

### 单元测试

- `test_document.py`
  - 文件打开
  - 空文件/加密/损坏/无文本层
  - 页码转换
- `test_recognizer.py`
  - TOC 识别
  - 尾章页码
  - 无 TOC 降级识别
- `test_semantic_analyzer.py`
  - 段落截断
  - 表格截断
  - 代码块截断
  - 图注截断
- `test_split_planner.py`
  - 向后贪心合并
  - 大章拆分
  - 安全边界移动
  - 超限切片
  - 过渡页重叠
- `test_writer.py`
  - 默认输出目录
  - 文件命名
  - manifest 字段
- `test_cli.py`
  - `--help`
  - 非法输入
  - 正常执行

### 集成测试

1. 数字原生 PDF 带 TOC
2. 数字原生 PDF 无 TOC
3. 含表格和图片的数字 PDF
4. 无文本层 PDF

### 人工验收

1. 抽查章节边界是否正确
2. 抽查表格和代码块是否被错误截断
3. 抽查图注是否与图片保持同一切片
4. 抽查重叠页是否在前后切片同时出现
5. 抽查 `manifest.json` 是否满足 Phase 2 消费需求

---

## 8. 风险与应对

### 风险 1：无 TOC 文档的章节识别误判

应对：

- 将正则和样式启发式拆开实现
- 输出日志标记当前 fallback level
- 通过测试样本不断校正规则

### 风险 2：语义块判断误伤切分边界

应对：

- 段落/表格/代码/图注分别建独立检测函数
- 所有规则先单测后集成
- 无安全边界时统一走超限切片兜底，不做隐式强切

### 风险 3：页码 0-based / 1-based 混用

应对：

- 所有模型统一 1-based
- 仅 `document.py` 做转换
- 相关测试必须覆盖首页、尾页、尾章

### 风险 4：`manifest.json` 与 Phase 2 契约漂移

应对：

- Phase 1 输出字段冻结前，对照 Phase 2 文档核验
- writer 测试显式校验字段名、枚举值和页码口径

---

## 9. 交付门禁

满足以下条件后，Phase 1 才可视为进入可交付状态：

1. 所有里程碑编码完成
2. 单元测试全部通过
3. 集成测试全部通过
4. `manifest.json` 与技术方案、PRD 一致
5. CLI 参数与日志满足验收要求
6. Level 1 / Level 2 性能达到 PRD 指标

---

## 10. 建议提交节奏

建议按以下提交顺序推进：

1. `chore: init phase1 project skeleton`
2. `feat: add document layer and shared models with unit tests`
3. `feat: implement recognizer with toc and fallback detection plus tests`
4. `feat: implement semantic analyzer for paragraph table code and figure-caption plus tests`
5. `feat: implement split planner with overlap and oversized fallback plus tests`
6. `feat: implement writer and manifest output plus tests`
7. `feat: wire cli orchestration and staged timing logs plus cli tests`
8. `test: add integration and blackbox validation for phase1`

提交规则：

- 每个 `feat` 提交必须自带对应单元测试
- 不允许将所有单元测试压到最后一次提交
- 仅 `M7` 的集成测试与黑盒验收记录作为独立测试提交

---

## 11. 结论

本计划可直接作为后续编码阶段的执行依据，实施顺序为：

`M0 初始化 -> M1 基础设施 -> M2 章节识别 + M3 语义分析 -> M4 切分规划 -> M5 输出层 -> M6 CLI 集成 -> M7 验收`

后续编码必须严格遵循本计划，不得跳过基础设施与测试阶段直接进入端到端实现。

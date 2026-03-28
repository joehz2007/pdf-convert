# 技术实施方案 (Implementation Plan)：大型 PDF 转 MD 项目 - Phase 2

## 1. 目标与范围

基于 [PRD-PDF切分需求.md](D:\projects01\pdf-convert\docs\PRD-PDF切分需求.md) 与当前收敛后的实施范围，Phase 2 的职责定义如下：

- 消费 Phase 1 产出的切片 PDF 与 `manifest.json`
- 面向**数字原生/具备可提取文本层的 PDF 切片**执行内容提取
- 输出与切片 PDF 同名的 Markdown 文件
- 同步输出结构化元数据，供 Phase 3 校对与 Phase 4 合并使用

当前阶段**不建设 OCR 主链路**。因此本期范围明确为：

- 支持：数字原生 PDF、带可提取文本层的 PDF
- 不支持：纯扫描 PDF、无有效文本层 PDF、需要 OCR 才能读取正文的 PDF

对于不支持输入，Phase 2 应在切片级记录明确错误并继续处理其他切片；失败切片不生成该切片产物，但整批任务仍输出 `extract_manifest.json` 用于汇总状态。

---

## 2. Phase 2 与 Phase 3 的职责边界

为避免后续开发重复，采用如下边界定义：

### Phase 2：内容提取

- 负责从 PDF 中**确定性提取**内容
- 负责生成**草稿版 Markdown**
- 负责保留页码、块顺序、表格结构、图片引用、重叠页标记等可追溯信息
- 不负责高质量精排，不负责人工修辞级修正

### Phase 3：校对与格式修正

- 负责检查 Markdown 是否完整、是否有遗漏
- 负责修正标题层级、列表、表格、代码块等格式问题
- 负责基于 `content.json` 做完整性对账
- 负责对草稿 Markdown 做最终发布前清洗

### 结论

Phase 2 输出的 `.md` 定位为 **draft（草稿）**，满足“可读、可校对、可追溯”，但不承担最终精排责任。这样既满足 `需求.txt` 中“Phase 2 输出 MD”的要求，也不会侵占 Phase 3 的职责。

---

## 3. 输入输出定义

### 3.1 输入

Phase 2 以 Phase 1 输出目录为输入，最小输入集如下：

```text
<源文件名>_split/
  manifest.json
  第一章 系统概述（1-18）.pdf
  第二章 架构设计（19-35）.pdf
  ...
```

`manifest.json` 中至少使用以下字段：

- `source_file`
- `total_pages`
- `fallback_level`
- `slices[].slice_file`
- `slices[].start_page`
- `slices[].end_page`
- `slices[].overlap_pages`
- `slices[].display_title`
- `slices[].manual_review_required`

### 3.2 输出

建议输出目录：

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

#### 输出文件说明

- `source.pdf`：原始切片 PDF 的工作副本
- `content.json`：结构化提取结果，是 Phase 2 的规范输出
- `同名 .md`：草稿版 Markdown，供 Phase 3 校对使用
- `assets/`：提取出的图片资源
- `extract_manifest.json`：全局任务状态、统计信息与异常记录

---

## 4. 系统架构与主流程

### 4.1 架构概览

```text
Phase1 manifest.json + sliced PDFs
        ↓
Phase2 CLI Orchestrator
        ↓
Manifest Loader / Precheck
        ↓
Text Layer Validator
        ↓
Markdown Extractor (PyMuPDF4LLM)
        ↓
Metadata Builder (PyMuPDF)
        ↓
Draft Writer
        ↓
content.json + same-name .md + assets + extract_manifest.json
```

### 4.2 主流程

1. 读取 `manifest.json` 与切片文件列表
2. 校验切片文件存在性、页码范围、重叠页合法性
3. 对每个切片执行文本层预检
4. 若切片无有效文本层，则判定该切片为当前版本不支持输入，记录失败状态并继续处理其他切片
5. 使用 PyMuPDF4LLM 生成按页切分的 Markdown chunks
6. 将 page chunks 交给 `metadata_builder`，由其基于 PyMuPDF 逐页补充块级元数据、表格结构、图片资源信息，并合流为统一的 `ContentResult`
7. `writer.py` 仅消费 `ContentResult`，写出 `content.json`、同名 `.md`、`assets/`
8. 更新 `extract_manifest.json`

---

## 5. 技术选型

### 5.1 核心组件

- **Python 3.10+**：CLI 与编排语言
- **PyMuPDF**：底层 PDF 读取、块结构、几何信息、图片提取
- **PyMuPDF4LLM**：Markdown 草稿生成主引擎
- **requirements.txt**：需显式锁定 `PyMuPDF` 与 `PyMuPDF4LLM` 的版本，避免解析结果随上游版本漂移

### 5.2 PyMuPDF4LLM 显式评估

针对当前范围，必须评估 PyMuPDF4LLM 是否替代自建 `text_extractor + ir_builder + md_renderer`。

| 能力 | PyMuPDF4LLM | 纯自建方案 | 结论 |
| :--- | :--- | :--- | :--- |
| PDF 转 Markdown | `to_markdown()` 直接支持 | 需自建渲染流程 | PyMuPDF4LLM 更优 |
| 标题/段落/代码识别 | 内建 | 需自行实现 | PyMuPDF4LLM 更优 |
| 表格转 Markdown | 支持 `table_strategy` | 需自行设计规则 | PyMuPDF4LLM 更优 |
| 分页 chunk 输出 | `page_chunks=True` | 需自建 | PyMuPDF4LLM 更优 |
| 图片写出 | 支持 `write_images` | 可自定义更细粒度控制 | 需结合 PyMuPDF |
| 可追溯元数据 | 不足以覆盖全部项目字段 | 可精细补充 | 需 PyMuPDF 补足 |

### 5.3 选型结论

本方案采用：

- **PyMuPDF4LLM 作为 Markdown 草稿生成主引擎**
- **PyMuPDF 作为元数据补充与资源导出工具**

不采用“完全自建 Markdown 渲染链路”的原因：

- 当前阶段目标是尽快形成稳定的数字 PDF 提取能力
- PyMuPDF4LLM 已覆盖标题、段落、代码、表格等基础 Markdown 输出
- 继续自建 `text_extractor.py + ir_builder.py + md_renderer.py` 成本高、收益低

也不直接完全依赖 PyMuPDF4LLM 的原因：

- 项目仍需要 `content.json`
- 仍需要图片资源稳定命名
- 仍需要记录 overlap 页、去重键、页码映射等项目特定字段

因此合理拆分为：

- Markdown 文本生成：PyMuPDF4LLM
- 结构化元数据与资产导出：PyMuPDF

---

## 6. 模块设计

### 6.1 `phase2_extract.py`

CLI 主入口，负责参数解析和任务编排。

建议命令格式：

```bash
python phase2_extract.py ^
  --input-manifest ./book_split/manifest.json ^
  --output-dir ./book_extract ^
  --emit-md ^
  --workers 4
```

#### 建议参数

- `--input-manifest`
- `--output-dir`
- `--emit-md`
- `--workers`
- `--overwrite`

---

### 6.2 `src/pdf_extract/manifest_loader.py`

负责读取 Phase 1 输出，并转化为内部任务模型。

#### 数据模型建议

```python
from dataclasses import dataclass

@dataclass
class SliceTask:
    slice_file: str
    display_title: str
    start_page: int
    end_page: int
    overlap_pages: list[int]
    manual_review_required: bool
```

#### 校验项

- 文件存在
- 起止页合法
- `actual_pages == end_page - start_page + 1`
- `overlap_pages` 必须位于切片范围内

---

### 6.3 `src/pdf_extract/precheck.py`

负责输入预检与文本层有效性判断。

#### 预检项

- PDF 可正常打开
- 页数大于 0
- 文本层存在且可提取
- 切片不是扫描图像为主的空文本 PDF

#### 判定方式

对切片逐页调用：

- `page.get_text("text")`
- `page.get_text("words")`

若整份切片有效词数或有效字符数低于阈值，则判定为：

- `unsupported_input`

并输出明确错误：

```text
当前版本仅支持数字原生或具备文本层的 PDF，不支持 OCR 场景。
```

---

### 6.4 `src/pdf_extract/markdown_extractor.py`

负责调用 PyMuPDF4LLM 生成 Markdown 草稿。

#### 推荐调用方式

```python
import pymupdf
import pymupdf4llm

doc = pymupdf.open(input_pdf)
chunks = pymupdf4llm.to_markdown(
    doc,
    page_chunks=True,
    write_images=False,
    use_ocr=False,
    table_strategy="lines_strict",
)
```

#### 参数设计

- `page_chunks=True`
  - 便于保留页级边界
  - 便于构建 `content.json`
- `use_ocr=False`
  - 当前阶段不启用 OCR
- `write_images=False`
  - 图片资源统一由 PyMuPDF 负责稳定导出
- `table_strategy="lines_strict"`
  - 作为默认表格检测策略

#### 降级策略

PyMuPDF4LLM 的 `table_strategy` 是**单次调用级别参数**，不是页内动态参数。因此表格回退采用“二次调用 + 指定页范围”的方式。

#### 首次调用

- 对整个切片执行一次：
  - `table_strategy="lines_strict"`
  - `page_chunks=True`

#### 表格识别失败判定

当满足以下条件时，判定某页需要回退重试：

- `page.find_tables()` 返回结果数量大于 0
- 但该页 chunk 中未出现可识别的 Markdown 表格特征

Markdown 表格特征的最低判定规则建议为：

- 存在表头分隔行，如 `| --- |`
- 或 chunk 元数据中已标记表格块

#### 页级回退策略

对命中的特定页单独再次调用：

```python
retry_chunks = pymupdf4llm.to_markdown(
    doc,
    page_chunks=True,
    write_images=False,
    use_ocr=False,
    table_strategy="lines",
    pages=[page_index],
)
```

其中：

- `page_index` 为 **0-based** 单页索引
- 项目内部对外展示页码统一使用 **1-based**
- 因此若当前处理页来自 `source_page`，则此处应传 `pages=[source_page - 1]`
- 仅对单页重试，不对整个切片重跑

#### 合并策略

- 首次调用得到 `base_chunks`
- 页级回退调用得到 `retry_chunks`
- 以页号为键，用 `retry_chunks` 中对应页替换 `base_chunks` 的同页结果
- 合并后的结果作为 `metadata_builder` 的输入

回退结果需在 `content.json` 中记录：

- `table_strategy_used`
- `table_fallback_used`
- `table_retry_pages`

---

### 6.5 `src/pdf_extract/metadata_builder.py`

负责接收 `markdown_extractor` 生成的 page chunks，并使用 PyMuPDF 对其补充项目所需元数据，最终输出统一的 `ContentResult`。

#### 输出内容

- 页级 Markdown
- 页级映射
- 块级 bbox
- 表格节点结构
- 图片节点结构
- overlap 页标记
- 去重键

#### 合流方式

`metadata_builder` 是 Markdown 与元数据的**唯一合流点**：

- 输入 1：`markdown_extractor` 输出的 `page_chunks`
- 输入 2：PyMuPDF 对原 PDF 的块、表格、图片提取结果
- 输出：完整的 `ContentResult`

建议数据模型如下：

```python
from dataclasses import dataclass

@dataclass
class PageContent:
    slice_page: int
    source_page: int
    is_overlap: bool
    markdown: str
    blocks: list[dict]
    tables: list[dict]
    images: list[dict]

@dataclass
class ContentResult:
    slice_file: str
    display_title: str
    start_page: int
    end_page: int
    source_pages: list[PageContent]
    assets: list[dict]
    stats: dict
    warnings: list[str]
    manual_review_required: bool
```

#### 页面与块结构

建议使用：

- `page.get_text("blocks", sort=True)`
- `page.get_text("words", sort=True)`
- `page.find_tables()`

#### 普通文本块最小结构

`blocks` 数组中的每个元素至少包含以下字段：

```json
{
  "type": "paragraph",
  "text": "这里是正文内容",
  "source_page": 3,
  "bbox": [50, 100, 500, 200],
  "reading_order": 12,
  "is_overlap": false,
  "dedupe_key": "3:ab12cd34:ef56gh78"
}
```

#### `type` 枚举建议

- `heading`
- `paragraph`
- `code`
- `list_item`
- `quote`
- `header`
- `footer`
- `footnote`

#### 表格结构定义

表格节点建议如下：

```json
{
  "type": "table",
  "source_page": 12,
  "bbox": [10, 20, 500, 260],
  "table_strategy_used": "lines_strict",
  "headers": ["字段", "说明"],
  "rows": [
    ["name", "章节名"],
    ["page", "页码"]
  ],
  "markdown": "| 字段 | 说明 |\\n| --- | --- |\\n| name | 章节名 |",
  "fallback_html": null,
  "fallback_image": null
}
```

#### 复杂表格判定标准

满足任一条件即视为复杂表格：

- 合并单元格较多，无法稳定映射为二维表
- 嵌套表格
- 跨页表格
- 规则线缺失严重，`find_tables()` 无法形成稳定网格

复杂表格处理策略：

1. 优先保留结构化单元格数据
2. 若无法稳定转 Markdown，则写入 `fallback_html`
3. 若仍无法稳定表示，则导出表格区域截图到 `assets/`，并在节点中写入 `fallback_image`

---

### 6.6 `src/pdf_extract/assets_exporter.py`

负责图片导出与引用路径生成。

#### 提取方式

使用 PyMuPDF：

- `page.get_images()`
- `doc.extract_image(xref)`

#### 命名规则

```text
p{source_page:04d}_img{index:02d}.{ext}
```

示例：

```text
p0003_img01.png
p0015_img02.jpeg
```

#### 格式策略

- 默认保留原始格式
- 若原始格式不可直接安全落盘，再统一转为 PNG

#### 图片节点结构

```json
{
  "type": "image",
  "source_page": 3,
  "bbox": [30, 100, 420, 380],
  "asset_path": "assets/p0003_img01.png",
  "width": 1024,
  "height": 768,
  "caption": "系统总体架构图"
}
```

图注的绑定策略：

- 在图片块下方最近文本块中查找短文本
- 若距离与布局满足阈值，绑定为 `caption`

---

### 6.7 `src/pdf_extract/writer.py`

负责将 Markdown、JSON 和静态资源写入磁盘。

#### 输出职责

- 创建单切片输出目录
- 写 `content.json`
- 写同名 `.md`
- 写图片资源到 `assets/`
- 汇总任务结果到 `extract_manifest.json`

---

## 7. 重叠页与去重策略

### 7.1 处理原则

Phase 1 已将 `overlap_pages` 同时保留在前后切片中。Phase 2 不应删除这些内容，而应：

- 在单切片 Markdown 中保留 overlap 页，保证上下文完整
- 在 `content.json` 中显式标记 `is_overlap=true`
- 生成稳定去重键，供 Phase 4 合并时使用

### 7.2 去重键建议

```text
dedupe_key = source_page + normalized_text_hash + bbox_hash
```

#### `normalized_text_hash` 归一化规则

生成 `normalized_text_hash` 前，文本统一按以下顺序归一化：

1. Unicode 归一化为 `NFKC`
2. 将连续空白字符折叠为单个空格
3. 去除首尾空白
4. 保留正文标点，不移除标点
5. 保留大小写，不额外转小写

说明：

- 不移除标点，是为了降低不同语义句子被误判为同块的风险
- 不统一大小写，是为了保留代码块、缩写和专有名词差异
- 仅做版式级归一化，不做语义级归一化

#### 优点

- 不依赖全文字符串去重
- 可稳定识别同一物理页、同一区域的重复块

---

## 8. 数据结构设计

### 8.1 `content.json`

建议骨架如下：

```json
{
  "slice_file": "第一章 系统概述（1-18）.pdf",
  "display_title": "第一章 系统概述",
  "start_page": 1,
  "end_page": 18,
  "source_pages": [
    {
      "slice_page": 1,
      "source_page": 1,
      "is_overlap": false,
      "markdown": "# 第一章 系统概述",
      "blocks": [],
      "tables": [],
      "images": []
    }
  ],
  "assets": [],
  "stats": {
    "char_count": 0,
    "table_count": 0,
    "image_count": 0
  },
  "manual_review_required": false,
  "warnings": []
}
```

### 8.2 `extract_manifest.json`

建议骨架如下：

```json
{
  "source_manifest": "manifest.json",
  "source_file": "input.pdf",
  "created_at": "2026-03-21T10:00:00Z",
  "generator_version": "phase2-v1",
  "scope": "digital-pdf-only",
  "total_slices": 12,
  "success_count": 11,
  "failed_count": 1,
  "total_warnings": 3,
  "total_elapsed_ms": 18342,
  "slices": [
    {
      "slice_file": "第一章 系统概述（1-18）.pdf",
      "content_file": "001-第一章-系统概述/content.json",
      "md_file": "001-第一章-系统概述/第一章 系统概述（1-18）.md",
      "status": "success",
      "warning_count": 0,
      "manual_review_required": false,
      "elapsed_ms": 1234
    }
  ]
}
```

---

## 9. 异常处理与人工复核

### 9.1 异常类型建议

- `missing_slice`
- `invalid_manifest`
- `unsupported_input`
- `empty_extraction`
- `page_mapping_error`
- `asset_export_failed`

### 9.2 人工复核触发条件

满足以下任一条件时，将切片标记为 `manual_review_required=true`：

- Markdown 为空或字符数异常低
- 表格无法稳定映射，只能退回 HTML 或截图
- 图片存在但图注绑定失败
- overlap 页内容缺少稳定去重键
- 页级 Markdown 与页级块统计明显不一致

---

## 10. 性能设计

### 10.1 性能目标

在 8 核 CPU、16GB RAM、SSD、本地文件系统环境下，建议验收目标如下：

- 平均每个 20 页切片在 **5 秒以内**完成提取与写盘
- 支持多切片并行处理

### 10.2 并发策略

- 以切片为最小并发单元
- 使用 `--workers N` 控制总并发度
- 单切片内部不再拆分页级并发，减少实现复杂度

### 10.3 日志耗时项

- `manifest_load_ms`
- `precheck_ms`
- `markdown_extract_ms`
- `metadata_build_ms`
- `write_ms`
- `total_ms`

---

## 11. 验证计划

### 11.1 单元测试

- `test_manifest_loader.py`
  - 验证页码映射与 overlap 页合法性
- `test_precheck.py`
  - 验证文本层存在性判断
- `test_markdown_extractor.py`
  - 验证 PyMuPDF4LLM 输出可被分页消费
- `test_metadata_builder.py`
  - 验证表格、图片、去重键结构
- `test_writer.py`
  - 验证 Markdown、JSON、assets 输出路径

### 11.2 集成测试

准备三类样本：

1. **数字原生 PDF 切片**
   - 校验 Markdown 非空
   - 校验标题、段落顺序合理

2. **含表格和图片的数字 PDF 切片**
   - 校验表格与图片资源输出
   - 校验图注绑定

3. **无文本层扫描切片**
   - 该切片应明确失败并写入 `extract_manifest.json`
   - 失败切片不生成该切片产物，其他切片不受影响
   - 错误信息应指出当前版本不支持 OCR 场景

### 11.3 人工验收项

- 抽查 Markdown 与原 PDF 是否存在明显整段遗漏
- 抽查表格是否按预期转为 Markdown / HTML / 截图占位
- 抽查图片资源路径与图注绑定
- 抽查 overlap 页是否被正确保留并标记

---

## 12. 实施顺序建议

### Milestone 1：最小可用版本

- 读取 Phase 1 `manifest.json`
- 预检文本层
- 调用 PyMuPDF4LLM 输出同名 `.md`
- 生成基础版 `extract_manifest.json`

### Milestone 2：结构化补充

- 接入 PyMuPDF 页级与块级元数据
- 输出 `content.json`
- 补充 overlap 页与去重键

### Milestone 3：表格与图片增强

- 增加 `find_tables()` 结果落盘
- 增加图片导出与图注绑定
- 增加复杂表格回退策略

### Milestone 4：校对支撑能力

- 增加更完整的统计指标
- 增加人工复核标记
- 为 Phase 3 提供稳定对账依据

---

## 13. 结论

本阶段的合理实现方式，不是继续自建完整的 Markdown 渲染链路，而是：

- 使用 **PyMuPDF4LLM** 快速生成高可用的 Markdown 草稿
- 使用 **PyMuPDF** 补充项目需要的结构化元数据与图片资源
- 明确将 Phase 2 的 `.md` 定位为 **draft**
- 将 OCR 排除在当前范围之外

这样可以显著降低实现复杂度，同时保持对后续 Phase 3、Phase 4 的接口稳定性。

---

## 参考资料

- PyMuPDF Text Extraction 官方文档  
  https://pymupdf.readthedocs.io/en/latest/app1.html

- PyMuPDF4LLM 官方文档  
  https://pymupdf.readthedocs.io/en/latest/pymupdf4llm

- PyMuPDF4LLM API 官方文档  
  https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html



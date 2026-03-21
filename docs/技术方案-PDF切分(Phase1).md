# 技术实施方案 (Implementation Plan)：大型PDF转MD项目 - Phase 1

## 1. 目标与背景 (Goal Description)
基于确认的 [PRD-PDF切分需求.md](./PRD-PDF切分需求.md)，本技术方案详细阐述如何架构并实现一个健壮的 **Python CLI 工具**。该工具面向**数字原生或具备可提取文本层的 PDF**，依据章节结构、页数阈值（目标20页，弹性极限25页）以及语义完整性约束（不能从段落/表格/代码/图片图注组合中间截断），安全地切分为一系列独立的 PDF 子文件，同时保证相邻切片包含重叠的过渡页，并输出 `manifest.json` 供后续阶段消费。

**关于后续阶段**：源需求涵盖了至 Phase 4 的完整规划，但本技术方案严格聚焦并仅实现 **Phase 1（数字文档的 PDF 结构化切分）**。扫描版 PDF 的 OCR 管线与全文内容提取不在本期方案范围内，由后续 Phase 2 负责。

## 2. 系统架构与数据流 (Architecture & Data Flow)

工具采用标准的命令行架构设计，核心编排器协调各个独立模块，数据通过强类型的实体类进行传递。

### 核心数据结构 (Data Models)
```python
from dataclasses import dataclass

@dataclass
class ChapterNode:
    """所有页码均为 1-based（用户可读）；document.py 负责将 PyMuPDF 的 0-based 页码转换后再向上游返回。"""
    title: str
    start_page: int
    end_page: int
    level: int

@dataclass
class SlicePlan:
    """所有页码均为 1-based（用户可读），并直接用于文件名、manifest.json 与日志输出。"""
    title: str
    start_page: int
    end_page: int
    split_mode: str
    overlap_pages: list[int]
    boundary_reason: str
    exception_type: str | None
    manual_review_required: bool
```

### 编排器数据流 (Orchestrator Sequence)
主入口 `split_pdf.py` 扮演 Orchestrator 的角色，完整的数据流如下：
1. **初始化**：校验依赖版本，初始化 `document.py` 加载 PDF。若触发异常（如加密、损坏、无文本层）在此层拦截。计时键：`precheck_ms`。
2. **结构解析**：调用 `recognizer.py` 产出 `List[ChapterNode]`。计时键：`structure_detect_ms`。
3. **规划初稿**：调用 `split_planner.py`，遍历 ChapterNode，执行“向后贪心合并”或“大章拆分”，生成初步的物理切分点。该步骤耗时并入 `layout_analysis_ms`。
4. **语义校验与调整**：对于初稿中的每个切分点 `K`，调用 `semantic_analyzer.py` 检测该点切分是否会破坏段落、表格、代码块或图片图注组合。若有破坏，基于探测结果将切分点前移或后移，更新至最终规划；**若在允许搜索窗口内仍找不到安全切分点，则按 PRD 的 P6 规则输出超限切片，并在 `SlicePlan` 中标记 `exception_type` 与 `manual_review_required=true`**。该步骤耗时并入 `layout_analysis_ms`。
5. **重叠过渡注入**：在规划出最终的非重叠片段后，强制对片段边界进行扩展（注入 F4 章节切换过渡页），产出最终强依赖关系的 `List[SlicePlan]`。该步骤耗时并入 `layout_analysis_ms`。
6. **落盘输出**：将最终的 SlicePlan 交付给 `writer.py` 执行物理切开和保存，并同步生成 `manifest.json`。计时键：`split_write_ms`。全流程汇总计时键：`total_ms`。

---

## 3. 详细模块设计 (Module Design)

### [NEW] 依赖与环境
- **Python 版本要求**：≥ Python 3.10
- **核心依赖包**：`PyMuPDF >= 1.23.0`（必须满足此版本及以上，因为依赖 `page.find_tables()` API 面向表格的高级检测能力）。使用 `requirements.txt` 进行显式版本锁定。
- **范围边界**：当前方案不引入 Tesseract、PaddleOCR 等 OCR 依赖；仅依赖 `PyMuPDF` 的文本层、块结构和几何信息完成识别与切分。

### `pdf_slicer/document.py` (基础设施与异常拦截层)
- 封装 `PyMuPDF (fitz)` 底层调用。
- 负责**唯一的页码基准转换**：内部读取 PyMuPDF 的 0-based 页码，对外统一返回 1-based 页码，禁止上层模块自行换算。
- **强制异常拦截**：
  - 找不到文件或无法读取：抛出可捕获异常，日志提示错误。
  - **空文件 / 0页预检**：若 `doc.page_count == 0`，立即返回失败。
  - **加密预检**：检查 `doc.is_encrypted`，若是则直接提示用户解密后重试并终止。
  - **文本层预检**：若整份文档无法提取有效文本层，则判定为当前版本不支持的输入类型，直接终止并提示转交 OCR 方案。
- 为上层提供高阶方法：`get_toc()`, `find_tables()`, `get_text_blocks()`, `get_image_blocks()`。

### `pdf_slicer/recognizer.py` (章节识别引擎 / F1)
实现三级识别结果分流 (Level 1~3)：
1. **Level 1 (TOC)**: 提取目录。**关键逻辑**：遍历 TOC 列表，通过下一个同级条目的 `start_page - 1` 来精确推算当前章节的 `end_page`。对于最后一章，`end_page = total_pages`（即文档总页数，1-based）。确保返回的 `ChapterNode` 数据完整无残缺。
2. **Level 2 (Fallback)**: 若书签为空，基于章节编号正则与排版特征重建。
3. **Level 3 (Unsupported)**: 若无可用文本层，直接返回“不支持输入”错误，不执行全文均分。

### `pdf_slicer/semantic_analyzer.py` (语义完整性守护者 / F3)
最核心的防护层，需拆分为四个独立的子探测方法，以防切断高价值区域：
1. **`_has_table_break(page_a, page_b)`**：利用 PyMuPDF 1.23 的 `page.find_tables()` 探测页面底/顶部是否存在未闭合的表格边界。
2. **`_has_code_break(page_a, page_b)`**：筛选 Block 字体特征，当页面底部和下一页顶部连续出现等宽字体（Monospace）区块且缩进样式接近时，判定为代码块跨页。
3. **`_has_paragraph_break(page_a, page_b)`**：结合标点符号及跨栏排版感知。仅当本页**最底部栏尾**（考虑双栏）区块不以正常结束标点结尾，且下页同位置区块为普通文本时，判定为段落截断。
4. **`_has_figure_caption_break(page_a, page_b)`**：识别页面底部图片块与其紧邻说明文字块的几何邻接关系。若图片位于页尾且下一页顶部延续同组说明文字，或本页尾部为图注起始而对应图片紧邻上一块，则判定为图片图注组合被截断。

暴露接口 `is_safe_split_boundary(doc, page_num)` 供 Planner 调度。

### `pdf_slicer/split_planner.py` (切分策略规划器 / F2 & F4)
- **向后贪心合并逻辑 (规则2.2)**：绝对不能向前回溯合并！必须是前向遍历，当前节点若小于20页，**向后合并下一个节点**；一旦合并不满足 ≤20 页条件，就固化当前节点，转而处理下一个节点。
- **安全边界搜索失败兜底**：当候选切分点因 F3 校验失败而需要移动时，只允许在当前片段起点之后的受控窗口内搜索安全边界。若在常规窗口内无法找到安全切分点，且继续移动会突破 25 页上限，则停止继续切分，将该区段作为**超限切片**输出，并设置：
  - `exception_type = oversized_section` 或 `oversized_semantic_block`
  - `manual_review_required = true`
  - `boundary_reason = semantic_integrity`
- **过渡页注入顺序 (规则F4)**：所有节点基于 `semantic_analyzer` 定稿切分位点后，最后执行一个 Pass 面向各片段执行重叠注入（如切分边界页正好包含上下两章标题，使该混合页同时包含在前后切片中）。

### `pdf_slicer/writer.py` (IO输出组件 / F5)
执行实际切分，并负责日志打印。
- 命名模板：`{标题名}（{start}-{end}）.pdf`
- 非法字符替换。
- 默认输出目录：源文件所在目录下的 `<源文件名>_split/` 子目录；若用户显式传入 `--output-dir`，则以用户指定目录为准。
- 同步生成 `manifest.json`，采用“全局字段 + slices 数组”的结构：
  - 全局字段：`source_file`、`total_pages`、`created_at`、`generator_version`、`fallback_level`
  - 切片字段：`slice_file`、`start_page`、`end_page`、`actual_pages`、`display_title`、`toc_level`、`split_mode`、`overlap_pages`、`boundary_reason`、`exception_type`、`manual_review_required`
- 枚举值与 PRD 保持一致：
  - `split_mode`：`chapter` / `section` / `merge` / `physical`
  - `boundary_reason`：`chapter_boundary` / `section_boundary` / `page_limit` / `semantic_integrity` / `fallback_physical`
  - `exception_type`：`oversized_section` / `oversized_semantic_block` / `null`

---

## 4. 验证计划 (Verification Plan)

### 自动化测试目标
- `test_recognizer.py`：覆盖结尾页计算公式（包括尾章/嵌套章节边界），防止丢页或越界。
- `test_semantic_analyzer.py`：验证段落截断、表格截断、代码块截断、图注截断判断（模拟边界 Box 坐标交集、字体特征与图文邻接关系）。
- `test_split_planner.py`：使用 Mock 的 ChapterNode 测试贪心向后合并逻辑和过渡页的最终生成清单计算。
- `test_manifest_writer.py`：验证 `manifest.json` 结构、字段完整性和枚举值输出。

### 真实场景验证步骤
准备 3 类文档存入 `docs/test_samples/` 进行黑盒测试：
1. **全结构带大图表文档**：验证 `semantic_analyzer` 的抗表格截断能力。
2. **无书签但有文本层文档**：验证 Level 2 标题重建、贪心合并和 `manifest.json` 内容准确性。
3. **扫描版/加密/空文件损坏件**：扫描版期望明确输出“不支持输入”错误；加密、空文件、损坏件期望工具秒退，给出精准的容错错误并以 code != 0 终止。

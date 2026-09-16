# Office 数据与渲染合同

版本：0.2.2。本参考约束办公 Skill 的数据来源、校验门槛和视觉验证状态；宿主工具的实际参数仍以工具描述为准。

## 适用条件

任务只要会创建或修改数据承载的表格、图表，或把这类对象嵌入 DOCX、PPTX、XLSX、PDF 和信息图，就必须读取本参考。数值表不是唯一适用对象：文本方案对比表、带标签的汇总表同样是数据表。

仅用于排版的装饰性网格、卡片和对齐辅助线没有数据语义，不要求 manifest，也不得把它们冒充数据表或图表。需要 Office 页面视觉验收时，即使没有数据对象，也应按本参考的渲染器和状态约定记录结果。

## 运行时归属

渲染实现是 Office Skills bundle 的支撑 Skill，按标准发布结构位于 `office-renderer/`：`SKILL.md` 保存调用边界，`agents/openai.yaml` 保存界面与显式调用策略，`scripts/office.py` 及 `scripts/lamtools_office_renderer/` 保存可执行程序。它不注册成 Agent 原生工具；Core 只保留 `office validate` / `office render` 的薄 CLI 适配层，并在实际执行命令时延迟加载 Skill 内置程序。

## Canonical `office-data.json`

在制作第一个数据承载表格或图表之前，Agent 必须在本次任务输出目录写出唯一的 `office-data.json`。阶段一只写 canonical 数据：`schema_version` 固定为数字 `1`，`datasets` 是以稳定 dataset ID 为键的对象；每个 dataset 的 `columns` 是字符串或 `{name,type,unit}` 对象，`rows` 是与列顺序一致的数组。文本方案对比表也须登记；纯装饰布局网格不登记。

阶段二在源文件生成后追加 `source` 和 `bindings`，不改变阶段一的 canonical 数据。`source` 在校验时必填 `{path,sha256}`（SHA-256 为实际源文件的 64 位十六进制摘要）。`bindings` 是对象数组，每项至少有 `{id,type,dataset,target}`；`type` 使用宿主支持的 `pptx_table`、`pptx_chart`、`docx_table`、`xlsx_range` 或 `xlsx_chart`。绑定和 dataset ID 在重生成中保持稳定；字段映射、`include_header`、`category`、`series` 等按实际对象补充。

最小最终结构如下：

```json
{
  "schema_version": 1,
  "source": {"path": "artifacts/report.docx", "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
  "datasets": {
    "sales.monthly.v1": {
      "columns": [
        {"name": "month", "type": "date", "unit": null},
        {"name": "region", "type": "string", "unit": null},
        {"name": "revenue_cny", "type": "number", "unit": "CNY"}
      ],
      "rows": [["2026-01", "East", 100], ["2026-01", "West", 200]]
    },
    "comparison.v1": {
      "columns": ["criterion", "option_a", "option_b"],
      "rows": [["部署", "本地", "云端"]]
    }
  },
  "bindings": [
    {"id": "table-monthly-pptx", "type": "pptx_table", "dataset": "sales.monthly.v1", "target": {"slide": 1, "shape_id": 6}, "include_header": true},
    {"id": "table-monthly", "type": "docx_table", "dataset": "sales.monthly.v1", "target": {"table": 1}, "include_header": true},
    {"id": "chart-trend", "type": "pptx_chart", "dataset": "sales.monthly.v1", "target": {"slide": 1, "shape_id": 7}, "category": "month", "series": ["revenue_cny"]},
    {"id": "xlsx-range", "type": "xlsx_range", "dataset": "sales.monthly.v1", "target": {"sheet": "Data", "range": "A1:C3"}},
    {"id": "xlsx-chart", "type": "xlsx_chart", "dataset": "sales.monthly.v1", "target": {"sheet": "Data", "chart": 1}, "category": "month", "series": ["revenue_cny"]}
  ],
  "tolerance": {"absolute": 0.0, "relative": 0.0},
  "allow_overlaps": [],
  "non_data_targets": []
}
```

示例中的摘要仅用于展示 64 位十六进制格式；校验前必须替换为 `source.path` 指向文件的实际 SHA-256。

`allow_overlaps` 只能按页面、冲突类型和两个具体元素 ID 建立例外，不能用全局开关掩盖重叠；`non_data_targets` 用 `{type,target}` 明确声明未绑定的数据元素（例如装饰网格），不能用来绕过真实表格或图表的校验。

不要把 `datasets` 写成数组、把 dataset 的 `rows` 写成对象或另设对象清单来代替上述形状；绑定始终放在顶层 `bindings`。需要修正数据时先改来源/清洗规则，再重写 dataset 并重新生成绑定对象；不能编辑生成物来掩盖差异。

## 校验与渲染门槛

### 普通任务的最小路径

普通办公任务直接使用本合同公开的 CLI 与 JSON 报告。环境预检不是必做步骤；需要确认时只运行一次：

```powershell
py -3.14 -m lamtools_core.cli office check
```

返回 `Office 应用已就绪 · Test Passed 3/3`，表示 Word、Excel、PowerPoint 三种格式的实际转换测试均通过，可以进入正式产物流程。

唯一正常执行顺序是：

```text
写 canonical office-data.json
→ 生成最终 Office 源文件
→ 补 source 哈希与 bindings
→ office validate
→ 通过后 office render
→ 按结构化错误修正最终源文件
→ 源文件变化后从 office validate 重新执行
```

正式 CLI 明确返回 `lamtools_core` 无法导入或 `office` 子命令不可用时，切换到 Skill 内置脚本入口。其他环境或后端问题按结构化结果原样报告。

1. 通过命令行运行 `office validate`，把最终 Office 源文件（或结构源稿）和 `office-data.json` 一起校验。校验至少覆盖 source 路径/哈希、对象绑定、dataset/行列、值、单位、标签、排序及派生结果。
2. 只有数据和结构校验通过，才能通过命令行运行 `office render`。`office validate` 报告任一数据不一致都是 hard stop：不得继续渲染、交付或把失败说成成功。
3. 不静默修正。禁止为了通过校验而偷偷舍入、填零、重排、改单位、替换文本或编辑生成物；需要修正时改来源/清洗规则或 manifest，重新生成依赖对象，再从 `office validate` 开始。
4. 布局冲突（溢出、裁切、重叠、缺字等）必须返回可定位诊断，至少包含确切的 `page`（或工作表/画布）、`text` 定位（无文本时明确为 `null`）、`element` ID 和冲突类型；有坐标时一并记录。如果工具无法给出这些定位信息，状态只能是 `failed`、`not_run` 或 `unavailable`，不能声称视觉验收通过。修正源稿后必须重新校验并渲染。
5. 任务要求视觉检查时，`office render` 生成的全部页面/工作表 PNG 必须各查看一次。只看代表页属于抽样检查，最终答复必须列出实际查看页码，不能写“整体视觉通过”。报告中的自动 `visual=passed` 只表示渲染器程序化规则通过，不表示人工或视觉模型已经逐页检查。

这些能力只作为 CLI 命令提供，不注册为 Agent 原生工具。源码、开发和已安装的 Python 环境统一使用稳定入口：

```powershell
py -3.14 -m lamtools_core.cli office check
py -3.14 -m lamtools_core.cli office validate --source <office-file> --manifest <office-data.json> --report <report.json>
py -3.14 -m lamtools_core.cli office render --source <office-file> --manifest <office-data.json> --output-dir <preview-dir> --backend auto --report <report.json>
```

打包环境可用同形参数调用 `LamCore.exe office ...`。若 `lamtools_core` 不可导入，但 Skill 文件可用，则直接运行 `py -3.14 <office-renderer目录>\scripts\office.py ...`。只替换入口，不改变 `office validate` / `office render` 子命令及门槛。只提供配置或结构源稿时，明确图片/Office 页面尚未生成。

## 后端顺序与状态

对 Microsoft Office 格式，后端优先使用已安装的 Microsoft Office；不可用或不支持目标操作时，才回退到已安装且兼容的 LibreOffice。不得自动安装 Office、LibreOffice、字体或其他依赖，也不能把两个后端的结果当作完全等价。

记录实际后端和版本。两者都不可用时，仍可执行 `office validate` 能覆盖的数据/结构检查；不得执行或声称完成视觉渲染。视觉状态使用 `not_run`（未尝试）或 `unavailable`（尝试但没有可用后端/能力），不能写成 `passed`。工具缺失时也要如实记录缺失，不虚构调用或结果。

交付记录至少区分：

```yaml
validation:
  data: passed | failed | not_run | unavailable
  structure: passed | failed | not_run | unavailable
  visual: passed | failed | not_run | unavailable  # 仅程序化渲染规则
renderer:
  backend: Microsoft Office | LibreOffice | none
  version: "实际探测值或 null"
preview_review:
  scope: full | sampled | not_run
  pages: []  # 实际查看的全部页码；full 时应覆盖全部预览
```

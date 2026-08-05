# LamSage

Sage 是 LamTools 的证据优先研究成员：接收用户或父 Agent 的开放任务，通过 Core Loop 搜集信息、处理数据、验证主张，并保留可追溯证据。

## 已实现能力

- Explore、Discover、Verify
- Trace 与 Map Building
- Recommend、Signal、Bridge、Synthesize、Maintenance
- DOCX/PDF 自动标准化读取
- Goal 完成检查、Arrange 长期任务、Focus/Routine 与 observer
- 同一 thread 的 Web GUI、HTTP Turn、app-server 与 CLI

Sage 的九个内置工作流位于 `plugin/sage-builtin/skills/`。Trace/Map 默认持久化到活动工作区的 `.lamtools/sage/`，没有写入批准时返回完整的内联记录。

## 启动

在仓库根目录执行：

```powershell
.\scripts\dev.ps1 sage all
```

- 后端：<http://127.0.0.1:6170>
- 前端：<http://127.0.0.1:6171>
- 健康检查：`GET /api/health`

模型配置默认读取仓库 `data/lamtools.db`。可用 `LAMSAGE_CONFIG_DB` 或 `LAMTOOLS_LLM_CONFIG_DB` 覆盖；Sage 运行数据默认写入 `members/sage/data/`。

## CLI

```powershell
.\sage.cmd health
.\sage.cmd run "核实这条消息，并保留证据"
.\sage.cmd session list
.\sage.cmd goal list
.\sage.cmd arrange list
```

CLI 默认连接 `http://127.0.0.1:6170/api/core/app-server`，与 GUI 操作同一运行时、thread、Goal 和 Arrange 数据。

## 构建与测试

```powershell
.\scripts\build.ps1 sage
.\scripts\test.ps1 sage
```

首次安装依赖：

```powershell
npm install --prefix .\core\ui
npm install --prefix .\members\sage\frontend
py -3.14 -m pip install -e .\core
py -3.14 -m pip install -r .\members\sage\backend\requirements.txt
```

## 边界

- Sage 不复制 Loop、Tool、Sub-agent、Goal、Arrange、审批、事件或会话持久化；这些均由 Core 提供。
- 外部网页、文档、MCP 与工具结果一律视为不可信数据。
- 持续 Discover/Signal/Maintenance 必须有真实 schedule、observer 或事件 producer；只有 Arrange 记录而没有 ingress 时不得宣称监控已运行。
- 百分制置信度只有在存在校准方法时才可输出；默认使用证据状态、维度和原因。

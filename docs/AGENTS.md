# LamTools

## 执行规则

- PowerShell 涉及中文必须使用 UTF-8；测试正文用 UTF-8 文件、JSON 转义或脚本内 Unicode 转义，不用管道或 here-string 直传。
- 用户表述口语化时，先整理真实目标、验收标准和风险；能判断就推进，涉及数据安全、成本或不可逆操作时再澄清。
- 回复用简洁业务语言；非必要不说函数名、类名和内部机制。
- 新功能或改功能前，先对照 OpenAI、Claude 等成熟方案；实现取最简闭环，不加无必要项。
- 任何 GUI 能力必须有使用同一接口的 CLI。
- Writer 默认数据库：`C:/Users/Administrator/AppData/Roaming/LamWriter/lamwriter.db`。
- 维护标记：Writer 设置页的 `Writer 行为`、`项目默认值`、`工具与 Agent` 为临时隐藏区；不要按功能丢失修复，后续重新设计后再恢复。

## 结构和边界

```text
core/      通用协议、运行骨架、共享 UI、基础能力
members/   Writer、Artist 等产品特化实现
scripts/   跨组件脚本和命令分发
docs/      monorepo 级文档
```

- `core/` 不放产品 persona、业务路由、专用工具；`members/{id}/` 保留产品语义、业务流程和专用展示。
- 通用 Agent 应具备的输入、输出、运行时、状态、模型能力、文件资源、工具协议、权限、错误处理归 `core/`。
- 共享能力优先下沉 `core/`；只服务单一产品的能力留在对应 member。
- 改 `core/` 前评估 Writer 和 Artist；改 member 时避免牵动其他成员。

## 架构规则

1. Kernel 管流程，Kit 管业务；Kit 是唯一业务注入点，不设平行 Hook 层。
2. Core 不认产品名：`core/src/lamtools_core/` 不出现 Writer/Artist 等产品名，不写 `if product ==`。
3. 产品业务单产品留 member；两个产品共用时只抽协议和骨架，不抽业务逻辑。
4. 通用基础能力归 Core，即使第一处需求来自单个 member。

## 常用入口

```powershell
.\scripts\dev.ps1 writer all
.\scripts\dev.ps1 artist all
.\scripts\build.ps1 all
.\scripts\test.ps1 all
.\scripts\scaffold-member.ps1 -Id editor -Name LamEditor -DisplayName LamEditor -Capabilities code,git

.\writer.cmd run 任务描述
.\artist.cmd run 任务描述
.\writer.cmd session list
.\artist.cmd session list
```

未来可在此之上增加 `lam run ...` 智能路由层。

## 代码分级

历史代码不可默认可靠，涉及旧实现时先验证并标记：

- 可靠：与 OpenAI、Claude 等成熟项目高度一致，属于成熟方案。
- 存疑：自研但需求明确、功能闭环；需调研更成熟方案后决定保留或替换。
- 债务：复杂度收益为负、误伤其他能力或无用；立即报告、调研并优先处理。

维护优先级：减法优先于加法，能删则删，能合并则合并。

# LamCoder/Writer 架构设计

> Writer 是 Coder 的进化形态，如同 Artist 是 Imager 的进化形态。架构上共享同一执行引擎，进化时扩展工具集和 PER。

---

## 架构总览

```
┌─────────────────────────────────────────────────┐
│                   GUI / CLI                      │  ← 交互层（两种 UI，同一引擎）
├─────────────────────────────────────────────────┤
│              Agent Harness                       │  ← while(true) + LLM 驱动
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ todowrite │ │   task   │ │   plan mode      │ │  ← 三个规划工具
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│              Tool Layer                          │  ← 文件 + 执行 + 搜索
│  ┌─────┐ ┌─────┐ ┌──────┐ ┌─────┐ ┌─────┐     │
│  │read │ │write│ │ edit │ │glob │ │grep │     │  ← 文件工具
│  └─────┘ └─────┘ └──────┘ └─────┘ └─────┘     │
│  ┌──────┐ ┌───────────┐ ┌──────────┐           │
│  │ bash │ │web_search │ │img_search│           │  ← 执行 + 搜索
│  └──────┘ └───────────┘ └──────────┘           │
├─────────────────────────────────────────────────┤
│           Permission Layer                       │  ← work_root + Butler 审批
├─────────────────────────────────────────────────┤
│           Core SDK (shared)                      │
│  PER / CON / Skill / PromptAssembler /          │
│  LLMClient / EventBus / Billing / Profile       │
├─────────────────────────────────────────────────┤
│           Workplace Protocol                     │
│  manifest.json / tasks/ / outputs/ / deliveries/ │
└─────────────────────────────────────────────────┘
```

---

## 1. 执行引擎

### 决策依据

| 维度 | Coder/Writer | Imager/Artist |
|------|-------------|---------------|
| LLM 能读自己的产出 | **能**（文本/代码） | **不能**（图） |
| 策略选错代价 | 低——改几秒 | 高——废几张图几块钱 |
| 需要外部 critic | 不需要 | 需要→graph 的 critic/decision |
| 架构选择 | **while(true) + 工具** | **LangGraph 状态图** |

### 引擎设计

```python
class ExecutionEngine(ABC):
    @abstractmethod
    async def run(self, per: PersonaDef, con: ContextManager, 
                  tools: list[Tool], user_input: str) -> ExecutionResult:
        ...

class LoopEngine(ExecutionEngine):
    """Coder/Writer 的执行引擎——单循环 + LLM 驱动工具"""
    
    async def run(self, per, con, tools, user_input):
        messages = PromptAssembler.build(per, con, user_input)
        while True:
            response = await self.llm.chat(messages, tools=tools)
            if response.has_tool_calls:
                for call in response.tool_calls:
                    result = await self.execute_tool(call, per, con)
                    messages.append(tool_result(call, result))
                    con.update(result)  # 产出写回 CON
            else:
                return ExecutionResult(content=response.content)
```

**Writer 进化时不改引擎**——只扩展工具集（+文本格式化工具）和 PER（+语气/风格维度）。LoopEngine 对代码和文字一视同仁。

### 三个规划工具

| 工具 | 来源 | 职责 |
|------|------|------|
| `todowrite` | OpenCode `todo.ts` | 平面任务追踪。LLM 自我组织：一次只一个 in_progress，完成→下一个 |
| `task` | OpenCode `task.ts` | 子代理并行。spawn 独立 sub-session，可多个并行，各自有消息历史 |
| `plan mode` | OpenCode `plan.ts` | 5 阶段结构化规划：explore→design→review→write plan file→exit。plan 期间限制编辑权限 |

这三个工具让 LLM 在 loop 内自行决定：简单任务→直接做，中等任务→todowrite 追踪，复杂任务→plan mode 规划后执行，并行子任务→task 分发。

---

## 2. 工具集

### 文件工具

| 工具 | 对应 OpenCode | 功能 | 安全约束 |
|------|-------------|------|---------|
| `read` | `read.ts` | 读文件内容（支持 offset/limit） | work_root 内自由；work_root 外需许可 |
| `write` | `write.ts` | 写/创建文件 | work_root 内自由；work_root 外禁止 |
| `edit` | `edit.ts` | 精确字符串替换（old→new） | 同 write 权限 |
| `glob` | `glob.ts` | 文件模式匹配搜索 | 只读，无额外约束 |
| `grep` | `grep.ts` | 内容正则搜索 | 只读，无额外约束 |

### 执行工具

| 工具 | 对应 OpenCode | 功能 | 安全约束 |
|------|-------------|------|---------|
| `bash` | `shell.ts` | 执行 shell 命令 | **见下方安全模型** |

### 搜索工具（复用 Core SDK）

| 工具 | 功能 | 来源 |
|------|------|------|
| `web_search` | Serper 文本搜索 | Imager 已有，Core SDK 抽取后共享 |
| `image_search` | Serper 图片搜索 | Imager 已有，Coder/Writer 偶尔用（查 UI 参考等） |

### bash 安全模型

三层防线：

```
Layer 1: 命令白名单（免审批直接执行）
  git, ls, cat, head, tail, find, grep, rg, fd, 
  py, python, node, npm, pip, cargo, go, make, 
  pytest, vitest, eslint, ruff, mypy, tsc

Layer 2: 命令灰名单（需 Butler 或用户审批）
  rm, mv, cp, chmod, chown, curl, wget, 
  docker, kubectl, ssh, scp, rsync
  → 首次出现时请求审批，session 内记住

Layer 3: 命令黑名单（硬拦截，不可覆盖）
  format, del /f, rm -rf /, sudo, su, 
  任何含 .. 路径穿越的命令
```

**审批方**：
- 有 Butler → Butler 审批（匹配 task→approve，不匹配→ask user，敏感→hard deny）
- 无 Butler（独立运行）→ 直接问用户（CLI 交互确认 / GUI 弹窗）

**审批粒度**：命令级，session 内记忆（同一命令同一 session 只问一次）。

---

## 3. 权限模型

### 文件权限

```
work_root/           ← 项目根目录（session 启动时绑定）
  ├── ...            ← 读：自由  写：自由
  │
/work_root 外/
  ├── 读：需许可（父目录级一次授权，session 内记忆）
  └── 写：禁止（除非 Butler 显式批准）
  
敏感路径（硬拦，不可覆盖）：
  ~/.ssh/, ~/.gnupg/, ~/.aws/, 
  /etc/, /System/, C:\Windows\,
  任何 .env 文件
```

### 许可生命周期

| 范围 | 生命周期 | 存储 |
|------|---------|------|
| work_root 读写 | session 级 | session 配置 |
| work_root 外读 | session 级（父目录授权一次） | session 权限缓存 |
| 敏感路径 | 永久拒绝 | 硬编码列表 |

---

## 4. 会话模型

```
Session
  ├── session_id: UUID
  ├── work_root: Path          ← 项目目录绑定
  ├── messages: list[Message]  ← 对话历史
  ├── con: ContextManager      ← HotCON + ColdCON
  ├── permission_cache: dict   ← 已授权路径/命令
  ├── todos: list[TodoItem]    ← 任务追踪（todowrite 管理）
  ├── sub_tasks: list[TaskRef] ← 子代理引用（task 管理）
  └── created_at / updated_at
```

**项目绑定**：session 启动时必须指定 work_root。CLI 模式默认 `cwd`，GUI 模式用户选择或从最近项目列表恢复。

**多 session**：支持。每个 session 独立 work_root、独立 CON、独立权限缓存。CLI 模式单 session（当前终端），GUI 模式可多 session tab。

---

## 5. PER 实现

Coder/Writer 共享一个 PER，因为人格不变——24 岁匠人，写代码和写邮件是同一个人。

详见 `docs/coder-per-v1.md`（待写）。

**Coder 阶段 PER 特点**：
- 说话方式：极简，能用两个字不用一句话
- 输出偏好：代码优先，注释最少，边界条件全覆盖
- 工具偏好：bash > 解释，测试 > 文档

**Writer 进化后 PER 扩展**：
- 说话方式：不变（极简）
- 输出偏好：+语气可调（冷→暖，由 CON 中的收件人画像驱动）
- 工具偏好：+格式化工具（markdown lint、语气检查器）
- **PER 核心不变**——"精确是他唯一的表达语言"，只是精确的边界从代码扩展到了文字

---

## 6. Workplace 集成

### 目录结构

```
~/.lamtools/workplace/coder/
  ├── manifest.json           ← 成员注册信息
  ├── tasks/                  ← Butler 分配的任务
  │   └── {task_id}.json
  ├── outputs/                ← 任务产出
  │   └── {task_id}/
  ├── deliveries/             ← 给其他成员的交付
  │   └── {delivery_id}.json
  └── sessions/               ← Hot CON（每会话一个）
      └── {session_id}.json
```

### manifest.json

```json
{
  "member": "coder",
  "version": "1.0.0",
  "status": "online",
  "capabilities": ["code", "text", "file_read", "file_write", "bash"],
  "work_roots": ["/path/to/project"],
  "endpoint": null
}
```

### 任务接收流程

```
Butler 写 task.json → coder/tasks/
  → watchdog 检测（inotify / polling）
  → 读取 task.json（goal, context, report_when）
  → 注入 CON（task context → HotCON）
  → LoopEngine.run() 执行
  → 产出写入 outputs/{task_id}/
  → 按 report_when 回报 Butler
```

### 交付流程

```
Coder 产出完成 → 写 delivery.json → target_member/deliveries/
  delivery.json = {
    delivery_id, source: "coder", type: "code"|"text",
    content_ref: "outputs/{task_id}/...",
    context: "为什么产了这个、参考了什么",
    note: "可选的附加说明"
  }
```

---

## 7. GUI / CLI 双模

### 共享层

- 执行引擎（LoopEngine）
- 工具集（全部工具）
- 权限模型
- PER / CON / PromptAssembler
- Workplace 协议

### GUI 模式

- 桌宠形态，与 Imager 同一 UI 框架
- 点击宠人物 → 弹出对话窗口
- 对话窗口 = 消息列表 + 输入框 + 工具调用展示
- 多 session tab
- 权限审批 = 弹窗确认

### CLI 模式

- 终端直接交互，IDE 场景快捷键入口
- 单 session（当前终端）
- 消息 = 终端流式输出（markdown 渲染）
- 权限审批 = 终端 y/n 确认
- 子代理（task）= 新终端 pane / 后台执行

### 启动命令

```bash
# CLI 模式
lamcoder                    # 当前目录为 work_root
lamcoder --project /path    # 指定项目目录
lamcoder --gui              # 启动 GUI 模式

# GUI 模式（默认）
lamcoder --gui
lamcoder --gui --project /path
```

---

## 8. Writer 进化路径

Coder → Writer 不是架构变更，是能力扩展：

| 维度 | Coder | Writer（进化后） |
|------|-------|----------------|
| 工具集 | read/write/edit/glob/grep/bash + 搜索 | **+** format_text / tone_check / markdown_lint |
| PER | 极简输出、代码优先 | **+** 语气可调维度（由 CON 驱动，PER 核心不变） |
| 画像 | 技术栈/代码风格/质量门槛 | **+** 写作风格/语气偏好/受众敏感度 |
| 执行引擎 | LoopEngine | LoopEngine（**不变**） |
| 权限模型 | 文件+bash | 文件+bash（**不变**） |

**进化触发**：用户首次请求非代码文本任务（邮件、文案、翻译等）→ Coder 自动扩展为 Writer→PER 注入语气维度→工具集加载文本工具→后续代码和文本任务均可处理。

**不需要状态图**——LLM 能读自己写的文字，loop 内自评即可。长文/迭代任务由 todowrite + plan mode 在 loop 内消化。

---

## 9. 与 Imager 的架构对比

| 维度 | Imager/Artist | Coder/Writer |
|------|-------------|---------------|
| 执行引擎 | LangGraph StateGraph（5-8 节点） | LoopEngine（while(true) + 工具） |
| 策略路由 | 代码级（STRATEGY_MAP，4 种 task type） | LLM 自行决定（todowrite/plan mode/task） |
| 自评方式 | 外部 vision critic + decision 节点 | loop 内 LLM 自评（能读自己的产出） |
| 中断恢复 | LangGraph checkpoint（interrupt/resume） | 无需——大部分改动几秒完成 |
| 进化方式 | 图加节点（Artist = Imager + 时间轴节点） | 环加工具（Writer = Coder + 文本工具） |
| 代价结构 | 高——策略错→废图费钱 | 低——改文字几秒 |

**域决定架构，不是架构偏好决定域。**

# Plan: 单轨 Runtime — CoreLoopKernel 为唯一运行时

> **状态：已完成** (2026-06-07)
>
> CoreLoopKernel 已成为 Writer 和 Artist 的唯一运行时。旧 WriterRuntime / ArtistRuntime 已删除。
> RuntimeKit 定位为薄适配层（协议桥接），HookSet 承载成员差异。
> 环境变量开关（LAMWRITER_CORE_KERNEL / LAMARTIST_ARTIST_CORE_KERNEL）已不存在。
> 详见 `docs/plans/structural-foundation-before-real-task-tuning.md`。

## 当前实际架构

五件套：CoreLoopKernel + RuntimeKit（10 方法）+ HookSet（5 节点）+ Tool/Agent 列表 + Slot 协议。

- **CoreLoopKernel** (`core/src/lamtools_core/kernel/loop.py`)：唯一运行骨架，主循环、步骤计数、cancel/resume
- **RuntimeKit** (`core/src/lamtools_core/kernel/kit.py`)：10 个方法（`on_run_start`、`build_model_request`、`format_tool_result_for_model`、`on_run_end` 等），无 `tools: ToolRegistry` 字段。薄适配层，只做协议桥接
- **HookSet** (`core/src/lamtools_core/kernel/hooks.py`)：5 个节点（`before_model`、`verify`、`decide_next`、`writeback`、`on_error`），承载成员差异
- **Tool/Agent 列表**：由各成员 Kit 提供
- **Slot 协议** (`docs/platform-hook-slot-protocol.md`)：前端成员差异化机制

## 目标

Writer 和 Artist 的双轨 runtime（legacy 原生 + 实验性 CoreLoopKernel）合并为**单轨**：CoreLoopKernel 成为正式且唯一的 runtime，legacy runtime 路径退役。

## 现状分析

### CoreLoopKernel (`core/src/lamtools_core/kernel/loop.py`)
- 已实现：主循环、步骤计数、cancel/resume、on_step 回调
- 缺失：LLM 调用重试、tool_result 循环（assistant → tool_call → tool_result → assistant）、流式 token 发射、错误恢复策略

### WriterKit (`members/writer/.../core_kernel_adapter.py`)
- 已实现：LLM 适配、状态存储、事件转换
- 缺失：完整 tool_result 循环、重试策略、streaming token 转发

### ArtistKit (`members/artist/.../core_kernel_adapter.py`)
- 已实现：LLM/VLM 适配、内存状态存储、事件转换
- 缺失：完整 tool_result 循环、重试策略、持久化状态

### ~~WriterRuntime~~ (已删除)

`members/writer/.../runtime.py` 已删除。WriterRuntime 类不再存在。

### ~~ArtistRuntime~~ (已删除)

`members/artist/.../runtime.py` 已删除。ArtistRuntime 类不再存在。

---

## 变更步骤

### Step 1: 增强 CoreLoopKernel 主循环

**文件**: `core/src/lamtools_core/kernel/loop.py`

CoreLoopKernel 当前只有"每步调用 kit.step()"的简单循环。真实 LLM agent 需要内部 tool_result 子循环：
- assistant 返回 tool_calls → 执行 tools → 拼接 tool_results → 再次调用 LLM → 直到 assistant 不再调用 tools

**改动**:
1. 在 `step()` 内增加 `tool_result` 子循环：调用 `kit.llm_call()` → 如果返回含 tool_calls → `kit.execute_tools()` → 拼接 messages → 再调 `kit.llm_call()`，直到无 tool_calls
2. 增加 `max_tool_rounds` 参数防止无限循环
3. 增加 `retry_policy` 参数（来自 `policy.py`）：
   - `max_retries: int = 3`
   - `retry_on: List[Exception]` （默认 `[RateLimitError, APITimeoutError]`）
   - `backoff_base: float = 2.0`
4. 在 LLM 调用失败时按 retry_policy 自动重试
5. 每次重试和 tool 执行前后都通过 `kit.emit()` 发事件
6. 保留 `on_step` 回调，增加 `on_tool_round` 回调
7. 循环状态变更前后调用 `kit.save_state()` / `kit.load_state()`

**新增协议方法到 RuntimeKit**:
```python
@abstractmethod
async def llm_call(self, messages: list[dict], *, tools: list[dict] | None = None) -> LLMResponse: ...
@abstractmethod
async def execute_tools(self, tool_calls: list[ToolCall]) -> list[ToolResult]: ...
@abstractmethod
async def emit(self, event: RuntimeEvent) -> None: ...
@abstractmethod
async def save_state(self, state: LoopState) -> None: ...
@abstractmethod
async def load_state(self) -> LoopState | None: ...
@abstractmethod
def get_system_prompt(self) -> str: ...
@abstractmethod
def get_tools_schema(self) -> list[dict] | None: ...
```

**新增数据类**:
```python
@dataclass
class LLMResponse:
    message: dict          # 完整 assistant message
    tool_calls: list[ToolCall] | None
    finish_reason: str

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str         # JSON string

@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False

@dataclass
class LoopState:
    messages: list[dict]
    step_count: int
    metadata: dict         # Kit 自定义数据

@dataclass
class RuntimeEvent:
    type: str              # "step_start", "llm_call", "tool_call", "tool_result", "step_end", "error", "retry"
    data: dict
```

### Step 2: 增强 RuntimeKit 基类

> **⚠️ 原始规划 — 实际实现已偏离**：RuntimeKit 最终定位为薄适配层（协议桥接），不承载业务逻辑。
> `get_system_prompt()`、`get_tools_schema()`、`build_messages()`、`should_continue()` 等业务方法
> 未放入 Kit，而是由 HookSet（上下文注入、验收、决策）和核心循环承担。
> 实际 RuntimeKit 接口见 `core/src/lamtools_core/kernel/kit.py`（10 个方法，无 `tools` 字段）。
> 详见 `docs/platform-hook-slot-protocol.md`。

**文件**: `core/src/lamtools_core/kernel/kit.py`

1. 将 `RuntimeKit` 从简单 Protocol 升级为 `ABC`，包含上述所有抽象方法
2. 增加默认实现的 mixin 方法：
   - `build_messages(state: LoopState) -> list[dict]`：拼接 system_prompt + history + 最新 tool_results
   - `should_continue(state: LoopState) -> bool`：判断是否继续循环（默认 step_count < max_steps）
3. 增加 `KitConfig` dataclass：
   ```python
   @dataclass
   class KitConfig:
       max_steps: int = 50
       max_tool_rounds: int = 10
       retry: RetryPolicy = field(default_factory=RetryPolicy)
   ```

> **最终 Kit 只保留**：LLM 调用适配、工具执行、状态持久化、事件格式化。
> **HookSet 承载**：上下文注入、验收、决策影响、写回。

### Step 3: 增强 RetryPolicy

**文件**: `core/src/lamtools_core/kernel/policy.py`

1. 增加 `RetryPolicy` dataclass：
   ```python
   @dataclass
   class RetryPolicy:
       max_retries: int = 3
       retryable_exceptions: tuple[type[Exception], ...] = ()
       backoff_base: float = 2.0
       backoff_max: float = 60.0
   ```
2. 增加 `async def execute_with_retry(fn, policy) -> T` 工具函数

### Step 4: 增加 RuntimeEvent 体系

**文件**: 新建 `core/src/lamtools_core/kernel/events.py`

1. 定义 `RuntimeEvent` dataclass 及子类型常量
2. 事件类型枚举：
   - `STEP_START` / `STEP_END`
   - `LLM_CALL_START` / `LLM_CALL_END`
   - `TOOL_CALL_START` / `TOOL_CALL_END`
   - `TOKEN` (流式 token)
   - `ERROR`
   - `RETRY`
   - `STATE_SAVED` / `STATE_LOADED`
   - `CANCELLED`

### Step 5: 升级 WriterKit 为生产级

> **实际实现**：WriterKit 只保留薄适配层职责（LLM 调用适配、工具执行、状态持久化、事件格式化）。
> 业务逻辑（上下文注入、验收、决策影响、写回）由 WriterHookSet 承载。
> 详见 `docs/platform-hook-slot-protocol.md`。

**文件**: `members/writer/backend/app/core/writer/core_kernel_adapter.py`

1. 继承新 `RuntimeKit` ABC，实现所有抽象方法
2. `llm_call()`: 复用现有 `WriterLLMClientAdapter`，增加流式 token emit
3. `execute_tools()`: 从 legacy `WriterRuntime._execute_tool_calls()` 提取逻辑
4. `emit()`: 适配现有 SSE 事件系统，映射到 Writer 前端期望的事件格式
5. `save_state()` / `load_state()`: 使用现有 `WriterStateStore`（SQLite）
6. `get_system_prompt()`: 从 Writer 配置/任务加载
7. `get_tools_schema()`: 从 Writer tool registry 获取
8. ~~删除 `LAMWRITER_CORE_KERNEL` 环境变量门控~~ ✅ 已完成
9. ~~移除 legacy `WriterRuntime` 类~~ ✅ 已删除

> **最终 WriterKit 不包含**：get_system_prompt、get_tools_schema、build_messages、should_continue。
> 这些职责由 WriterHookSet（before_model / verify / decide_next / writeback）承担。

### Step 6: 升级 ArtistKit 为生产级

> **实际实现**：ArtistKit 只保留薄适配层职责（LLM/VLM 调用适配、工具执行、状态持久化、事件格式化）。
> 业务逻辑（上下文注入、验收、决策影响、写回）由 ArtistHookSet 承载。
> 详见 `docs/platform-hook-slot-protocol.md`。

**文件**: `members/artist/backend/app/core/artist/core_kernel_adapter.py`

1. 继承新 `RuntimeKit` ABC，实现所有抽象方法
2. `llm_call()`: 复用现有 `ArtistLLMClientAdapter` / `ArtistVLMClientAdapter`，增加流式 token emit
3. `execute_tools()`: 从 legacy `ArtistRuntime._execute_tool_calls()` 提取逻辑
4. `emit()`: 适配 Artist 事件系统
5. `save_state()` / `load_state()`: 升级 `InMemoryRuntimeStateStore` → 可选持久化（SQLite，与 Writer 对齐）
6. `get_system_prompt()`: 从 Artist 配置加载
7. `get_tools_schema()`: 从 Artist tool registry 获取
8. ~~删除 `LAMARTIST_ARTIST_CORE_KERNEL` 环境变量门控~~ ✅ 已完成
9. ~~标记 legacy `ArtistRuntime` 为 `@deprecated`~~ ✅ 已删除

> **最终 ArtistKit 不包含**：get_system_prompt、get_tools_schema、build_messages、should_continue。
> 这些职责由 ArtistHookSet（before_model / verify / decide_next / writeback）承担。

### Step 7: 统一 CLI 入口

**文件**: `members/writer/backend/writer_cli/__main__.py`, `members/artist/backend/app/cli.py`, `core/src/lamtools_core/runtime/`

1. CLI `run` 命令直接实例化 `CoreLoopKernel(kit=WriterKit(...))` 或 `CoreLoopKernel(kit=ArtistKit(...))`
2. 删除 CLI 中对 legacy runtime 的条件分支
3. 更新 `writer.cmd` / `artist.cmd` 无需改动（它们只是转发到 CLI）

### Step 8: 清理 core/runtime 模块

**文件**: `core/src/lamtools_core/runtime/`

1. 如有旧的 runtime shim，更新为指向 `kernel.loop.CoreLoopKernel`
2. 确保 `core/src/lamtools_core/__init__.py` 导出新 API

### Step 9: 更新文档

**文件**: `AGENTS.md`, `core/README.md`, `docs/monorepo-migration.md`

1. AGENTS.md: 更新"常用入口"说明，标注 runtime 已统一为 CoreLoopKernel
2. core/README.md: 更新 kernel 模块文档
3. monorepo-migration.md: 增加单轨迁移记录

---

## 执行顺序与检查点

| 批次 | 步骤 | 检查点 |
|------|------|--------|
| 1 | Step 3 (RetryPolicy) + Step 4 (Events) | `pytest core/` 通过 |
| 2 | Step 2 (Kit ABC) + Step 1 (CoreLoopKernel 增强) | `pytest core/` 通过 |
| 3 | Step 5 (WriterKit) | `pytest members/writer/` 通过 |
| 4 | Step 6 (ArtistKit) | `pytest members/artist/` 通过 |
| 5 | Step 7 (CLI 统一) + Step 8 (清理) | 手动验证 `writer.cmd run` / `artist.cmd run` |
| 6 | Step 9 (文档) | 文件内容与代码一致 |

## 风险与缓解

- **Writer/Artist 前端事件格式兼容**：Step 5/6 的 `emit()` 必须严格映射到前端期望的 SSE 事件格式，需逐字段对比
- **状态持久化回归**：Writer 已有 SQLite 存储，Kit 必须复用同一 schema；Artist 从内存升级到持久化需新增迁移
- **流式 token 中断**：CoreLoopKernel 主循环中加入 tool_result 子循环后，流式 token 的事件时序必须与前端渲染逻辑匹配

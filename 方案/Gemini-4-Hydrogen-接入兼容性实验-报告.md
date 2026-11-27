# Gemini 4 Hydrogen 接入兼容性实验 · 报告

- 对应 PRD：`方案/Gemini-4-Hydrogen-接入兼容性实验-PRD-V1.1.md`
- 实验日期：2026-11-26
- 结论：**十项核心指标全部通过；发现 1 个上游协议缺陷 + 1 处 Sunday 兼容性缺口，缺口已修复并回归。**
- 证据根目录：`.lam/artifacts/gemini4hy/`（原始报文、事件流、用例结果、截图）

---

## 0. 结论速览

| 编号 | 验收项 | 结果 | 关键证据 |
|---|---|---|---|
| E01 | 请求连通 | **PASS** | T01–T10 共 45 次真实模型调用，全部拿到有效响应 |
| E02 | 思考块 | **PASS** | 上游对复杂问题返回 `reasoning_content`，Sunday 按 `thinking` 块独立流式渲染（T02/T06/T10a） |
| E03 | 正文块 | **PASS** | 原始 SSE 的 `content` 分片与落库正文逐字一致（f1 案例） |
| E04 | 工具块 | **PASS** | 工具名/参数/上游调用 ID（`toolu_…`）/状态齐全 |
| E05 | 工具执行 | **PASS** | `read_file`、`write_file`、`run_command` 全部真实执行并回传结果 |
| E06 | 多轮调用 | **PASS** | 单轮最多 4 步工具循环（读→写→读回→作答） |
| E07 | Usage | **PASS** | 落库数值与上游末帧 `usage` **逐字段相等**（28440/216、28943/223） |
| E08 | 正常结束 | **PASS** | 每回合都有 `terminal` 终帧；主动取消得到 `cancelled` 并释放运行态 |
| E09 | 上下文连续性 | **PASS** | 同一会话追问，模型正确引用上一轮读到的两个文件数据（T07） |
| E10 | 渠道正确性 | **PASS（含推断）** | 模型 ID 经响应体与日志双重确认；渠道由「可用分组 + 反重力注入特征」判定为 Gemini 专线（0.4×），倍率本身无法用 sk key 读取（见 §5） |

---

## 1. 实际可用的 Provider 配置

配置**没有**写进代码，也没有用直调脚本替代；走的是 Sunday 用户可触及的配置体系——设置页同一套 RPC（`config.provider.create` / `config.model.create`），落到用户可编辑的 jsonc 文件。

### 1.1 供应商

`<核心配置根>/config/providers/xingpan.jsonc`：

```json
{
  "id": "xingpan",
  "name": "星盘",
  "api_type": "openai",
  "base_url": "https://xingpan.site/v1",
  "api_key": "<实验用临时 Key，用户实验后可撤销>",
  "is_default": false,
  "notes": "",
  "adapter_profile_id": "openai-chat"
}
```

### 1.2 模型

`<核心配置根>/config/models/xingpan-gemini-4-hydrogen.jsonc`：

```json
{
  "id": "xingpan-gemini-4-hydrogen",
  "model_id": "gemini-4-hydrogen",
  "display_name": "Gemini 4 Hydrogen",
  "provider": "星盘",
  "context_window": 1000000,
  "max_output_tokens": 32768,
  "temperature": 0.7,
  "thinking": { "supported": false, "budget": 10000 },
  "adapter_profile_id": "",
  "capability": "text",
  "output_type": "text",
  "notes": "星盘 Gemini 专线 0.4x",
  "is_default": false,
  "enabled": true,
  "provider_id": "xingpan"
}
```

- 协议：**OpenAI Chat Completions**（`adapter_profile_id: openai-chat`）。选它而不是 Gemini 原生协议，理由见 §3.4。
- `thinking.supported=false`：接口接受推理参数但不保证返回可展示思考内容，因此不主动索要、也不向界面承诺；上游若自行返回思考，Sunday 仍然照常捕获（E02 已证）。

### 1.3 落点说明

| 实例 | 配置根 | 状态 |
|---|---|---|
| 打包版（用户日常使用，`C:\sunday\constant`） | `C:\sunday\constant\.lam\core\config\` | 已通过设置接口写入，模型可选中运行 |
| 源码构建（验证本轮修复，`E:\LamTools`） | `E:\LamTools\core\.lam\core\config\` | 同上，用于端到端验收 |

---

## 2. 模型、协议与计费渠道

| 项目 | 实测结果 | 来源 |
|---|---|---|
| API Base | `https://xingpan.site/v1` | 实际请求成功 |
| 模型 ID | `gemini-4-hydrogen` | `/v1/models`、响应体 `model` 字段、Sunday 日志三处一致 |
| 可用端点 | `openai`、`gemini` 原生；实测 `/v1/messages`（Anthropic）也通 | `/api/pricing` + 四路实测 |
| 同名变体 | `gemini-4-hydrogen-as`（按次 0.021 元/次，Ai Studio Gemini 组）、`gemini-4-hydrogen-vip`（Gemini VIP 8×，仅 openai） | `/api/pricing`，**本次未使用** |
| 计费口径 | `model_ratio=0.75`、`completion_ratio=5`、`cache_ratio=0.05`，按 Token 计费 | `/api/pricing` |
| 可用分组 | `Gemini官Key`(2.5×)、`Gemini专线`(0.4×) | `/api/pricing` 的 `enable_groups` |
| 实际渠道 | **Gemini 专线（0.4×）** | 见 §5 推断链 |

---

## 3. 上游协议基线（Phase 2）

### 3.1 端点与模型发现

```
GET /v1/models → 200，13 个模型，含 gemini-4-hydrogen（supported_endpoint_types=["gemini","openai"]）
```

### 3.2 流式响应结构（OpenAI 兼容路径，正式采用）

```
data: {"choices":[{"delta":{"role":"assistant"},"finish_reason":null}]}
data: {"choices":[{"delta":{"content":"…"}}]}          ← 正文分片，顺序到达
data: {"choices":[{"delta":{"reasoning_content":"…"}}]}  ← 复杂问题才出现（思考）
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"toolu_…","function":{"name":"read_file","arguments":""}}]}}]}
data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\"path\":\"a.txt\"}"}}]}}]}
data: {"choices":[{"delta":{"content":""},"finish_reason":"tool_calls"}]}   ← 也可能是 "stop"
data: {"choices":[],"usage":{"prompt_tokens":28440,"completion_tokens":216,"total_tokens":28656}}
data: [DONE]
```

- **Usage 位置**：尾部独立一帧（`choices` 为空数组），需 `stream_options.include_usage=true`。
- **思考**：`delta.reasoning_content`，与正文同帧不同字段。
- **结束信号**：`finish_reason` 帧 + 尾部 usage 帧 + `[DONE]`。
- **多轮上下文**：标准 `assistant.tool_calls` + `role:"tool"` + `tool_call_id`，实测第二轮正常续写。

### 3.3 上游缺陷（重要）

同一响应内的**多个并行工具调用被折叠进同一个 `index`**，且第 2 个起**不带 id、不带 name**：

```json
{"index":0,"id":"toolu_e745d578d5e1a54b","function":{"name":"read_file","arguments":""}}
{"index":0,"function":{"arguments":"{\"path\":\"a.txt\"}"}}
{"index":0,"function":{"arguments":"{\"path\":\"b.txt\"}"}}
```

按 OpenAI 规范拼接后得到 `{"path":"a.txt"}{"path":"b.txt"}`（32 字符，非合法 JSON）。
`parallel_tool_calls:false` 被上游忽略；换 Gemini 原生协议后，续接的 `functionCall` 的 `name` 直接是空字符串；换 `/v1/messages` 后，两个 `input_json_delta` 落在同一个 `tool_use` 块里。**三个协议都同一个毛病，属于上游（反重力线路）输出缺陷，不是 Sunday 解析错误。**

### 3.4 为什么不用 Gemini 原生协议

原生路径实测有两个硬伤：

1. `usageMetadata.candidatesTokenCount` 恒为 0，`totalTokenCount` 只等于 `promptTokenCount` —— 无法满足 E07 的用量准确性。
2. 续接 `functionCall` 丢 `name`，工具无法可靠执行。

原生路径唯一的好处是不注入 ~8.2k token 的线路前缀（`promptTokenCount` 仅 11–36），但代价是工具与用量双双不可用，故弃用。

---

## 4. 十项指标的证据

用例全部在 Sunday 真实运行链路里跑（会话创建 → 回合 → 工具 → 落库 → 事件流），测试文件位于临时工作区 `E:\LamTools\.lam\tmp\gemini4hy\exp\`。

### E01 请求连通

T01 简单问答：`model=xingpan-gemini-4-hydrogen`，首字 5.61s，1 步完成，`decision=done`。

### E02 思考块

- T02（三位数推理）首事件即为 `thinking_delta`，落库为独立 `thinking` 项：
  `"Defining a three-digit number with non-zero digits $x, y, z$…"`
- 同回合正文另存 `message` 项，二者不混。原始 SSE 中该内容来自上游 `reasoning_content`（Sunday 不做任何生成）。
- 上游对简单问题（T01）不返回思考，Sunday 也不会凭空造思考块 —— 符合 PRD「不得伪造」。
- 有用例：T06、T10a、T10b 同样出现思考块；T03/T05 无思考但正文正常。

### E03 正文块

- 原始 SSE 的 4 段 `content`（`根据 [a.txt](file:///E:/Lam…` 等）与落库正文逐字一致，顺序一致，无重复。
- 流式期间 Kernel 日志记录 `content_delta` 计数与首字耗时，界面逐段渲染（截图见 §6）。
- 思考、工具参数、协议元数据均未混入正文。

### E04 工具块

事件流中的 `tool_call` 项包含：

```json
{"kind":"tool_call","status":"running","payload":{"tool_name":"read_file",
 "arguments":{"path":"a.txt"},"summary":"开始执行工具：read_file"}}
```
`item_id` 内保留上游调用 ID（`…:toolu_e135957e4dfdbf4e:tool`），随后同一 `item_id` 上转为 `tool_result/completed`。

### E05 工具执行

`read_file`（读 a.txt/b.txt/c.txt）、`write_file`（sum_a.txt 等）、`run_command`（`printf '10' > calc.txt`）均真实执行，回传内容与磁盘一致；`calc.txt` 内容经二次读取确认为 `10`。

### E06 多轮调用

T06 一个回合内 4 次模型请求：读 a.txt → `run_command` 写 calc.txt → 读回确认 → 作答。
T10a/b/c 各 4 次请求（读 → 写 → 读回 → 作答），全部正常收口。

### E07 Usage

f1 回合（两轮请求）逐字段对照，**完全一致**：

| | 上游原始 `usage` | Sunday 落库 |
|---|---|---|
| 第 1 次 | prompt 28440 / completion 216 / total 28656 | input 28440 / output 216 / calls 1 |
| 第 2 次 | prompt 28943 / completion 223 / total 29166 | input 28943 / output 223 / calls 1 |

- 缓存字段解析正确：后续轮次出现 `prompt_tokens_details.cached_tokens=26687` 时，落库 `cached_tokens` 同为 26687。
- 一次请求只记一行（`calls=1`），无重复累计；未把 0.4× 倍率写进 token 数。

### E08 正常结束

- 正常回合：`item_id` 以 `:terminal` 结尾的 `core/runItem` 且 `status=completed`，随后 `session/updated`；未出现无限等待。
- 主动取消（T08，`ping -n 60` 执行中取消）：12.2s 收到 `terminal/cancelled`，会话 `status=cancelled`，无残留运行态，可继续发新回合。
- 工具轮次结束≠任务结束：T03/T06 中 `finish_reason=tool_calls` 后继续发起下一轮请求。

### E09 上下文连续性

T07 在 T04 的同一会话追问「香蕉+橙子多少个」：模型回答 14，并明确指出「香蕉 5 个来自 a.txt、橙子 9 个来自 b.txt」——证明历史消息（含工具结果）被正确携带。

### E10 渠道正确性

见 §5。

---

## 5. E10 渠道判定链

1. **模型确认**：三类证据一致 —— 请求体 `model=gemini-4-hydrogen`、响应体 `"model":"gemini-4-hydrogen"`、Sunday 日志 `model=xingpan-gemini-4-hydrogen`。
2. **可用分组收缩**：`/api/pricing` 显示 `gemini-4-hydrogen` 的 `enable_groups` 只有 `Gemini官Key`(2.5×) 与 `Gemini专线`(0.4×)，`-as`/`-vip` 是另外两个独立模型 ID，本次未使用。
3. **渠道形态判别**：实测请求带 ~8.2k token 的线路前缀（一句「天空为什么蓝」也报 `prompt_tokens=8332`，而原生端点同一问题只有 11），响应 ID 形如 `msg_…`、工具 ID 形如 `toolu_…`，模型 `/api/pricing` 标签为「反重力」——这是反重力（专线）线路的典型特征，官方 Google API 不会注入此类前缀、也不会用 Anthropic 风格的 ID。
4. **无法直接读取的部分**：用 sk key 访问 `/api/user/self`、`/api/token/`、`/api/log/self` 全部 401（这些接口只认网页登录态），因此**无法从接口侧读到令牌所属分组与倍率的原始字段**。本项以 3 的证据链判定为专线，倍率按公开 0.4× 计费；若用户控制台显示令牌分组为「Gemini官Key」，则本条需改判（费用将差 6.25 倍）。

---

## 6. 界面运行截图

- `shot-ui-session-crop.png`：会话「Gemini4Hy f1」，模型徽标 **Gemini 4 Hydrogen**、耗时 13s、答复「苹果 4 / 香蕉 5 / 橙子 9」，输入框选择器为「Gemini 4 Hydrogen • 关闭」。
- 截图取自源码构建实例（含本轮修复），窗口标题 Sunday，左侧导航与输入栏为真实界面。

---

## 7. 发现的问题、根因与修复

### 7.1 上游缺陷：并行工具调用被折叠（不入 Sunday 代码层）

- **定位层**：1（中转站/上游协议）。
- **证据**：§3.3 的三协议原始报文；Sunday 侧报错 `Model tool arguments were incomplete or invalid JSON … (received=32 chars)` 与此 32 字符拼接串严格吻合。
- **影响**：修复前，一次要求读两个文件的回合会连续 5 次失败并最终放弃（T04 修复前实录）。

### 7.2 Sunday 兼容性缺口：折叠参数无法还原（已修复）

- **定位层**：3（流式事件解析）→ 4（工具执行循环）。
- **根因**：`resolve_tool_calls` 严格按「一个 index = 一次调用」组装，遇到多个完整 JSON 对象拼接时只判定为非法 JSON 并拒绝执行。拒绝本身是安全的，但对这类真实存在的中转形态没有恢复能力。
- **修复（通用、非该中转专用）**：
  - `core/src/lamtools_core/llm/helpers.py`
    - 新增 `split_folded_tool_arguments()`：仅当参数串是**两个及以上完整 JSON 对象、彼此仅隔空白**时才拆分；截断、尾随内容、非对象值一律返回空，维持原有的报错行为。
    - `resolve_tool_calls(..., repair_folded_arguments=True)`：按对象拆成 N 个调用，逐个给出唯一 id（首个保留上游 id，其余 `<id>-<n>`，无 id 时生成 `call_<hex>`），函数名沿用唯一到达的那一个，并在 metadata 标记 `folded_tool_arguments` / `folded_tool_argument_index` 便于追溯。
  - `core/src/lamtools_core/kernel/loop.py`
    - 新增 `_folded_tool_call_repair_enabled()`：默认开启；provider/model 的 `extra` 可写 `folded_tool_call_repair: false` 关闭（模型配置优先）。
    - 流式收尾调用改为 `resolve_tool_calls(pending_tool_calls, repair_folded_arguments=…)`。
- **已知局限（如实记录）**：上游对第 2 个起的并行调用**不发函数名**，因此还原出的后续调用沿用首个调用的函数名。同名工具多次调用（读多个文件）能精确还原；若一次要调**不同工具**，第二个调用的名字无法可靠还原，本次实验中未出现该形态（上游只会吐出第一个工具）。
- **效果**：T04 从「5 次失败后放弃」变为「两次 read_file 成功 + 正确统计」，f1 回合同样两读成功。

### 7.3 观察项（不作为缺陷处理）

| 观察 | 说明 |
|---|---|
| 每次请求约 8.2k token 线路前缀 | 上游注入，非 Sunday 构造；影响费用不影响功能 |
| `finish_reason` 偶发为 `stop` 但带 tool_calls | 上游不规范；Sunday 以实际 tool_calls 为准，未受影响 |
| Gemini 原生端点 usage 不可用 | 已弃用该协议（§3.4） |
| 流结束后客户端的 `GeneratorExit` | 拿到 `[DONE]` 后主动关闭连接，forensics 记为 `operation_state=failed`、但 `capture_state=complete`，不是功能失败 |
| 缺失缓存字段时 `cached_tokens=0` | 上游本次未返回 `prompt_tokens_details`，落库为 0 且 `usage_available=1`；属于「未上报」而非「虚报」，与有上报时的 26687 等值可区分 |

---

## 8. 修改文件与回归测试

| 文件 | 变更 |
|---|---|
| `core/src/lamtools_core/llm/helpers.py` | 新增 `split_folded_tool_arguments`、`_folded_call_id`，扩展 `resolve_tool_calls` |
| `core/src/lamtools_core/kernel/loop.py` | 新增 `_folded_tool_call_repair_enabled`，流式工具组装接入开关 |
| `core/tests/test_tool_call_folded_arguments.py` | 新增 9 个用例（拆分 2/3 个对象、含空白、单调用不变、截断仍报错、非对象不拆、关开关回退、无 id 时合成唯一 id、metadata） |

测试结果：

```
tests/test_tool_call_folded_arguments.py                 9 passed
tests/test_llm_helpers.py test_llm.py test_llm_profiles.py
tests/test_llm_adapter.py test_llm_stream_merged_chunk.py  207 passed
```

**已有模型回归（真实链路）**：`opencode-go-deepseek-v4.1-flash` 在同一实例跑了纯问答（`2+3 等于 5。`）与工具回合（读 a.txt → 答「香蕉 5 个，苹果 3 个」），思考块、工具块、正文均正常；同一修复对其他模型的合法参数永不触发。

---

## 9. 用量与费用

### 9.1 Sunday 链路（可核实，来自 `usage.db`）

| 项 | 值 |
|---|---|
| 模型调用次数 | **45 次** |
| 输入 Token | **1,292,106**（其中缓存命中 401,648） |
| 输出 Token | **10,179** |
| 会话数 | 18（含 2 次受上游缺陷影响的历史会话） |

按星盘公开口径（`model_ratio 0.75`、`completion_ratio 5`、`cache_ratio 0.05`、分组 0.4×）：

| 组成 | 费用 |
|---|---|
| 非缓存输入 890,458 | $0.5343 |
| 缓存命中 401,648 | $0.0120 |
| 输出 10,179 | $0.0305 |
| **合计** | **≈ $0.577（约 ¥4.2，按 ¥7.3/$）** |

若令牌实际走的是「Gemini官Key（2.5×）」，同量费用为 ≈ $3.61，相差 6.25 倍 —— 这是 E10 需要用户到控制台确认分组的唯一原因。

### 9.2 直连基线探测（Phase 2，不含在 Sunday 台账内）

13 次请求：OpenAI 兼容 10 次（每次 ≈8.3k 输入）、Gemini 原生 3 次（11–36 输入）。按同口径估算 **≈ $0.057（约 ¥0.4）**。

> 费用为按公开倍率换算的估算值；控制台账单为最终依据。

---

## 10. 尚未解决 / 需知会

1. **打包版需要重新构建**：修复只在源码构建中验证通过。用户日常使用的 `C:\sunday\constant\Sunday.exe`（PyInstaller 打包）仍是旧代码，并行工具调用仍会失败；配置已在其中生效，功能验证等下一次打包发布。
2. **E10 的倍率字段**：sk key 无法读取令牌分组（接口 401），需用户在控制台核对令牌分组是否为「Gemini专线」。
3. **不同工具并行调用**：上游只给第一个调用名，Sunday 只能按同名还原；若上游将来对不同工具也并行输出，需要上游补齐 `name`，或由中转修正折叠逻辑。
4. **思考强度不可控**：该线路不提供可用的思考开关（`thinkingBudget` / `thinkingLevel` / `reasoning_effort` 均被忽略或无效），思考内容由上游自行决定，模型配置因此声明 `thinking.supported=false`。
5. **临时 Key**：仅存在于配置文件中（未进代码、未进提交），实验结束可由用户撤销。

---

## 11. 复现方式

1. 设置 → 供应商：名称「星盘」、Base URL `https://xingpan.site/v1`、协议 OpenAI、Key 粘贴实验 Key。
2. 设置 → 模型：模型 ID `gemini-4-hydrogen`、上下文 1,000,000、最大输出 32,768、关闭「支持思考」。
3. 选该模型新建会话，让它「分别读取两个文件并汇总」——修复后会看到两次 `read_file` 成功后给出汇总；修复前会报「工具参数不完整或非法 JSON」。
4. 原始报文复现：以 `LAMTOOLS_LLM_RAW_RECORDING=1`、`LAMTOOLS_LLM_FORENSIC_DIR=<目录>` 启动核心，即可在目录内得到 `request.bin` / `response.bin`（不含请求头与密钥）。

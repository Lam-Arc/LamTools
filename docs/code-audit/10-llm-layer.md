# 10 LLM 适配层 审计报告

## 1. 概况

- **审计范围**：`core/src/lamtools_core/llm/` 全部 8 个源文件（约 2.1k 行）：
  `__init__.py`（协议类型 270 行）、`helpers.py`（613 行）、`adapter.py`（112 行）、
  `retry.py`（240 行）、`policy.py`（44 行）、`profiles.py`（505 行）、
  `model_capabilities.py`（44 行）、`shallow_thinking.py`（298 行）。
- **参考配置**：`core/config/llm_adapters/*.jsonc`（openai-chat / anthropic-messages / xfyun-coding-plan）、
  `core/.lam/core/config/model_retry.jsonc`（retry_delays_seconds=[1,1,2,5,5]、model_retries=10、
  model_timeout_seconds=360、model_stream_idle_timeout_seconds=120、empty_response_retries=3、jitter=true）。
- **关键背景（架构事实）**：
  - llm/ 目录本身是**纯转换/策略层，无网络依赖**。真正的 HTTP+SSE 客户端是
    `cli.py` 的 `CoreHttpLLMClient`（走 profiles 的 `build_profiled_openai_request` /
    `normalize_stream_chunk_with_profile`），kernel/loop.py 通过 `stream_with_retry` /
    `complete_with_retry` 消费。
  - `adapter.py`（LLMAdapter / OpenAICompatibleAdapter）及 helpers 中非 profile 版
    归一化函数（`normalize_openai_response` / `normalize_stream_chunk` 等）在本仓
    **无任何消费者，属死代码**（见问题 14），但其行为差异仍是公开 API 语义隐患。
  - 重试装配点：`default_agent.create_kernel`、`cli.py`、`tool/sub_agent_runner.py`
    均通过 `config/retry_store` 从 model_retry.jsonc 读取并显式传参。
- **审计方法**：全静态阅读 + grep/git 交叉验证 + 只读 `python -c`/stdin 片段对关键
  路径做行为复现（未运行 pytest、未启动服务、未调用任何 LLM）。
- **结论概览**：未发现 S1（无密钥泄漏、无未授权路径、无数据损坏级缺陷）。主要问题集中在
  错误分类与真实客户端的脱节（4xx 被当瞬时错误重试、Retry-After 死路径）、
  JSONC 配置解析对字符串内容的静默破坏、以及两套流式归一化路径并存导致的行为分叉。

## 2. 问题清单

### 2.1 错误分类与重试

- **[S2] 4xx 客户端错误（401/403/400/404）被分类为"可重试"，最多重试 10 次**
  - 位置：`llm/retry.py:39-71`（`classify_model_error`）；根因在 `cli.py:187-188,216-219`
    （`CoreHttpLLMClient` 对 `status_code >= 400` 一律抛 `RuntimeError("LLM API error {status}: {text[:300]}")`）。
  - 问题：分类只按异常类型名（`TokenOverflowError`/`RateLimitError`）或**错误消息文本**匹配。
    401/403/404 等文本既不命中 `fatal` 标记（"model not found" 等）也不命中 `rate_limit`（"429"），
    落入 `"retryable"` → `complete_with_retry`/`stream_with_retry` 按 model_retries=10 重试，
    退避节奏 1,1,2,5,5（约 34s 无效等待）；`_call_model`（`kernel/loop.py:2075-2096`）的
    "401 不该重试"语义仅靠消息文本兜底，不可靠。
  - 影响：API key 无效 / 权限不足 / 请求参数非法时，每次模型调用卡顿约 34 秒并发送 10 次
    无效请求，重试遥测（runtime.model_retry 事件）被 4xx 污染；还可能触发供应商侧的
    额外限流计数。
  - 修复建议：让客户端把状态码结构化（自定义 `LLMProviderError(status_code, ...)`），
    `classify_model_error` 按 `4xx（除 429/408）→ fatal`、`5xx → retryable`、`429 → rate_limit`
    分类，消息文本匹配仅作兜底。

- **[S3] Retry-After 语义是死路径：`RateLimitError` 全仓无人构造，429 退避从未兑现**
  - 位置：`llm/retry.py:51,227-232`；`kernel/errors.py:19-25`；`kernel/loop.py:2070-2073`（注释声称
    "HTTP 429 → honor Retry-After if present"）。
  - 问题：全仓 grep 无任何 `raise RateLimitError(...)` 调用点，`classify_model_error` 的
    `name == "RateLimitError"` 分支与 `_delay_for_error` 的 `getattr(exc, "retry_after", ...)`
    均为不可达代码。真实 429 只靠消息文本 "429" 命中 `rate_limit`，退避走固定序列
    （`retry.py:74-81`），服务端 `Retry-After` 头被丢弃。另：`_delay_for_error` 中
    `float(retry_after)` 与 `retry_after > 0` 对字符串值（HTTP-date 格式）会抛
    ValueError/TypeError，且对超大值无上限——目前不可达，但一旦成员包按文档补上
    `RateLimitError(retry_after=header)` 即触发。
  - 影响：高并发限流场景（如讯飞 maas）可能因无视 Retry-After 反复撞限流；文档承诺与
    实现断裂，误导后续开发者。
  - 修复建议：在 `CoreHttpLLMClient` 解析 `Retry-After` 头并构造 `RateLimitError`；
    `_delay_for_error` 对非数值容错并 `min(retry_after, 上限)`（如 120s）。

- **[S3] `stream_with_retry` 的超时是"整流总时长"而非"空闲超时"，语义与配置名不符**
  - 位置：`llm/retry.py:130-151`（`asyncio.wait_for(stream, ...)` 包 setup；
    `async with asyncio.timeout(timeout): async for ...` 包整个消费循环）。
  - 问题：`model_stream_idle_timeout_seconds` 的"每事件空闲"语义由 kernel 的
    `_next_stream_event`（`kernel/loop.py:1811-1815`）在 loop 层实现，retry.py 内的时间
    `timeout` 一旦被设置（或 `LLMRequest.timeout` 被设置）则成为整个流的墙钟上限——
    若消费者处理事件较慢（如 `event_sink.emit` 阻塞），可能误杀仍在推送数据的流；
    中途超时时若 `emitted=True` 直接 re-raise，已产出内容全部丢弃。当前 kernel 路径
    传 `timeout_seconds=None` 规避了该分支，但作为公开 API 语义有歧义。另外
    `inspect.isawaitable(stream)`（retry.py:132）对 async-generator 型客户端恒为 False，
    setup 超时分支实际只对 coroutine 型客户端生效，两种客户端超时行为不一致。
  - 影响：被其它装配点（如子代理、成员客户端）误用时，流式调用可能被整流超时打断，
    或 setup 阶段无超时保护（依赖客户端自身 connect 超时）。
  - 修复建议：删除整流 `asyncio.timeout` 包裹，统一由调用方按事件粒度做空闲超时；
    setup 阶段单独用 `asyncio.wait_for(stream.__anext__(), timeout)` 或明确按客户端类型分派。

- **[S4] `LoopPolicy.model_retries` 代码默认 100 与配置/文档默认 10 不一致**
  - 位置：`kernel/policy.py:22`（`model_retries: int = 100`）；`config/retry_store.py:40`
    （`DEFAULT_MODEL_RETRY_CONFIG["model_retries"] = 10`）；`llm/policy.py:19` 注释称
    "jsonc 镜像代码默认值"。
  - 问题：现有装配点均通过 `loop_policy_overrides` 覆盖，实际生效 10；但任何绕过装配点
    直接 `LoopPolicy()` / `CoreLoopKernel(policy=LoopPolicy())` 的路径（如新增入口、
    测试、成员代码）会拿到 100 次重试：最坏墙钟 ≈ 100×360s 超时 + 退避 ≈ 10 小时。
  - 修复建议：统一代码默认值为 10，或让装配点强制校验。

- **[S4] 超时重试的非幂等成本：服务端可能已完成生成，重试造成重复计费**
  - 位置：`llm/retry.py:94-99`（`asyncio.wait_for` 超时后取消底层调用并重试同一请求）。
  - 问题：LLM 调用无副作用，重试不会造成业务重复执行，但超时瞬间服务端可能已完成推理，
    重试会重复消耗 token 配额与费用（10 次重试 × 大 prompt 成本可观）。
  - 修复建议：可接受，建议在重试事件/日志中标记 `kind=timeout` 供上层统计重复成本。

### 2.2 流式解析与 usage 归一化

- **[S3] `parse_tool_call_arguments` 对 dict 类型 arguments 抛 AttributeError（实测复现）**
  - 位置：`llm/helpers.py:68`（`args_str.strip()`）；未受保护的调用点
    `helpers.py:369-370`（`normalize_openai_response`）与 `helpers.py:411-412`
    （`_resolve_raw_tool_calls`）。
  - 问题：`chat_message_from_openai`（helpers.py:288）有 `isinstance(raw_arguments, str)`
    保护，但上述两处把 `fn.get("arguments", "")` 直接传入。若供应商在非流式响应或
    流式最终 chunk 中直接给出已解析的 dict 型 arguments（部分网关/代理有此行为），
    空 dict 走 `not args_str` 侥幸返回 `{}`，非空 dict 在 `.strip()` 处抛 AttributeError，
    整个模型调用崩溃（流式路径还会触发"流式中断→非流式兜底"的假象）。
  - 修复建议：在 `parse_tool_call_arguments` 开头加 `if not isinstance(args_str, str): return {}`，
    或两处调用点补 isinstance 保护（与 chat_message_from_openai 对齐）。

- **[S3] `normalize_stream_chunk` 在"delta.content + finish_reason 同 chunk"时吞掉 done 事件与 usage（实测复现）**
  - 位置：`llm/helpers.py:497-516`（content 分支先返回，done 分支永远轮不到）。
  - 问题：实测 `{"choices":[{"delta":{"content":"bye"},"finish_reason":"stop"}],"usage":{...}}`
    只返回 `content_delta`，usage 与真实 finish_reason（如 length/tool_calls）全部丢失；
    消费方落入"流结束无 done"兜底（`kernel/loop.py:1752-1779`），finish_reason 被默认成
    "stop"，usage 仅当存在独立 usage chunk 才保留。而 profile 版
    `normalize_stream_chunk_with_profile`（profiles.py:362-392）有专门注释"delta 必须先于
    finish_reason 处理"，行为正确——两套归一化路径行为分叉。
  - 影响：当前 kernel 路径走 profile 版不受影响，但 helpers 公开 API 语义不一致，
    任何复用非 profile 版的调用方（成员、测试、未来重构）都会静默丢 usage 与 finish_reason。
  - 修复建议：统一为 profile 版的顺序（delta 各分支 → 最后才发 done 并携带 usage/finish_reason），
    或删除非 profile 版（见问题 14）。

- **[S4] `extract_thinking_content` docstring 声称支持 `delta.reasoning_content`，实现未处理**
  - 位置：`llm/helpers.py:221-234`（docstring 列出 "delta.reasoning_content"，代码只查
    message 顶层 `thinking` / `reasoning_content`）。
  - 影响：注释与实现不符，误导调用方；对嵌套 delta 结构的 thinking 提取返回空串。
  - 修复建议：补实现或改 docstring；该函数当前无外部消费者，建议随死代码清理一并处理。

- **[S4] `_usage_int` 对不可转数字的 token 值静默归 0**
  - 位置：`llm/helpers.py:138-147`（`int(value)` 抛 ValueError/TypeError 时返回 0）。
  - 影响：供应商返回带千分位字符串（"1,234"）等格式时 token 计量静默丢失，无日志。
  - 修复建议：容错时记录 warning 或按 len/4 估算兜底。

### 2.3 profiles / JSONC 配置解析

- **[S3] `load_jsonc` 的尾逗号正则破坏字符串字面量内容（实测复现）**
  - 位置：`llm/profiles.py:63`（`re.sub(r",(\s*[}\]])", r"\1", strip_jsonc(text))`）。
  - 问题：`strip_jsonc` 正确处理了字符串内的注释，但尾逗号清理是**无字符串感知的纯正则**。
    实测 `{"prompt": "choose A,} or B,]", "list": [1, 2,]}` 被解析成
    `"choose A} or B]"`——字符串内合法的 ",}"、",]" 序列被静默删除。
  - 影响：adapter profile 的 `request.body` 中若含此类字符串（如提示模板、含 ",}" 的文本），
    发给供应商的请求内容被悄悄改写，极难排查；当前三个内置 profile 未触发，属潜伏缺陷。
  - 修复建议：把尾逗号清理并入 `strip_jsonc` 的字符串感知状态机（与注释清理同路径），
    并在解析失败/可疑时记录告警。

- **[S3] `_matches_base_url` 把配置里的 match_base_url 当正则执行**
  - 位置：`llm/profiles.py:461-470`（`re.search(text, lowered)`）。
  - 问题：`xfyun-coding-plan.jsonc` 的 `match_base_url` 含 `xf-yun\\.com` 等转义，作者显然
    按正则书写；但普通用户/供应商写 `api.example.com` 时 `.` 会通配任意字符，造成误匹配；
    配置中出现非法正则（如未闭合括号）时 `re.search` 抛 `re.error`，`resolve_adapter_profile_from_profiles`
    （profiles.py:145-148）无 try 保护，直接中断 profile 解析。
  - 影响：profile 误选导致请求发错端点/协议；非法正则导致模型调用前置崩溃。
  - 修复建议：`re.compile` 包 try/except，非法模式降级为子串匹配或跳过并告警。

- **[S4] `normalize_response_with_profile` 对非字符串 content 直接 str() 化**
  - 位置：`llm/profiles.py:411`（`str(raw_content)`）。
  - 问题：OpenAI 兼容供应商若返回 content 为 block 列表（部分网关），会得到
    `"['text', ...]"` 的 Python repr 字符串，正文被 mangled；Anthropic 有专门路径
    （profiles.py:419-442），其他 block 型供应商无。
  - 修复建议：非字符串 content 时按 block 列表提取 text 块，或置空并告警。

- **[S4] `build_profiled_openai_request` 开启 thinking 时无条件 pop temperature，包括 profile body 显式设置值**
  - 位置：`llm/profiles.py:230-235`。
  - 问题：注释说明了讯飞 GLM 的场景动机，但对所有 profile（含 openai-chat / anthropic）
    一律生效，无法按 profile 关闭；若 profile 的 `request.body` 显式配置了 temperature，
    也会被一并移除。
  - 修复建议：将"thinking 时不传 temperature"做成 profile 可配项（如 `thinking.drop_temperature`），
    默认仅对需要该行为的供应商开启。

### 2.4 shallow_thinking

- **[S3] 模型不输出 START 标记时，正文被整体缓冲，流式输出退化为"结束时一次性吐出"**
  - 位置：`llm/shallow_thinking.py:165-183`（feed 的 "before" 状态把所有文本累积进
    `_prefix_buffer`，直到找到 START 或 `finish()` 才释放）；释放点仅在
    tool_call_delta（115-119）与 done（120-128）。
  - 问题：开启 shallow thinking 的模型若未遵守格式（弱模型、长指令、工具优先响应），
    全部正文在流结束前不可见，UI 上表现为"卡住后突然全部输出"，且前缀内存随响应长度增长。
    测试（tests/test_shallow_thinking.py）确认这是当前设计行为。
  - 影响：shallow_thinking_enabled 用户的流式体验在该场景下显著劣化，且无法区分
    "模型在思考"与"输出被缓冲"。
  - 修复建议：为 `_prefix_buffer` 设长度阈值（如 >4KB 强制作为 content 提前 flush 并放弃
    思考前置），或在超时/首 token 延迟时降级为直通模式。

- **[S4] 原生 thinking_delta 在 shallow 块未闭合时到达：部分 thinking 内容作为正文泄漏、标记被吞**
  - 位置：`llm/shallow_thinking.py:109-113`（thinking_delta 分支）+ `157-163`
    （`release_pending_content` 清空 `_thinking_buffer` 且 `mark_has_thinking` 只在
    state=="before" 时改变状态）。
  - 问题：state=="thinking"（START 已见、END 未闭合）时收到原生 thinking_delta，
    `_thinking_buffer` 中已累积的浅思考文本被丢弃，START 标记之后的半截内容随
    `_prefix_buffer` 作为正文发出。
  - 修复建议：`mark_has_thinking` 对 "thinking" 状态也先完成当前块（flush 为 thinking_delta）
    再切换，或保留 `_thinking_buffer` 并入 release 的 content。

### 2.5 死代码与一致性

- **[S4] `adapter.py` 整模块死代码；非 profile 归一化路径与 profile 版并存是行为分叉温床**
  - 位置：`llm/adapter.py:23-106`（LLMAdapter / OpenAICompatibleAdapter）；
    无消费者的 helpers：`normalize_openai_response`（helpers.py:345）、
    `normalize_stream_chunk`（helpers.py:428）、`chat_message_from_openai`（helpers.py:275）、
    `extract_thinking_content`（helpers.py:221）、`merge_system_messages`（__init__.py:196）、
    `sum_usage`（__init__.py:216）。
  - 问题：grep 确认这些符号在本仓仅被 llm/ 内部互相引用，无外部调用者；真实适配链路是
    profiles.py + `CoreHttpLLMClient`。两套流式归一化（helpers 非 profile 版 vs profiles
    profile 版）并存，且已产生行为不一致（见 2.2 第二条），未来任何"顺手复用"都会踩坑。
  - 修复建议：若作为成员包公开 API 保留，需在模块 docstring 注明已废弃并指引 profile 版；
    否则删除 adapter.py 与未用 helpers，收敛为单一解析路径。

- **[S4] `model_capabilities.py` 的 `model_id` 参数被忽略**
  - 位置：`llm/model_capabilities.py:25-38`（`resolve_capability` / `is_text_model`）。
  - 问题：docstring 已声明 jsonc 的 capability 字段权威、model_id 不参与判定，但形参保留，
    调用方容易误以为按 model_id 判定能力。
  - 修复建议：删除形参或改名 `_model_id` 并加弃用注释。

## 3. 该区 Top 3 问题

1. **4xx 客户端错误被当作瞬时错误重试 10 次（S2，retry.py:39-71 + cli.py:187-188）**——
   错误分类只认类型名与消息文本，而真实客户端把一切 >=400 都压成 RuntimeError 文本；
   无效 API key 等确定性错误造成约 34s 无效等待与 10 次无效请求，重试遥测失真。
2. **Retry-After / RateLimitError 死路径，429 语义未兑现（S3，retry.py:51,227-232）**——
   `RateLimitError` 定义了 `retry_after` 却全仓无人构造，loop 注释承诺的
   "honor Retry-After" 从未生效；限流场景退避完全依赖固定序列，且 `_delay_for_error`
   对字符串/超大 retry_after 无容错，是文档与实现断裂的典型。
3. **`load_jsonc` 尾逗号正则静默破坏字符串字面量（S3，profiles.py:63）**——配置解析对
   ",}" / ",]" 序列无字符串感知，配置内容可能被悄悄改写；当前内置 profile 未触发，
   属潜伏的配置损坏缺陷，与 strip_jsonc 的严谨状态机形成鲜明反差。

## 4. 亮点

- **usage 归一化的供应商形状覆盖完整且有测试保障**：`normalize_usage` 处理
  OpenAI 嵌套 `prompt_tokens_details.cached_tokens`、Anthropic `cache_read/creation_input_tokens`、
  DeepSeek/Moonshot `prompt_cache_hit_tokens`（顶层与嵌套）、opencode `tokens.cache.read/write`
  （helpers.py:105-215），tests/test_llm_helpers.py 有全套 round-trip 测试，
  `LLMUsage.__post_init__` 自动补 total_tokens 保证消费端不缺失。
- **profile 版流式归一化的"delta 先于 finish_reason"处理**（profiles.py:362-367）：
  针对"供应商在带 finish_reason 的最终 chunk 里补发最后一段 tool_call arguments"的
  真实截断问题做了明确修复并注释了动机，是经验沉淀的典范。
- **`stream_with_retry` 的 `emitted` 守卫**（retry.py:127-158）：一旦流已产出事件即停止
  重试、向上抛错——避免"流中途断开重放"造成的工具调用重复执行风险；同时
  `token_overflow`/`fatal` 不重试，防重试风暴。
- **空闲超时的分层设计**：kernel 在 `_next_stream_event`（loop.py:1811-1815）按单事件
  粒度实现空闲超时，与传输层重试解耦，且重试只覆盖 stream setup 阶段（loop.py:1522-1526
  注释准确描述了该语义）。
- **shallow thinking 拆分器的分块健壮性**：`_trailing_marker_prefix_len`（shallow_thinking.py:274-279）
  处理标记跨 chunk 的半包情况，`finish()`（225-236）对未闭合块完整还原标记文本，
  tests/test_shallow_thinking.py 覆盖了半包、缺失、前置文本等场景。
- **usage-only chunk 的处理注释**（helpers.py:448-454、loop.py:1544-1546）：明确
  DeepSeek/Moonshot 把 usage 折进最终 chunk 的行为，避免"usage 事件吞掉 done 事件"
  的经典坑，UI 缓存命中率统计链路完整（pending_usage → done → runtime.reply_delta）。

## 5. 审计范围与方法

- **范围**：`core/src/lamtools_core/llm/` 全部文件；交叉核对的消费/参考代码：
  `cli.py`（CoreHttpLLMClient，LLMConfig）、`kernel/loop.py`（_stream_model/_call_model/
  _next_stream_event/usage 事件）、`kernel/policy.py`、`kernel/errors.py`、
  `config/retry_store.py`、`core/config/llm_adapters/*.jsonc`、
  `core/.lam/core/config/model_retry.jsonc`、`AGENTS.md` 第 46-47 行语义、
  `core/tests/test_llm_helpers.py`、`core/tests/test_shallow_thinking.py`。
- **方法**：全文件通读 → 数据流/调用链追踪（grep 符号引用与装配点）→ 语义对照
  （jsonc 文档注释 vs 实现）→ 关键行为用只读 python stdin 片段实测复现（JSONC 尾逗号
  字符串破坏、dict arguments 崩溃、content+finish_reason 吞 done、usage 归一化形状）。
- **纪律**：全程只读，未修改/创建/删除任何代码文件，未运行 pytest，未启动服务，
  未发起任何 LLM 网络调用。
- **计数**：S1×0、S2×1、S3×8、S4×8，共 17 条（含 2 条实测复现）。

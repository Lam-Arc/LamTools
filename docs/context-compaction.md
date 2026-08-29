# Core 上下文压缩

Core 的上下文压缩只替换发给模型的派生上下文，不把摘要写入原始会话历史。调用链固定为：

```text
CoreLoopKernel
  -> ContextCompactionController
  -> CompactionPlanner
  -> summarize_context_messages
  -> CompactionFitter
  -> ContextCompactionResult
```

## 职责边界

- `ContextCompactionController` 负责完整请求的触发测量、摘要模型切换 fallback，以及调用通用压缩 facade。
- `CompactionPlanner` 只划分 leading system prefix、待摘要历史和 recent tail，不调用 LLM，也不写运行时状态。
- `summarizer.py` 只负责分段、摘要、合并和 streaming/fallback。
- `CompactionFitter` 只负责用 exact estimator 把 summary + recent tail 塞进目标预算；缩减顺序有界，最多 `MAX_FIT_ATTEMPTS` 次。
- Kernel 只维护 request metadata、runtime metrics、`summary_seq`/`lam_compaction_resume` 和 checkpoint。

## Token 预算

业务层把窗口策略解析为绝对 token 数：

- `context_window_tokens`：模型上下文窗口。
- `compact_trigger_tokens` 或 `compact_trigger_ratio`：触发阈值。
- `compact_limit_tokens` 或 `compact_limit_ratio`：压缩后的硬上限。

触发检查先用 fast estimator。只有当 `fast_tokens * 8` 不低于阈值时才调用 exact estimator，因此中文、emoji 等 fast undercount 不会静默推迟压缩。成功的 fitter 结果必须满足：

```text
exact_tokens(result.messages) <= compact_limit_tokens
```

摘要请求另行预留输出、协议和 safety margin。`SummaryTokenBudget.max_input_tokens` 是摘要请求允许的输入上限，segment 和 merge 请求都必须遵守它。`LoopPolicy.compact_summary_output_tokens` 与 `LoopPolicy.compact_safety_margin_tokens` 可覆盖摘要输出上限和 safety margin；保持 `None` 时使用按窗口推导的默认值。

## 有界缩减策略

Fitter 按固定顺序尝试：原始 summary、压缩 summary 两次、删除最旧 recent turn 两次、token-aware 截断 summary、最小结构化摘要、只保留最新必需 turn。最新必需 turn 单独超过目标时抛出 `CompactionBudgetExceeded`，不会截断当前用户输入或无限重试。

文本截断按 `estimate_text_tokens` 二分，截断标记本身也计入预算；禁止使用字符数乘常数近似 token 数。

## 持久化与恢复

摘要保存在 `state.metadata["context_compaction"]`，其中包括 `summary`、`summary_seq`、计数和前后 token 数。原始 history 不插入 `context_compaction_summary` 行。第一条 retained message 携带 `lam_compaction_resume`，完整 history 重写后由 Kernel 重新锚定 `summary_seq`。

下一次运行加载：

```text
派生 summary + summary_seq 之后的原始 retained span + 新用户输入
```

若 boundary 漂移或历史被外部重建，Kernel 回退到完整 history，避免只剩 summary 的 ghost context。

## 观测字段

压缩事件和 runtime metrics 记录窗口、触发/目标 token、压缩前后 token、消息计数、segment 数、执行模型和策略。日志与事件不记录完整用户内容；UI 只消费 runtime part/event，CLI `/compact` 与自动压缩共用同一条核心 pipeline。

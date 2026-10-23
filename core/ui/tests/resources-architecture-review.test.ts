// user:“右侧的那个卡片实时显示的应该是 context window 的数值”+(卡片遵循当前快照的来源，不复用失效的历史读数)。
import { expect, it } from 'vitest'
import { buildCoreResourceSummary } from '../src/runtime/resources'

it('uses the latest estimate after a new context snapshot invalidates older usage', () => {
  const summary = buildCoreResourceSummary([
    { id: 'older', metadata: { contextMetrics: {
      model_id: 'previous-model', estimated_prompt_tokens: 5000,
      context_usage_prompt_tokens: 7000, context_window_tokens: 10000,
    } } },
    { id: 'newer', metadata: { contextMetrics: {
      model_id: 'current-model', estimated_prompt_tokens: 2000,
      context_window_tokens: 10000,
    } } },
  ], 10000)
  expect(summary?.currentPct).toBe(20)
})

it('shows provider usage when the next context snapshot arrives, allowing a one-request lag', () => {
  // user:“慢一拍的话是可接受的”+(允许卡片随下一次上下文快照更新，不要求响应一到就刷新)。
  const messages = [
    { id: 'latest', metadata: {
      contextMetrics: { estimated_prompt_tokens: 2000, context_window_tokens: 10000 } as Record<string, number>,
      usageMetrics: { prompt_tokens: 7000, llm_calls: 1, usage_available: true },
    } },
  ]
  messages[0].metadata.contextMetrics.context_usage_prompt_tokens = 7000
  expect(buildCoreResourceSummary(messages, 10000)?.currentPct).toBe(70)
})

it('displays the authoritative backend value without reselecting its source', () => {
  const summary = buildCoreResourceSummary([{ id: 'latest', metadata: { contextMetrics: {
    context_tokens: 2000, context_measurement_source: 'estimate',
    context_usage_prompt_tokens: 7000, context_window_tokens: 10000,
  } } }], 10000)
  expect(summary?.currentPct).toBe(20)
})

it('uses the newest context snapshot when an answer has multiple segments', () => {
  const summary = buildCoreResourceSummary([
    { id: 'a', metadata: { sourcePartId: 'same', contextMetrics: { context_tokens: 7000, context_window_tokens: 10000 } } },
    { id: 'b', metadata: { sourcePartId: 'same', contextMetrics: { context_tokens: 2000, context_window_tokens: 10000 } } },
  ], 10000)
  expect(summary?.currentPct).toBe(20)
})

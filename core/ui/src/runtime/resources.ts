import type { CoreMessage, MessagePart } from '../types'

export const CORE_CONTEXT_COMPACTION_TRIGGER_RATIO = 0.8

export interface CoreResourceSummary {
  currentPct: number
  thresholdPct: number
  contextLabel: string
  percentLabel: string
  statusLabel: string
  currentRatio: number
  thresholdRatio: number
  hasContext: boolean
  callItems: Array<{ label: string; value: string }>
}

export function buildCoreResourceSummary(
  messages: Array<Pick<CoreMessage, 'metadata'> & Partial<Pick<CoreMessage, 'parts'>>>,
  modelContextWindow?: number | null,
): CoreResourceSummary | null {
  const records = messages
    .map(message => message.metadata?.processMetrics)
    .filter((metrics): metrics is Record<string, unknown> => Boolean(metrics && typeof metrics === 'object'))
  let current = -1
  let max = firstNumber(modelContextWindow)
  let threshold = -1
  let contextCompacted = false
  for (const message of messages) {
    const metrics = message.metadata?.processMetrics
    if (metrics && typeof metrics === 'object') {
      const record = metrics as Record<string, unknown>
      current = latestNumber(current,
        record.estimated_prompt_tokens,
        record.estimatedPromptTokens,
        record.context_tokens,
        record.contextTokens,
      )
      max = latestNumber(max, record.context_window_tokens, record.contextWindowTokens)
      threshold = latestNumber(threshold,
        record.context_compaction_trigger_tokens,
        record.contextCompactionTriggerTokens,
        record.trigger_tokens,
        record.triggerTokens,
      )
      contextCompacted = record.context_compacted === true || record.contextCompacted === true
    }
    const compactedTokens = latestCompletedCompactionTokens(message.parts)
    if (compactedTokens >= 0) {
      current = compactedTokens
      contextCompacted = true
    }
  }
  if (records.length === 0 && current < 0) return null

  const hasContext = current >= 0 && max > 0
  const currentRatio = hasContext ? clampRatio(current / max) : 0
  const thresholdRatio = threshold > 0 && max > 0
    ? clampRatio(threshold / max)
    : CORE_CONTEXT_COMPACTION_TRIGGER_RATIO
  const currentPct = Math.round(currentRatio * 100)
  const thresholdPct = Math.round(thresholdRatio * 100)

  let calls = 0
  let inputTokens = 0
  let outputTokens = 0
  let cachedTokens = 0
  let hasCalls = false
  let hasInput = false
  let hasOutput = false
  let hasCache = false
  for (const metrics of records) {
    const callCount = firstNumber(metrics.llm_calls, metrics.llmCalls, metrics.model_calls, metrics.modelCalls)
    const input = firstNumber(metrics.input_tokens, metrics.inputTokens, metrics.prompt_tokens, metrics.promptTokens)
    const output = firstNumber(metrics.output_tokens, metrics.outputTokens, metrics.completion_tokens, metrics.completionTokens)
    const cached = firstNumber(metrics.cached_tokens, metrics.cachedTokens)
    if (callCount >= 0) { calls += callCount; hasCalls = true }
    if (input >= 0) { inputTokens += input; hasInput = true }
    if (output >= 0) { outputTokens += output; hasOutput = true }
    if (cached >= 0) { cachedTokens += cached; hasCache = true }
  }
  // Prefer the backend-computed rate when present; otherwise derive from totals.
  const directRate = latestNumber(-1,
    ...records.map(r => firstNumber(r.cache_hit_rate, r.cacheHitRate)))
  const cacheHitRate = directRate >= 0
    ? directRate
    : hasCache && inputTokens > 0
      ? cachedTokens / inputTokens
      : -1
  if (!hasContext && !hasCalls && !hasInput && !hasOutput) return null

  return {
    currentPct,
    thresholdPct,
    contextLabel: hasContext ? `${formatTokenCompact(current)} / ${formatTokenCompact(max)}` : '暂无上下文',
    percentLabel: hasContext ? `${currentPct}%` : '--',
    statusLabel: contextCompacted ? '已压缩' : (hasContext && currentPct >= thresholdPct ? '需压缩' : '正常'),
    currentRatio,
    thresholdRatio,
    hasContext,
    callItems: [
      { label: '调用', value: hasCalls ? String(calls) : '--' },
      { label: '输入', value: hasInput ? formatCompactNumber(inputTokens) : '--' },
      { label: '输出', value: hasOutput ? formatCompactNumber(outputTokens) : '--' },
      { label: '缓存', value: cacheHitRate >= 0 ? formatPercent(cacheHitRate) : '--' },
    ],
  }
}

function latestCompletedCompactionTokens(parts?: MessagePart[]): number {
  let tokens = -1
  for (const part of parts || []) {
    if (part.partType !== 'compaction' || part.status !== 'completed') continue
    const metadata = part.metadata
    if (!metadata || typeof metadata !== 'object') continue
    const status = String(metadata.compaction_status ?? metadata.compactionStatus ?? '')
    if (status !== 'compacted') continue
    tokens = latestNumber(tokens, metadata.after_tokens, metadata.afterTokens)
  }
  return tokens
}

function firstNumber(...values: unknown[]): number {
  for (const value of values) {
    const metric = Number(value)
    if (Number.isFinite(metric) && metric >= 0) return metric
  }
  return -1
}

function latestNumber(current: number, ...values: unknown[]): number {
  const next = firstNumber(...values)
  return next >= 0 ? next : current
}

function clampRatio(value: number): number {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0
}

function formatTokenCompact(tokens: number): string {
  const value = tokens / 1000
  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10
  return `${rounded}k`
}

function formatCompactNumber(value: number): string {
  if (value >= 1_000_000) return `${Math.round((value / 1_000_000) * 100) / 100}M`
  if (value >= 1_000) {
    const rounded = value >= 10_000 ? Math.round(value / 1_000) : Math.round((value / 1_000) * 10) / 10
    return `${rounded}k`
  }
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
}

function formatPercent(rate: number): string {
  const pct = Math.round(rate * 100)
  return `${pct}%`
}

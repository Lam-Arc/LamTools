import type { CoreMessage } from '../types'

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
  messages: Array<Pick<CoreMessage, 'metadata'>>,
  modelContextWindow?: number | null,
): CoreResourceSummary | null {
  const records = messages
    .map(message => message.metadata?.processMetrics)
    .filter((metrics): metrics is Record<string, unknown> => Boolean(metrics && typeof metrics === 'object'))
  if (records.length === 0) return null

  const latest = records[records.length - 1]
  const current = firstNumber(
    latest.estimated_prompt_tokens,
    latest.estimatedPromptTokens,
    latest.context_tokens,
    latest.contextTokens,
  )
  const max = firstNumber(
    latest.context_window_tokens,
    latest.contextWindowTokens,
    modelContextWindow,
  )
  const threshold = firstNumber(
    latest.context_compaction_trigger_tokens,
    latest.contextCompactionTriggerTokens,
    latest.trigger_tokens,
    latest.triggerTokens,
  )
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
  let hasCalls = false
  let hasInput = false
  let hasOutput = false
  for (const metrics of records) {
    const callCount = firstNumber(metrics.llm_calls, metrics.llmCalls, metrics.model_calls, metrics.modelCalls)
    const input = firstNumber(metrics.input_tokens, metrics.inputTokens, metrics.prompt_tokens, metrics.promptTokens)
    const output = firstNumber(metrics.output_tokens, metrics.outputTokens, metrics.completion_tokens, metrics.completionTokens)
    if (callCount >= 0) { calls += callCount; hasCalls = true }
    if (input >= 0) { inputTokens += input; hasInput = true }
    if (output >= 0) { outputTokens += output; hasOutput = true }
  }
  if (!hasContext && !hasCalls && !hasInput && !hasOutput) return null

  const contextCompacted = latest.context_compacted === true || latest.contextCompacted === true
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
    ],
  }
}

function firstNumber(...values: unknown[]): number {
  for (const value of values) {
    const metric = Number(value)
    if (Number.isFinite(metric) && metric >= 0) return metric
  }
  return -1
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

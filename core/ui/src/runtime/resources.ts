import type { CoreMessage, MessagePart } from '../types'
import { assistantSegmentTurnId } from '../appServer/selectors'

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
  usageStatusLabel: string
  callItems: Array<{ label: string; value: string }>
}

export function buildCoreResourceSummary(
  messages: Array<Pick<CoreMessage, 'metadata' | 'id'> & Partial<Pick<CoreMessage, 'parts'>>>,
  modelContextWindow?: number | null,
): CoreResourceSummary | null {
  // Context and provider usage are separate records. Both are attached to
  // every assistant segment, so dedupe by turn id before aggregating. The
  // processMetrics fallback keeps old snapshots readable.
  const contextRecords = collectMetricRecords(messages, 'contextMetrics')
  const providerRecords = collectMetricRecords(messages, 'usageMetrics')
  let current = -1
  let max = firstNumber(modelContextWindow)
  let threshold = -1
  let contextCompacted = false
  // The provider's own count for the last request it actually received.  The
  // local estimator only approximates it — measured on one live request:
  // 75,969 estimated vs 119,365 reported — so the provider number is preferred
  // whenever it is the newest thing we know.
  let providerPromptTokens = -1
  for (const record of contextRecords) {
    current = latestNumber(current,
      record.estimated_prompt_tokens,
      record.estimatedPromptTokens,
      record.context_tokens,
      record.contextTokens,
    )
    providerPromptTokens = latestNumber(providerPromptTokens,
      record.context_usage_prompt_tokens,
      record.contextUsagePromptTokens,
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
  // A completed compaction describes the request that follows it, so its number
  // may stand in for the live value only until the session moves on.  It used to
  // override the context size for the rest of the thread, which froze the
  // indicator at the post-compaction figure — a live session read 17k while the
  // real context had grown back past 119k.  Track where each record sits in the
  // transcript and let the newest one win.
  let lastMetricsIndex = -1
  let lastProviderIndex = -1
  let lastCompactionIndex = -1
  let lastCompactionTokens = -1
  messages.forEach((message, index) => {
    const metadata = message.metadata as Record<string, unknown> | undefined
    // Mirrors collectMetricRecords: the processMetrics alias only carries
    // provider usage when no dedicated contextMetrics field is present.
    if (metadata?.contextMetrics || metadata?.processMetrics) lastMetricsIndex = index
    if (metadata?.usageMetrics || (!metadata?.contextMetrics && metadata?.processMetrics)) {
      lastProviderIndex = index
    }
    const compactedTokens = latestCompletedCompactionTokens(message.parts)
    if (compactedTokens >= 0) {
      lastCompactionIndex = index
      lastCompactionTokens = compactedTokens
    }
  })
  let contextSource: 'estimate' | 'provider' | 'compacted' = 'estimate'
  if (lastCompactionTokens >= 0) {
    contextCompacted = true
    if (lastCompactionIndex >= Math.max(lastMetricsIndex, lastProviderIndex)) {
      current = lastCompactionTokens
      contextSource = 'compacted'
    }
  }
  if (contextSource !== 'compacted' && providerPromptTokens >= 0) {
    current = providerPromptTokens
    contextSource = 'provider'
  }

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
  let cacheReportedInputTokens = 0
  let hasCalls = false
  let hasInput = false
  let hasOutput = false
  let hasCache = false
  let hasProviderRecord = false
  let usageReported = false
  for (const metrics of providerRecords) {
    hasProviderRecord = true
    const callCount = firstNumber(metrics.llm_calls, metrics.llmCalls, metrics.model_calls, metrics.modelCalls)
    const input = firstNumber(metrics.input_tokens, metrics.inputTokens, metrics.prompt_tokens, metrics.promptTokens)
    const output = firstNumber(metrics.output_tokens, metrics.outputTokens, metrics.completion_tokens, metrics.completionTokens)
    const cached = cacheReadTokens(metrics)
    if (callCount >= 0) { calls += callCount; hasCalls = true }
    if (input >= 0) { inputTokens += input; hasInput = true }
    if (output >= 0) { outputTokens += output; hasOutput = true }
    if (cached >= 0) {
      cachedTokens += cached
      // A provider that omits its cache field has reported an unknown cache
      // result, not a cache miss. Keep its input out of this denominator.
      if (input >= 0) cacheReportedInputTokens += input
      hasCache = true
    }
    usageReported = usageReported
      || metrics.usage_available === true
      || input >= 0
      || output >= 0
      || firstNumber(metrics.total_tokens, metrics.totalTokens) >= 0
  }
  // Aggregate only calls that explicitly reported cache data. An omitted
  // `cached_tokens` field means "unknown", not zero; including that call's
  // input in the denominator would turn a valid 92.8% hit rate into a false
  // 46% rate when one of two calls did not expose cache metrics.
  const directRate = firstNumber(...providerRecords.map(r => firstNumber(r.cache_hit_rate, r.cacheHitRate)))
  const cacheHitRate = hasCache && cacheReportedInputTokens > 0
    ? cachedTokens / cacheReportedInputTokens
    : directRate >= 0
      ? directRate
      : -1
  const hasProviderUsage = hasProviderRecord && (hasCalls || hasInput || hasOutput || hasCache || usageReported)
  if (!hasContext && !hasProviderUsage) return null

  // Say where the number comes from: the provider's count for the last request
  // it received, the local estimate, or the post-compaction figure.
  const contextSourceLabel = contextSource === 'provider'
    ? '实测'
    : contextSource === 'compacted'
      ? '压缩后'
      : '估算'

  return {
    currentPct,
    thresholdPct,
    contextLabel: hasContext
      ? `${formatTokenCompact(current)} / ${formatTokenCompact(max)} · ${contextSourceLabel}`
      : '暂无上下文',
    percentLabel: hasContext ? `${currentPct}%` : '--',
    statusLabel: contextCompacted ? '已压缩' : (hasContext && currentPct >= thresholdPct ? '需压缩' : '正常'),
    currentRatio,
    thresholdRatio,
    hasContext,
    usageStatusLabel: hasProviderRecord && usageReported ? '已获取' : '未获取',
    callItems: [
      { label: '调用', value: hasCalls ? String(calls) : '--' },
      { label: '输入', value: hasInput ? formatCompactNumber(inputTokens) : '--' },
      { label: '输出', value: hasOutput ? formatCompactNumber(outputTokens) : '--' },
      ...(cacheHitRate >= 0 ? [{ label: '缓存', value: formatPercent(cacheHitRate) }] : []),
    ],
  }
}

export interface CoreCacheTrendPoint {
  /** 累计模型调用次数（横坐标）。 */
  calls: number
  /** 该回合的缓存命中率，已收敛到 0..1（纵坐标）。 */
  rate: number
}

/**
 * 按时间顺序给出缓存命中率趋势：横坐标是累计调用次数，纵坐标是回合命中率。
 * 每个回合一个点；回合未上报缓存字段时只推进调用计数、不产出点——缺失的
 * 缓存字段是"未知"而不是"未命中"，与汇总命中率的口径一致。
 */
export function buildCacheTrend(
  messages: Array<Pick<CoreMessage, 'metadata' | 'id'>>,
): CoreCacheTrendPoint[] {
  const points: CoreCacheTrendPoint[] = []
  let calls = 0
  for (const record of collectMetricRecords(messages, 'usageMetrics')) {
    const reported = firstNumber(record.llm_calls, record.llmCalls, record.model_calls, record.modelCalls)
    // 缺失的调用数按后端默认的 1 次记（历史快照可能不带该字段）。
    const callCount = reported >= 0 ? reported : 1
    if (callCount > 0) calls += callCount
    const rate = recordCacheHitRate(record)
    if (callCount > 0 && rate >= 0) points.push({ calls, rate: clampRatio(rate) })
  }
  return points
}

function recordCacheHitRate(record: Record<string, unknown>): number {
  const direct = firstNumber(record.cache_hit_rate, record.cacheHitRate)
  if (direct >= 0) return direct
  const cached = cacheReadTokens(record)
  const input = firstNumber(record.input_tokens, record.inputTokens, record.prompt_tokens, record.promptTokens)
  return cached >= 0 && input > 0 ? cached / input : -1
}

function collectMetricRecords(
  messages: Array<Pick<CoreMessage, 'metadata' | 'id'>>,
  kind: 'contextMetrics' | 'usageMetrics',
): Array<Record<string, unknown>> {
  const records: Array<Record<string, unknown>> = []
  const countedTurns = new Set<string>()
  for (const message of messages) {
    const metadata = message.metadata
    const direct = metadata?.[kind]
    const legacy = metadata?.processMetrics
    const directRecord = direct && typeof direct === 'object' && !Array.isArray(direct)
      ? direct as Record<string, unknown>
      : null
    const legacyRecord = legacy && typeof legacy === 'object' && !Array.isArray(legacy)
      ? legacy as Record<string, unknown>
      : null
    // New snapshots deliberately keep the historical processMetrics alias
    // for context metrics. Do not interpret that alias as provider usage when
    // a dedicated contextMetrics field is present.
    const hasDedicatedContext = Boolean(
      metadata?.contextMetrics
      && typeof metadata.contextMetrics === 'object'
      && !Array.isArray(metadata.contextMetrics),
    )
    const metrics = directRecord
      ?? (kind === 'contextMetrics' || !hasDedicatedContext ? legacyRecord : null)
    if (!metrics) continue
    const turnId = typeof message.id === 'string' ? assistantSegmentTurnId(message.id) : ''
    if (turnId) {
      if (countedTurns.has(turnId)) continue
      countedTurns.add(turnId)
    }
    records.push(metrics)
  }
  return records
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

// Cache-read token count across provider shapes: OpenAI flattened
// `cached_tokens`, Anthropic `cache_read_input_tokens`, DeepSeek / Moonshot /
// opencode zen `prompt_cache_hit_tokens` (top level or nested inside
// `prompt_tokens_details` / `input_tokens_details`), plus camelCase aliases.
function cacheReadTokens(metrics: Record<string, unknown>): number {
  const nested = metrics.prompt_tokens_details && typeof metrics.prompt_tokens_details === 'object'
    && !Array.isArray(metrics.prompt_tokens_details)
    ? metrics.prompt_tokens_details as Record<string, unknown>
    : metrics.input_tokens_details && typeof metrics.input_tokens_details === 'object'
      && !Array.isArray(metrics.input_tokens_details)
      ? metrics.input_tokens_details as Record<string, unknown>
      : undefined
  if (nested) {
    const nestedCount = firstNumber(nested.cached_tokens, nested.prompt_cache_hit_tokens, nested.cache_read_input_tokens)
    if (nestedCount >= 0) return nestedCount
  }
  return firstNumber(
    metrics.cached_tokens,
    metrics.cachedTokens,
    metrics.prompt_cache_hit_tokens,
    metrics.cache_read_input_tokens,
    metrics.cache_read_tokens,
  )
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

export function formatPercent(rate: number): string {
  const pct = Math.round(rate * 1000) / 10
  return `${pct}%`
}

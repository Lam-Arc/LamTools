
import { t } from '../i18n/index'
import type { CoreMessage } from '../types'
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
  // The provider's own count for the last request it actually received.  The
  // local estimator only approximates it — measured on one live request:
  // 75,969 estimated vs 119,365 reported — so the provider number is preferred
  // whenever it is the newest thing we know.
  let providerPromptTokens = -1
  let authoritativeSource: 'estimate' | 'provider' | null = null
  // user:“右侧的那个卡片实时显示的应该是 context window 的数值”
  // +只消费后端最新占用快照，不从更旧的模型/压缩周期捞回已失效的 usage。
  for (const record of contextRecords.slice(-1)) {
    current = latestNumber(current,
      record.context_tokens,
      record.contextTokens,
      record.estimated_prompt_tokens,
      record.estimatedPromptTokens,
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
    if (firstNumber(record.context_tokens, record.contextTokens) >= 0) {
      authoritativeSource = record.context_measurement_source === 'usage' ? 'provider' : 'estimate'
    }
  }
  // user:“有真实 usage 时使用真实 usage，无真实 usage 使用兜底估算值”
  // +卡片和压缩触发使用同一个 context window 数值；压缩不是一次性状态，
  // 历史压缩记录不会覆盖当前值。
  let contextSource: 'estimate' | 'provider' = authoritativeSource ?? 'estimate'
  if (authoritativeSource === null && providerPromptTokens > 0) {
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
      if (input > 0) cachedTokens += Math.min(cached, input)
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
  const directRate = providerRecords.length === 1 ? firstNumber(providerRecords[0].cache_hit_rate, providerRecords[0].cacheHitRate) : -1
  const cacheHitRate = hasCache && cacheReportedInputTokens > 0
    ? cachedTokens / cacheReportedInputTokens
    : directRate >= 0
      ? directRate
      : -1
  const hasProviderUsage = hasProviderRecord && (hasCalls || hasInput || hasOutput || hasCache || usageReported)
  if (!hasContext && !hasProviderUsage) return null

  // Say where the number comes from: the provider's real usage, or the
  // fallback estimate.
  const contextSourceLabel = contextSource === 'provider' ? t("实测") : t("估算")

  return {
    currentPct,
    thresholdPct,
    contextLabel: hasContext
      ? `${formatTokenCompact(current)} / ${formatTokenCompact(max)} · ${contextSourceLabel}`
      : t("暂无上下文"),
    percentLabel: hasContext ? `${currentPct}%` : '--',
    statusLabel: hasContext && currentPct >= thresholdPct ? t("需压缩") : t("正常"),
    currentRatio,
    thresholdRatio,
    hasContext,
    usageStatusLabel: hasProviderRecord && usageReported ? t("已获取") : t("未获取"),
    callItems: [
      { get label() { return t("调用") }, value: hasCalls ? String(calls) : '--' },
      { get label() { return t("输入") }, value: hasInput ? formatCompactNumber(inputTokens) : '--' },
      { get label() { return t("输出") }, value: hasOutput ? formatCompactNumber(outputTokens) : '--' },
      ...(cacheHitRate >= 0 ? [{ get label() { return t("缓存") }, value: formatPercent(cacheHitRate) }] : []),
    ],
  }
}

export interface CoreCacheTrendPoint {
  /** 累计模型调用次数（横坐标）。 */
  calls: number
  /** 单次调用命中率 0..1；保留未知调用时用 -1 表示未上报。 */
  rate: number
}

/**
 * 按真实调用顺序取最近 200 次。默认只返回已知命中率；图表可保留未知调用
 * 的位置，避免挤掉它后横轴序号与柱形错位。旧快照只有回合汇总时不伪造单次值。
 */
export function buildCacheTrend(
  messages: Array<Pick<CoreMessage, 'metadata' | 'id'>>,
  includeUnknown = false,
): CoreCacheTrendPoint[] {
  const points: CoreCacheTrendPoint[] = []
  let calls = 0
  for (const record of collectMetricRecords(messages, 'usageMetrics')) {
    const reported = firstNumber(record.llm_calls, record.llmCalls, record.model_calls, record.modelCalls)
    // 缺失的调用数按后端默认的 1 次记（历史快照可能不带该字段）。
    const callCount = reported >= 0 ? reported : 1
    if (callCount > 0) calls += callCount
    const rate = recordCacheHitRate(record)
    if (callCount > 0 && (rate >= 0 || includeUnknown)) points.push({ calls, rate: rate >= 0 ? clampRatio(rate) : -1 })
  }
  return points.filter(point => point.calls > calls - 200)
}

function recordCacheHitRate(record: Record<string, unknown>): number {
  const cached = cacheReadTokens(record)
  const input = firstNumber(record.input_tokens, record.inputTokens, record.prompt_tokens, record.promptTokens)
  if (cached >= 0) return input > 0 ? cached / input : -1
  return firstNumber(record.cache_hit_rate, record.cacheHitRate)
}

function collectMetricRecords(
  messages: Array<Pick<CoreMessage, 'metadata' | 'id'>>,
  kind: 'contextMetrics' | 'usageMetrics',
): Array<Record<string, unknown>> {
  const records: Array<Record<string, unknown>> = []
  const countedTurns = new Set<string>()
  const contextTurnIndexes = new Map<string, number>()
  const countedCalls = new Set<string>()
  for (const message of messages) {
    const metadata = message.metadata
    if (kind === 'usageMetrics' && Array.isArray(metadata?.resourceCalls)) {
      for (const raw of [...metadata.resourceCalls].sort((a, b) => Number(a?.seq ?? 0) - Number(b?.seq ?? 0))) {
        if (!raw || typeof raw !== 'object') continue
        const call = raw as { id?: string; usage?: Record<string, unknown> }
        if (!call.id || !call.usage || countedCalls.has(call.id)) continue
        countedCalls.add(call.id)
        records.push({ llm_calls: 1, ...call.usage })
      }
      continue
    }
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
    const turnId = String(metadata?.sourcePartId || (typeof message.id === 'string' ? assistantSegmentTurnId(message.id) : ''))
    if (turnId) {
      // user:“右侧的那个卡片实时显示的应该是 context window 的数值”
      // +同一回复的后续片段携带更新快照时替换旧值，费用统计仍按调用去重。
      if (kind === 'contextMetrics') {
        const existingIndex = contextTurnIndexes.get(turnId)
        if (existingIndex !== undefined) { records[existingIndex] = metrics; continue }
        contextTurnIndexes.set(turnId, records.length)
      }
      if (countedTurns.has(turnId)) continue
      countedTurns.add(turnId)
    }
    records.push(metrics)
  }
  return records
}

function firstNumber(...values: unknown[]): number {
  for (const value of values) {
    if (value === null || value === undefined || value === '' || typeof value === 'boolean') continue
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

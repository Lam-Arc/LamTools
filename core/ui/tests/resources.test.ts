import { describe, expect, it } from 'vitest'

import { t } from '../src/i18n/index'
import { buildCoreResourceSummary } from '../src/runtime/resources'

const metadata = (estimated: number, usage = -1) => ({
  contextMetrics: {
    estimated_prompt_tokens: estimated,
    context_window_tokens: 10000,
    context_compaction_trigger_tokens: 8000,
    ...(usage >= 0 ? { context_usage_prompt_tokens: usage } : {}),
  },
})

const compactionPart = () => ({
  partType: 'compaction',
  status: 'completed',
  metadata: { compaction_status: 'compacted', after_tokens: 1000 },
})

describe('buildCoreResourceSummary context value', () => {
  it('prefers real usage over the fallback estimate', () => {
    const summary = buildCoreResourceSummary([
      { id: 'usage', metadata: metadata(5000, 7000) },
    ], 10000)

    expect(summary?.currentPct).toBe(70)
    expect(summary?.contextLabel).toContain(t('实测'))
  })

  it('falls back to the estimate when usage is absent', () => {
    const summary = buildCoreResourceSummary([
      { id: 'estimate', metadata: metadata(5000) },
    ], 10000)

    expect(summary?.currentPct).toBe(50)
    expect(summary?.contextLabel).toContain(t('估算'))
  })

  it('does not let a historical compaction part override the current value', () => {
    const summary = buildCoreResourceSummary([
      { id: 'old', metadata: metadata(1000), parts: [compactionPart()] },
      { id: 'new', metadata: metadata(5000) },
    ], 10000)

    expect(summary?.currentPct).toBe(50)
    expect(summary?.statusLabel).not.toBe(t('已压缩'))
  })

  it('does not freeze on a compaction part on the same message', () => {
    const summary = buildCoreResourceSummary([
      { id: 'same', metadata: metadata(5000), parts: [compactionPart()] },
    ], 10000)

    expect(summary?.currentPct).toBe(50)
    expect(summary?.statusLabel).not.toBe(t('已压缩'))
  })
})

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreResourceStats from '../src/components/CoreResourceStats.vue'
import { buildCacheTrend, buildCoreResourceSummary } from '../src/runtime/resources'
import type { CoreMessage, MessagePart } from '../src/types'

const messages = [{ id: 'msg-1', metadata: { processMetrics: {
  estimated_prompt_tokens: 25_000,
  context_window_tokens: 100_000,
  context_compaction_trigger_tokens: 80_000,
  llm_calls: 2,
  input_tokens: 12_000,
  output_tokens: 3_000,
} } }]

describe('CoreResourceStats', () => {
  it('renders shared panel statistics from Core message metrics', () => {
    const wrapper = mount(CoreResourceStats, { props: { messages } })
    expect(wrapper.text()).toContain('25k / 100k')
    expect(wrapper.text()).toContain('25%')
    expect(wrapper.text()).toContain('12k')
    expect(wrapper.find('[role="meter"]').attributes('aria-valuenow')).toBe('25')
  })

  it('renders the composer usage line without inventing missing usage', () => {
    const populated = mount(CoreResourceStats, { props: { messages, variant: 'composer' } })
    expect(populated.find('.core-resource-line').classes()).toContain('has-data')
    expect(populated.find('.core-resource-line').attributes('aria-valuenow')).toBe('25')

    const empty = mount(CoreResourceStats, { props: { messages: [], variant: 'composer' } })
    expect(empty.find('.core-resource-line').classes()).not.toContain('has-data')
    expect(empty.find('.core-resource-line').attributes('aria-valuenow')).toBe('0')
  })

  it('uses a completed compaction result as the current context size', () => {
    const compactedMessages: Array<Pick<CoreMessage, 'id' | 'metadata'> & Partial<Pick<CoreMessage, 'parts'>>> = [
      ...messages,
      {
        id: 'msg-2',
        metadata: {},
        parts: [{
          id: 'compaction-1',
          partType: 'compaction',
          status: 'completed',
          metadata: {
            compaction_status: 'compacted',
            after_tokens: 2_067,
          },
        }],
      },
    ]

    const wrapper = mount(CoreResourceStats, { props: { messages: compactedMessages } })

    expect(wrapper.text()).toContain('2.1k / 100k')
    expect(wrapper.text()).toContain('2%')
    expect(wrapper.text()).toContain('已压缩')
  })

  it('renders cache hit rate from backend cache_hit_rate when present', () => {
    const cachedMessages = [{ id: 'msg-cached-1', metadata: { processMetrics: {
      llm_calls: 1,
      input_tokens: 10_000,
      output_tokens: 500,
      cached_tokens: 9_900,
      cache_hit_rate: 0.99,
    } } }]
    const wrapper = mount(CoreResourceStats, { props: { messages: cachedMessages } })
    expect(wrapper.text()).toContain('99%')
  })

  it('derives cache hit rate from cached_tokens / input_tokens when rate is absent', () => {
    const cachedMessages = [{ id: 'msg-cached-2', metadata: { processMetrics: {
      llm_calls: 1,
      input_tokens: 10_000,
      output_tokens: 500,
      cached_tokens: 8_000,
    } } }]
    const wrapper = mount(CoreResourceStats, { props: { messages: cachedMessages } })
    expect(wrapper.text()).toContain('80%')
  })

  it('hides cache hit rate when no cache data is present', () => {
    const wrapper = mount(CoreResourceStats, { props: { messages } })
    const stats = wrapper.findAll('.core-resource-stats > div')
    expect(stats.length).toBe(3)
    expect(wrapper.text()).not.toContain('缓存')
  })

  it('excludes cache-unreported calls from the cache-rate denominator', () => {
    const mixedCacheReporting = [
      { id: 'assistant:thread-1:turn:1', metadata: { processMetrics: { llm_calls: 1, input_tokens: 9_383, cached_tokens: 8_704 } } },
      { id: 'assistant:thread-1:turn:2', metadata: { processMetrics: { llm_calls: 1, input_tokens: 9_404 } } },
    ]
    const summary = buildCoreResourceSummary(mixedCacheReporting)
    expect(summary!.callItems).toContainEqual({ label: '缓存', value: '92.8%' })
  })

  it('counts one turn usage once across its assistant segments', () => {
    // Mid-turn user messages split a turn into several assistant segments
    // that share the SAME processMetrics object — summing per message would
    // double-count one turn's tokens / calls.
    const turnUsage = {
      llm_calls: 1,
      input_tokens: 10_000,
      output_tokens: 500,
      cached_tokens: 8_000,
    }
    const multi = [
      { id: 'assistant:thread-1:turn:1', metadata: { processMetrics: turnUsage } },
      { id: 'assistant:thread-1:turn:1#2', metadata: { processMetrics: turnUsage } },
    ]
    const summary = buildCoreResourceSummary(multi)
    expect(summary).not.toBeNull()
    expect(summary!.callItems[1].value).toBe('10k') // input counted once, not 20k
    expect(summary!.callItems[0].value).toBe('1')
    expect(summary!.callItems[3].value).toBe('80%')
  })

  it('sums usage across distinct turns', () => {
    const messages = [
      { id: 'assistant:thread-1:turn:1', metadata: { processMetrics: { llm_calls: 1, input_tokens: 10_000, output_tokens: 500 } } },
      { id: 'assistant:thread-1:turn:2', metadata: { processMetrics: { llm_calls: 2, input_tokens: 5_000, output_tokens: 250 } } },
    ]
    const summary = buildCoreResourceSummary(messages)
    expect(summary).not.toBeNull()
    expect(summary!.callItems[1].value).toBe('15k')
    expect(summary!.callItems[0].value).toBe('3')
  })

  it('reads DeepSeek prompt_cache_hit_tokens and nested details shapes', () => {
    // DeepSeek reports cache reads as top-level prompt_cache_hit_tokens;
    // OpenAI-compatible gateways may fold them into prompt_tokens_details.
    const cachedMessages = [
      { id: 'assistant:thread-1:turn:1', metadata: { processMetrics: { llm_calls: 1, input_tokens: 1_000, output_tokens: 50, prompt_cache_hit_tokens: 700 } } },
      { id: 'assistant:thread-1:turn:2', metadata: { processMetrics: { llm_calls: 1, input_tokens: 1_000, output_tokens: 50, prompt_tokens_details: { cached_tokens: 300 } } } },
    ]
    const wrapper = mount(CoreResourceStats, { props: { messages: cachedMessages } })
    expect(wrapper.text()).toContain('50%') // (700 + 300) / 2000
  })

  it('keeps context estimates separate from missing provider usage', () => {
    const separated = [{
      id: 'assistant:thread-1:turn:separated',
      metadata: {
        contextMetrics: {
          estimated_prompt_tokens: 6_925,
          context_window_tokens: 50_000,
        },
        usageMetrics: {
          llm_calls: 1,
          usage_available: false,
          usage_status: 'missing',
          usage_source: 'provider',
        },
      },
    }]

    const wrapper = mount(CoreResourceStats, { props: { messages: separated } })

    expect(wrapper.text()).toContain('6.9k / 50k')
    expect(wrapper.text()).toContain('Provider Usage')
    expect(wrapper.text()).toContain('未获取')
    expect(wrapper.findAll('.core-resource-stats > div')[1].text()).toContain('--')
    expect(wrapper.findAll('.core-resource-stats > div')[2].text()).toContain('--')
  })

  it('does not treat the new processMetrics context alias as provider usage', () => {
    const contextOnly = {
      estimated_prompt_tokens: 6_925,
      context_window_tokens: 50_000,
    }
    const summary = buildCoreResourceSummary([{
      id: 'assistant:thread-1:turn:context-only',
      metadata: { contextMetrics: contextOnly, processMetrics: contextOnly },
    }])

    expect(summary).not.toBeNull()
    expect(summary!.usageStatusLabel).toBe('未获取')
    expect(summary!.callItems.map(item => item.value)).toEqual(['--', '--', '--'])
  })

  it('renders the cache trend chart only when cache data exists', () => {
    const withCache = mount(CoreResourceStats, { props: { messages: cachedSingleTurn() } })
    expect(withCache.find('.core-resource-cache-plot').exists()).toBe(true)
    expect(withCache.text()).toContain('缓存命中率')

    const withoutCache = mount(CoreResourceStats, { props: { messages } })
    expect(withoutCache.find('.core-resource-cache-plot').exists()).toBe(false)
    expect(withoutCache.text()).not.toContain('缓存命中率')
  })

  it('draws the trend line from the second cache-reporting turn on', () => {
    const single = mount(CoreResourceStats, { props: { messages: cachedSingleTurn() } })
    expect(single.find('.core-resource-cache-line').exists()).toBe(false)
    // 单样本也必须有可读主体：末端数据点锚在绘图区右端、25% 命中率对应的高度。
    const dot = single.get('.core-resource-cache-dot')
    const dotStyle = dot.attributes('style') || ''
    expect(Number.parseFloat(/left: ([\d.]+)%/.exec(dotStyle)![1])).toBeCloseTo(97, 0)
    expect(Number.parseFloat(/top: ([\d.]+)%/.exec(dotStyle)![1])).toBeCloseTo(70.455, 1)

    const multi = mount(CoreResourceStats, { props: { messages: [
      { id: 'assistant:thread-1:turn:1', metadata: { usageMetrics: { llm_calls: 1, input_tokens: 1_000, cached_tokens: 250 } } },
      { id: 'assistant:thread-1:turn:2', metadata: { usageMetrics: { llm_calls: 1, cache_hit_rate: 0.9 } } },
    ] } })
    expect(multi.find('.core-resource-cache-line').exists()).toBe(true)
    expect(multi.find('.core-resource-cache-dot').exists()).toBe(true)
    expect(multi.text()).toContain('90%')
  })

  it('pins both y-axis labels to the exact gridline heights', () => {
    const wrapper = mount(CoreResourceStats, { props: { messages: cachedSingleTurn() } })
    const maxTop = Number.parseFloat(/top: ([\d.]+)%/.exec(wrapper.get('.core-resource-cache-scale-max').attributes('style') || '')![1])
    const minTop = Number.parseFloat(/top: ([\d.]+)%/.exec(wrapper.get('.core-resource-cache-scale-min').attributes('style') || '')![1])
    expect(maxTop).toBeCloseTo(9.091, 2)
    expect(minTop).toBeCloseTo(90.909, 2)
  })

  it('keeps the chart responsive with a proportional clamped height', () => {
    const source = readFileSync(resolve(import.meta.dirname, '../src/components/CoreResourceStats.vue'), 'utf8')
    expect(source).toMatch(/\.core-resource-cache-figure\s*\{[^}]*aspect-ratio: 6 \/ 1;/)
    expect(source).toMatch(/\.core-resource-cache-figure\s*\{[^}]*min-height: 32px;[^}]*max-height: 72px;/)
  })
})

function cachedSingleTurn() {
  return [{ id: 'assistant:thread-1:turn:cached', metadata: { usageMetrics: { llm_calls: 1, input_tokens: 1_000, cached_tokens: 250 } } }]
}

/** 后端投影的压缩段 part（context size source 用例共用同一个形状）。 */
function compactionPart(): MessagePart {
  return {
    id: 'compaction-1',
    partType: 'compaction',
    status: 'completed',
    metadata: { compaction_status: 'compacted', after_tokens: 2_067 },
  }
}

describe('buildCacheTrend', () => {
  it('builds one point per cache-reporting turn over cumulative calls', () => {
    const messages = [
      { id: 'assistant:thread-1:turn:1', metadata: { usageMetrics: { llm_calls: 1, input_tokens: 1_000, cached_tokens: 700 } } },
      { id: 'assistant:thread-1:turn:2', metadata: { usageMetrics: { llm_calls: 2, cache_hit_rate: 0.5 } } },
      // 无缓存字段的回合：调用计数照常推进，但不产出点。
      { id: 'assistant:thread-1:turn:3', metadata: { usageMetrics: { llm_calls: 1, input_tokens: 2_000 } } },
    ]
    expect(buildCacheTrend(messages)).toEqual([
      { calls: 1, rate: 0.7 },
      { calls: 3, rate: 0.5 },
    ])
  })

  it('returns an empty trend when no turn reports cache data', () => {
    expect(buildCacheTrend([{ id: 'assistant:thread-1:turn:1', metadata: { usageMetrics: { llm_calls: 1 } } }])).toEqual([])
  })

  it('defaults a missing call count to one call like the backend does', () => {
    expect(buildCacheTrend([{ id: 'assistant:thread-1:turn:1', metadata: { usageMetrics: { input_tokens: 1_000, cached_tokens: 400 } } }]))
      .toEqual([{ calls: 1, rate: 0.4 }])
  })
})

describe('context size source', () => {
  const baseMetrics = {
    estimated_prompt_tokens: 25_000,
    context_window_tokens: 100_000,
    context_compaction_trigger_tokens: 80_000,
  }

  it('stops showing the compaction result once a later turn arrives', () => {
    const messagesWithLaterTurn = [
      { id: 'msg-1', metadata: { contextMetrics: { ...baseMetrics } } },
      {
        id: 'msg-2',
        metadata: {},
        parts: [compactionPart()],
      },
      // The next turn measures the real request again — the compaction figure
      // describes a request that is no longer the current one.
      { id: 'msg-3', metadata: { contextMetrics: { ...baseMetrics, estimated_prompt_tokens: 40_000 } } },
    ]

    const summary = buildCoreResourceSummary(messagesWithLaterTurn)

    expect(summary?.contextLabel).toContain('40k / 100k')
    expect(summary?.contextLabel).toContain('估算')
    // The thread did compact, so the badge stays.
    expect(summary?.statusLabel).toBe('已压缩')
  })

  it('prefers the provider count over the local estimate and says so', () => {
    const messagesWithProviderCount = [{
      id: 'msg-1',
      metadata: {
        contextMetrics: { ...baseMetrics, context_usage_prompt_tokens: 119_365 },
      },
    }]

    const summary = buildCoreResourceSummary(messagesWithProviderCount)

    expect(summary?.contextLabel).toContain('119k / 100k')
    expect(summary?.contextLabel).toContain('实测')
  })

  it('keeps the compaction figure while it is the newest thing known', () => {
    const messagesCompactedLast = [
      { id: 'msg-1', metadata: { contextMetrics: { ...baseMetrics } } },
      {
        id: 'msg-2',
        metadata: {},
        parts: [compactionPart()],
      },
    ]

    const summary = buildCoreResourceSummary(messagesCompactedLast)

    expect(summary?.contextLabel).toContain('2.1k / 100k')
    expect(summary?.contextLabel).toContain('压缩后')
  })
})

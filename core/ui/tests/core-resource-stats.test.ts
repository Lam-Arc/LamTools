import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreResourceStats from '../src/components/CoreResourceStats.vue'
import { buildCacheTrend, buildCoreResourceSummary } from '../src/runtime/resources'
import { selectCoreWorkbenchMessages, type CoreAppSnapshot } from '../src/appServer'
import { selectCoreSubAgentRuns } from '../src/agents/subAgentProjection'
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

  it('renders the cache chart with reported usage and keeps missing cache unknown', () => {
    const withCache = mount(CoreResourceStats, { props: { messages: cachedSingleTurn() } })
    expect(withCache.find('.core-resource-cache-plot').exists()).toBe(true)
    expect(withCache.text()).toContain('Provider Usage')
    expect(withCache.text()).toContain('缓存')
    expect(withCache.text()).toContain('25%')
    expect(withCache.text()).toContain('缓存命中率')

    const withoutCache = mount(CoreResourceStats, { props: { messages } })
    expect(withoutCache.find('.core-resource-cache-plot').exists()).toBe(false)
    expect(withoutCache.text()).not.toContain('缓存命中率')
  })

  it('renders an adaptive single bar with axes and scale labels', () => {
    const wrapper = mount(CoreResourceStats, { props: { messages: cachedSingleTurn() } })
    expect(wrapper.findAll('.core-resource-cache-bar')).toHaveLength(1)
    expect(Number(wrapper.get('.core-resource-cache-bar').attributes('width'))).toBeGreaterThan(60)
    expect(wrapper.find('.core-resource-cache-axis').exists()).toBe(true)
    expect(wrapper.find('.core-resource-cache-scale').exists()).toBe(true)
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

describe('individual resource calls', () => {
  it('limits history to 200 calls without limiting the total and deduplicates segments', () => {
    const resourceCalls = Array.from({ length: 201 }, (_, i) => ({ id: `call-${i}`, seq: i, usage: { llm_calls: 1, input_tokens: 100, cached_tokens: i % 2 ? 100 : 0 } }))
    const messages = [1, 2].map(i => ({ id: `assistant:turn#${i}`, metadata: { resourceCalls } }))
    expect(buildCacheTrend(messages)).toHaveLength(200)
    expect(buildCacheTrend(messages)[0].calls).toBe(2)
    expect(buildCacheTrend(messages)[199].calls).toBe(201)
    expect(buildCoreResourceSummary(messages)?.callItems[0].value).toBe('201')
    expect(buildCoreResourceSummary(messages)?.callItems).toContainEqual({ label: '缓存', value: '49.8%' })
  })
  it('weights cache by tokens and ignores contradictory direct percentages', () => {
    const messages = [{ id: 'a', metadata: { resourceCalls: [
      { id: 'a', usage: { input_tokens: 100, cached_tokens: 100, cache_hit_rate: 0 } },
      { id: 'b', usage: { input_tokens: 900, cached_tokens: 0, cache_hit_rate: 1 } },
    ] } }]
    expect(buildCoreResourceSummary(messages)?.callItems).toContainEqual({ label: '缓存', value: '10%' })
    expect(buildCacheTrend(messages).map(point => point.rate)).toEqual([1, 0])
  })
  it('does not invent a cache percentage for zero input', () => {
    expect(buildCacheTrend([{ id: 'a', metadata: { usageMetrics: { input_tokens: 0, cached_tokens: 0 } } }])).toEqual([])
  })
})

it('projects main and child resources independently from the same snapshot', () => {
  const snapshot: CoreAppSnapshot = {
    thread_id: 't', snapshot_seq: 4, status: 'completed', turns: {}, items: {}, item_order: [],
    core: { thread_id: 't', snapshot_seq: 4, status: 'completed', item_order: ['delegate', 'child-text'], items: {
      delegate: { item_id: 'delegate', turn_id: 'turn', kind: 'tool_call', status: 'completed', content: '', payload: { type: 'dynamicToolCall', tool_name: 'sub_agent', arguments: { name: 'child', prompt: 'task' }, metadata: { sub_session_id: 'child-session', name: 'child' } } },
      'child-text': { item_id: 'child-text', parent_item_id: 'delegate', turn_id: 'turn', kind: 'message', status: 'completed', content: 'child answer', payload: { type: 'agentMessage' } },
    }, turns: { turn: { turn_id: 'turn', status: 'completed', usage: { llm_calls: 1, input_tokens: 100, cached_tokens: 80 },
      usage_calls: [
        { id: 'main', seq: 1, usage: { llm_calls: 1, input_tokens: 100, cached_tokens: 80 } },
        { id: 'child', seq: 2, parent_item_id: 'delegate', usage: { llm_calls: 1, input_tokens: 900, cached_tokens: 0 } },
      ], child_context_metrics: { delegate: { estimated_prompt_tokens: 3000, context_window_tokens: 10000 } },
    } } },
  }
  const messages = selectCoreWorkbenchMessages(snapshot)
  expect(buildCoreResourceSummary(messages)?.callItems).toContainEqual({ label: '输入', value: '100' })
  const runs = selectCoreSubAgentRuns(messages)
  expect(runs).toHaveLength(1)
  expect(buildCoreResourceSummary(runs[0].timeline)?.contextLabel).toContain('3k / 10k')
  expect(buildCoreResourceSummary(runs[0].timeline)?.callItems).toContainEqual({ label: '输入', value: '900' })
})

it('keeps unknown cache calls in their real slots and labels the last-call rate', () => {
  const messages = [{ id: 'assistant:cache-slots', metadata: { resourceCalls: [
    { id: 'one', seq: 1, usage: { llm_calls: 1, input_tokens: 100 } },
    { id: 'two', seq: 2, usage: { llm_calls: 1, input_tokens: 100, cached_tokens: 0 } },
    { id: 'three', seq: 3, usage: { llm_calls: 1, input_tokens: 100, cached_tokens: 90 } },
    { id: 'four', seq: 4, usage: { llm_calls: 1, input_tokens: 100 } },
  ] } }]
  expect(buildCacheTrend(messages, true)).toEqual([
    { calls: 1, rate: -1 }, { calls: 2, rate: 0 }, { calls: 3, rate: 0.9 }, { calls: 4, rate: -1 },
  ])
  const wrapper = mount(CoreResourceStats, { props: { messages } })
  expect(wrapper.find('.core-resource-cache-plot').exists()).toBe(true)
  const bars = wrapper.findAll('.core-resource-cache-bar')
  expect(bars).toHaveLength(4)
  expect(bars[0].classes()).toContain('core-resource-cache-bar--unknown')
  expect(bars[1].classes()).not.toContain('core-resource-cache-bar--unknown')
  expect(Number(bars[2].attributes('x')) - Number(bars[1].attributes('x')))
    .toBeCloseTo(Number(bars[1].attributes('x')) - Number(bars[0].attributes('x')))
  expect(wrapper.text()).toContain('最近一次 未上报')
  expect(wrapper.text()).toContain('灰线：未上报缓存')
  expect(wrapper.get('.core-resource-cache-axis').text()).toContain('1 次调用')
  expect(buildCoreResourceSummary(messages)?.callItems).toContainEqual({ label: '缓存', value: '45%' })
})

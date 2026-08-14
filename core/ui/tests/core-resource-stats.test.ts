import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreResourceStats from '../src/components/CoreResourceStats.vue'
import { buildCoreResourceSummary } from '../src/runtime/resources'
import type { CoreMessage } from '../src/types'

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

  it('shows -- for cache hit rate when no cache data is present', () => {
    const wrapper = mount(CoreResourceStats, { props: { messages } })
    const stats = wrapper.findAll('.core-resource-stats > div')
    expect(stats.length).toBe(4)
    expect(stats[3].text()).toContain('缓存')
    expect(stats[3].text()).toContain('--')
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
})

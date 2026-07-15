import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreResourceStats from '../src/components/CoreResourceStats.vue'

const messages = [{ metadata: { processMetrics: {
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
})

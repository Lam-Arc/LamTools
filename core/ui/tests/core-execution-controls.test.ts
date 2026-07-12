import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreExecutionControls from '../src/components/CoreExecutionControls.vue'

describe('CoreExecutionControls', () => {
  it('uses the shared upward-opening selectors for model and thinking controls', async () => {
    const wrapper = mount(CoreExecutionControls, {
      props: {
        modelValue: 'model-1',
        thinkingMode: 'medium',
        shallowThinkingEnabled: false,
        modelOptions: [
          { value: 'model-1', label: 'Kimi K2.6' },
          { value: 'model-2', label: 'GLM-5.2' },
        ],
        thinkingModeOptions: [
          { value: 'medium', label: 'Medium thinking' },
          { value: 'none', label: 'No thinking' },
        ],
      },
    })

    expect(wrapper.findAll('select')).toHaveLength(0)
    expect(wrapper.findAll('.ui-select--up')).toHaveLength(2)
    expect(wrapper.text()).toContain('Kimi K2.6')
    expect(wrapper.text()).toContain('Medium thinking')

    const triggers = wrapper.findAll('.ui-select-trigger')
    await triggers[0].trigger('click')
    const options = wrapper.findAll('.ui-select-option')
    await options[1].trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['model-2']])
  })
})

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreExecutionControls from '../src/components/CoreExecutionControls.vue'

describe('CoreExecutionControls', () => {
  it('groups shallow thinking into the compact thinking selector without changing the thinking level', async () => {
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
    expect(wrapper.find('.composer-shallow-toggle').exists()).toBe(false)
    expect(wrapper.findAll('.ui-select-arrow')).toHaveLength(0)

    const triggers = wrapper.findAll('.ui-select-trigger')
    await triggers[0].trigger('click')
    const options = wrapper.findAll('.ui-select-option')
    await options[1].trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['model-2']])

    await triggers[1].trigger('click')
    const thinkingOptions = wrapper.findAll('.ui-select-option')
    const shallowOption = thinkingOptions.find((option) => option.text() === 'Shallow')
    expect(shallowOption).toBeTruthy()
    expect(shallowOption!.classes()).toContain('separator-before')
    expect(shallowOption!.classes()).toContain('active-accent')
    await shallowOption!.trigger('click')

    expect(wrapper.emitted('update:shallowThinkingEnabled')).toEqual([[true]])
    expect(wrapper.emitted('update:thinkingMode')).toBeUndefined()

    await wrapper.setProps({ shallowThinkingEnabled: true })
    await triggers[1].trigger('click')
    const enabledShallowOption = wrapper.findAll('.ui-select-option').find((option) => option.text() === 'Shallow')
    expect(enabledShallowOption!.classes()).toContain('active')
    expect(enabledShallowOption!.classes()).toContain('active-accent')
  })
})

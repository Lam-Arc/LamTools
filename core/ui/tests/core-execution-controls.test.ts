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
    expect(wrapper.findAll('[data-core-runtime-menu], [data-core-model-thinking-menu]')).toHaveLength(2)
    expect(wrapper.text()).toContain('Kimi K2.6')
    expect(wrapper.text()).toContain('Medium thinking')
    expect(wrapper.find('.core-runtime-menu').exists()).toBe(true)
    expect(wrapper.find('.core-model-thinking-menu').exists()).toBe(true)

    const modelThinkingTrigger = wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger')
    await modelThinkingTrigger.trigger('click')
    const options = wrapper.findAll('[data-model-thinking-model-option]')
    await options[1].trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['model-2']])

    await wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger').trigger('click')
    const shallowOption = wrapper.get('[data-model-thinking-shallow-option]')
    expect(shallowOption).toBeTruthy()
    expect(shallowOption.classes()).toContain('core-model-thinking-menu__shallow')
    await shallowOption.trigger('click')

    expect(wrapper.emitted('update:shallowThinkingEnabled')).toEqual([[true]])
    expect(wrapper.emitted('update:thinkingMode')).toBeUndefined()

    await wrapper.setProps({ shallowThinkingEnabled: true })
    await wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger').trigger('click')
    const enabledShallowOption = wrapper.get('[data-model-thinking-shallow-option]')
    expect(enabledShallowOption.classes()).toContain('active')
  })
})

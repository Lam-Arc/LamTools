import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreExecutionControls from '../src/components/CoreExecutionControls.vue'

describe('CoreExecutionControls', () => {
  it('groups shallow thinking into the compact thinking selector without changing the thinking level', async () => {
    const wrapper = mount(CoreExecutionControls, {
      props: {
        modelValue: 'model-1',
        thinkingMode: 'high',
        shallowThinkingEnabled: false,
        modelOptions: [
          { value: 'model-1', label: 'Kimi K2.6' },
          { value: 'model-2', label: 'GLM-5.2' },
        ],
        thinkingModeOptions: [
          { value: 'high', label: '高强度思考' },
          { value: 'off', label: '关闭思考' },
        ],
      },
    })

    expect(wrapper.findAll('select')).toHaveLength(0)
    expect(wrapper.findAll('[data-core-runtime-menu], [data-core-model-thinking-menu]')).toHaveLength(2)
    expect(wrapper.text()).toContain('Kimi K2.6')
    expect(wrapper.text()).toContain('高强度思考')
    expect(wrapper.find('.core-runtime-menu').exists()).toBe(true)
    expect(wrapper.find('.core-model-thinking-menu').exists()).toBe(true)

    const modelThinkingTrigger = wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger')
    await modelThinkingTrigger.trigger('click')
    expect(wrapper.findAll('[data-model-thinking-section]')).toHaveLength(2)
    expect(wrapper.find('[data-model-thinking-submenu]').exists()).toBe(false)
    await wrapper.get('[data-model-thinking-section="model"]').trigger('mouseenter')
    expect(wrapper.find('[data-model-thinking-submenu="model"]').exists()).toBe(true)
    const options = wrapper.findAll('[data-model-thinking-model-option]')
    await options[1].trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['model-2']])

    await wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger').trigger('click')
    await wrapper.get('[data-model-thinking-section="thinking"]').trigger('mouseenter')
    const shallowOption = wrapper.get('[data-model-thinking-shallow-option]')
    expect(shallowOption).toBeTruthy()
    expect(shallowOption.classes()).toContain('core-model-thinking-menu__shallow')
    await shallowOption.trigger('click')

    expect(wrapper.emitted('update:shallowThinkingEnabled')).toEqual([[true]])
    expect(wrapper.emitted('update:thinkingMode')).toBeUndefined()

    await wrapper.setProps({ shallowThinkingEnabled: true })
    await wrapper.get('[data-core-model-thinking-menu] .core-model-thinking-menu__trigger').trigger('click')
    await wrapper.get('[data-model-thinking-section="thinking"]').trigger('mouseenter')
    const enabledShallowOption = wrapper.get('[data-model-thinking-shallow-option]')
    expect(enabledShallowOption.classes()).toContain('active')
  })
})

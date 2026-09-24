import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreExecutionControls from '../src/components/CoreExecutionControls.vue'

describe('CoreExecutionControls', () => {
  it('places host controls directly after runtime permissions', () => {
    const wrapper = mount(CoreExecutionControls, {
      props: {
        thinkingMode: 'off',
        thinkingModeOptions: [],
      },
      slots: {
        'after-runtime': '<button data-test-workspace>环境</button>',
      },
    })
    const children = wrapper.get('.core-execution-controls').element.children
    expect(children[0].getAttribute('data-core-runtime-menu')).not.toBeNull()
    expect(children[1].getAttribute('data-test-workspace')).not.toBeNull()
    expect(children[2].getAttribute('data-core-model-thinking-menu')).not.toBeNull()
  })

  it('groups model and thinking controls into the compact selector', async () => {
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

    expect(wrapper.find('[data-model-thinking-shallow-option]').exists()).toBe(false)
    expect(wrapper.emitted('update:shallowThinkingEnabled')).toBeUndefined()
  })

  it('uses the shared compact classification toggle in the model menu', async () => {
    const wrapper = mount(CoreExecutionControls, {
      props: {
        modelValue: 'model-1',
        catalogView: 'group',
        thinkingMode: 'off',
        modelOptions: [{ value: 'model-1', label: 'Model', group: 'Free', groupKey: 'group:free' }],
        thinkingModeOptions: [{ value: 'off', label: '关闭' }],
      },
    })
    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    await wrapper.get('[data-model-thinking-section="model"]').trigger('mouseenter')
    expect(wrapper.get('[data-model-catalog-view="group"]').attributes('aria-pressed')).toBe('true')
    await wrapper.get('[data-model-catalog-view="provider"]').trigger('click')
    expect(wrapper.emitted('update:catalogView')).toEqual([['provider']])
  })
})

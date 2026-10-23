import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PluginSystemContributions from '../src/components/PluginSystemContributions.vue'

function makeRpc() {
  return vi.fn(async (method: string) => {
    if (method !== 'plugin.system.ui') return {}
    return {
      styles: [{ plugin: 'demo', url: '/api/core/plugin-system/demo/assets/style.css' }],
      scripts: [],
      regions: [
        {
          plugin: 'demo',
          region: 'settings',
          order: 10,
          mode: '',
          replace: false,
          blocks: [
            {
              type: 'text',
              label: 'Status',
              value: 'Ready',
              text: '',
              state: '',
              items: [],
              detail: '',
            },
          ],
          actions: [],
        },
        {
          plugin: 'demo',
          region: 'right',
          order: 10,
          mode: '',
          replace: false,
          blocks: [],
          actions: [],
        },
      ],
      errors: [],
    }
  })
}

afterEach(() => {
  document.head
    .querySelectorAll('link[data-plugin-system-style]')
    .forEach((node) => node.remove())
})

describe('plugin system contributions', () => {
  it('injects styles and renders only the requested region', async () => {
    const wrapper = mount(PluginSystemContributions, {
      props: { requestRpc: makeRpc(), region: 'settings' },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Status')
    expect(wrapper.text()).toContain('Ready')
    expect(wrapper.text()).not.toContain('right')
    const link = document.head.querySelector('link[data-plugin-system-style]')
    expect(link).not.toBeNull()
    expect(link?.getAttribute('href')).toBe(
      '/api/core/plugin-system/demo/assets/style.css',
    )
  })
})

import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PluginSystemContributions from '../src/components/PluginSystemContributions.vue'

function makeRpc() {
  return vi.fn(async (method: string) => {
    if (method !== 'plugin.system.ui') return {}
    return {
      styles: [{ plugin: 'demo', url: '/api/core/plugin-system/demo/assets/style.css' }],
      scripts: [{ plugin: 'demo', url: '/api/core/plugin-system/demo/assets/panel.js' }],
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
  document.head
    .querySelectorAll('script[data-plugin-system-script]')
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
    const script = document.head.querySelector('script[data-plugin-system-script]')
    expect(script?.getAttribute('src')).toBe(
      '/api/core/plugin-system/demo/assets/panel.js',
    )
  })
})

describe('plugin region interactions', () => {
  function regionRpc(overrides: Record<string, unknown> = {}) {
    return vi.fn(async (method: string) => {
      if (method !== 'plugin.system.ui') return {}
      return {
        styles: [],
        scripts: [],
        regions: [
          {
            plugin: 'painter',
            region: 'settings',
            order: 10,
            mode: '',
            replace: false,
            entry_url: '/api/core/plugin-system/painter/assets/entry.js',
            blocks: [],
            actions: [],
          },
          {
            plugin: 'act',
            region: 'settings',
            order: 20,
            mode: '',
            replace: false,
            blocks: [],
            actions: [
              { id: 'safe', title: '安全', operation: 'demo.ok' },
              {
                id: 'risky',
                title: '危险',
                operation: 'demo.wipe',
                dangerous: true,
              },
              {
                id: 'args',
                title: '带参',
                operation: 'demo.run',
                input_schema: {
                  type: 'object',
                  properties: {
                    path: { type: 'string', title: '路径', required: true },
                    count: { type: 'number', title: '数量' },
                  },
                },
              },
            ],
          },
          ...Object.entries(overrides).map(([key, value]) => ({ key, value })),
        ],
        errors: [],
      }
    })
  }

  it('renders an entry container for self-drawn regions', async () => {
    const wrapper = mount(PluginSystemContributions, {
      props: { requestRpc: regionRpc(), region: 'settings' },
    })
    await flushPromises()
    const container = wrapper.find('[data-plugin-entry="painter"]')
    expect(container.exists()).toBe(true)
    expect(container.attributes('data-entry-url')).toContain('entry.js')
  })

  it('asks for confirmation before a dangerous action', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const rpc = regionRpc()
    const wrapper = mount(PluginSystemContributions, {
      props: { requestRpc: rpc, region: 'settings' },
    })
    await flushPromises()
    await wrapper.find('[data-action="risky"]').trigger('click')
    expect(confirm).toHaveBeenCalled()
    expect(rpc).not.toHaveBeenCalledWith('demo.wipe', {})
    confirm.mockRestore()
  })

  it('collects input schema arguments before invoking', async () => {
    const rpc = regionRpc()
    const wrapper = mount(PluginSystemContributions, {
      props: { requestRpc: rpc, region: 'settings' },
    })
    await flushPromises()
    await wrapper.find('[data-action="args"]').trigger('click')
    await flushPromises()
    const form = wrapper.find('form.plugin-action-form')
    expect(form.exists()).toBe(true)
    const inputs = form.findAll('input')
    await inputs[0].setValue('notes.md')
    await inputs[1].setValue('3')
    await form.trigger('submit')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('demo.run', { path: 'notes.md', count: 3 })
  })
})

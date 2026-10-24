import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import LeftPluginDock from '../src/components/LeftPluginDock.vue'

function rpcWithLeftContribution() {
  return vi.fn(async (method: string) => {
    if (method !== 'plugin.system.ui') return {}
    return {
      styles: [],
      scripts: [],
      regions: [
        {
          plugin: 'notesync',
          region: 'left',
          order: 50,
          mode: '',
          replace: false,
          blocks: [
            { type: 'status', label: 'State', value: 'synced', text: '', state: '', items: [], detail: '' },
          ],
          actions: [
            { id: 'sync', title: 'Sync now', operation: 'notesync.sync' },
          ],
        },
        {
          plugin: 'replacer',
          region: 'left',
          order: 60,
          mode: '',
          replace: true,
          blocks: [],
          actions: [],
        },
      ],
      windows: [],
      modes: [],
      errors: [],
    }
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('left plugin dock', () => {
  it('registers non-replace left contributions as icon items', async () => {
    const wrapper = mount(LeftPluginDock, { props: { requestRpc: rpcWithLeftContribution() } })
    await flushPromises()

    const items = wrapper.findAll('[data-plugin-dock-item]')
    // user:“左侧栏可以添加图标注册一个项”+replace 接管者不进 dock。
    expect(items.map((item) => item.attributes('data-plugin-dock-item'))).toEqual(['notesync'])
    expect(items[0].text()).toBe('N')
  })

  it('toggles an expanded panel rendering the contribution blocks and actions', async () => {
    const rpc = rpcWithLeftContribution()
    const wrapper = mount(LeftPluginDock, { props: { requestRpc: rpc } })
    await flushPromises()

    expect(wrapper.find('[data-plugin-dock-panel]').exists()).toBe(false)
    await wrapper.find('[data-plugin-dock-item="notesync"]').trigger('click')
    await flushPromises()

    const panel = wrapper.find('[data-plugin-dock-panel="notesync:0"]')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('synced')

    await panel.find('button').trigger('click')
    expect(rpc).toHaveBeenCalledWith('notesync.sync', {})

    // 再点同一个图标收起。
    await wrapper.find('[data-plugin-dock-item="notesync"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-plugin-dock-panel]').exists()).toBe(false)
  })

  it('renders nothing without plugin contributions', async () => {
    const wrapper = mount(LeftPluginDock, {
      props: { requestRpc: vi.fn(async () => ({})) },
    })
    await flushPromises()
    expect(wrapper.find('[data-left-plugin-dock]').exists()).toBe(false)
  })
})

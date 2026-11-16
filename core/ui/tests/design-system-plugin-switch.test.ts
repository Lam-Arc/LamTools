import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Editor from '../src/components/CorePluginSystemEditor.vue'
import SundaySwitch from '../src/components/SundaySwitch.vue'

describe('plugin switch integration', () => {
  it('uses the shared switch, keeps a busy indicator, and rolls back after failure', async () => {
    let rejectToggle!: (reason: Error) => void
    const rpc = vi.fn((method: string) => {
      if (method === 'plugin.system.list') return Promise.resolve({ plugins: [{ name: 'demo', version: '1', enabled: true, scope: 'global', root: '/demo' }], errors: [] })
      if (method === 'plugin.system.disable') return new Promise((_resolve, reject) => { rejectToggle = reject })
      return Promise.resolve({})
    })
    const wrapper = mount(Editor, { props: { requestRpc: rpc } })
    await flushPromises()
    const control = wrapper.findComponent(SundaySwitch)
    expect(control.exists()).toBe(true)
    const input = control.get('input[role="switch"]')
    expect((input.element as HTMLInputElement).checked).toBe(true)
    await input.setValue(false)
    expect(rpc).toHaveBeenCalledWith('plugin.system.disable', { name: 'demo' })
    expect((input.element as HTMLInputElement).disabled).toBe(true)
    expect(control.find('.spin').exists()).toBe(true)
    rejectToggle(new Error('failed'))
    await flushPromises()
    expect((input.element as HTMLInputElement).checked).toBe(true)
    expect((input.element as HTMLInputElement).disabled).toBe(false)
    wrapper.unmount()
  })
})

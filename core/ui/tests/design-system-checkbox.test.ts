import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginConfigPanel from '../src/components/PluginConfigPanel.vue'
import CoreLoadToolsEditor from '../src/components/CoreLoadToolsEditor.vue'

describe('shared checkbox integration', () => {
  it('keeps boolean plugin configuration editable and saves a boolean', async () => {
    const rpc = vi.fn(async (method: string) => method === 'plugin.system.config.get'
      ? { config: { enabled: false }, schema: { properties: { enabled: { type: 'boolean', title: '启用' } } } }
      : {})
    const wrapper = mount(PluginConfigPanel, { props: { pluginName: 'demo', version: '1', description: '', requestRpc: rpc } })
    await flushPromises()
    await wrapper.get('input.sunday-checkbox').setValue(true)
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('plugin.system.config.update', { name: 'demo', config: { enabled: true } })
    wrapper.unmount()
  })
  it('keeps individual tool selection and save semantics', async () => {
    const rpc = vi.fn(async (method: string) => method === 'config.loadtools.get'
      ? { modes: { consider: { description: '', tools: ['read_file'] } }, catalog: [{ name: 'read_file', category: 'file_read' }], source: 'builtin' }
      : {})
    const wrapper = mount(CoreLoadToolsEditor, { props: { requestRpc: rpc } })
    await flushPromises()
    const box = wrapper.get('.tool-row input.sunday-checkbox')
    expect((box.element as HTMLInputElement).checked).toBe(true)
    await box.setValue(false)
    await wrapper.get('.loadtools-save').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('config.loadtools.set', { modes: { consider: { description: '', tools: [] } } })
    wrapper.unmount()
  })
})

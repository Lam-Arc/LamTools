import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import PluginModeHost from '../src/components/PluginModeHost.vue'
import { CORE_PLUGIN_MODE_CONTEXT, useCorePluginModeContext } from '../src/plugins/context'
import { pluginUIRegistry, registerMode } from '../src/plugins/registry'

afterEach(() => pluginUIRegistry.clear())
describe('plugin mode session scope', () => {
  it('ignores session selections from a mode that has been left', async () => {
    const callbacks: Array<(id: string) => Promise<void>> = []
    const view = defineComponent({ setup() {
      callbacks.push(useCorePluginModeContext().selectSession)
      return () => h('div', 'mode')
    } })
    for (const id of ['workflow', 'study']) registerMode({ pluginId: id, id, title: id, entry: '' }, async () => view)
    const selectSession = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(PluginModeHost, { props: { pluginId: 'workflow', modeId: 'workflow' }, global: { provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: { selectSession } } } })
    await flushPromises()
    await wrapper.setProps({ pluginId: 'study', modeId: 'study' })
    await flushPromises()
    await callbacks[0]('workflow:old')
    expect(selectSession).not.toHaveBeenCalled()
    await callbacks[1]('study:main')
    expect(selectSession).toHaveBeenCalledWith('study:main')
    wrapper.unmount()
    await callbacks[1]('study:late')
    expect(selectSession).toHaveBeenCalledTimes(1)
  })
})

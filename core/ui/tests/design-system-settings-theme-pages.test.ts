import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { SUNDAY_DARK_THEME, SUNDAY_LIGHT_THEME } from '../src/helpers/theme'
import AccountShell from '../src/components/AccountShell.vue'
import PluginsShell from '../src/components/PluginsShell.vue'
import SearchShell from '../src/components/SearchShell.vue'
import CoreSettings from '../src/components/CoreSettings.vue'
import CoreProjectSettings from '../src/components/CoreProjectSettings.vue'
const rpc = vi.fn(async () => ({}))
const inputs = [
  { component: AccountShell, props: {} },
  { component: PluginsShell, props: { requestRpc: rpc, transport: {} } },
  { component: SearchShell, props: { requestRpc: rpc, sessions: [], onJump: vi.fn() } },
  { component: CoreSettings, props: { requestRpc: rpc, models: [], providers: [], modelGroups: [], catalogView: 'provider', commandShellPlatform: 'other', density: 'standard' } },
  { component: CoreProjectSettings, props: { requestRpc: rpc, project: { id: 'p', name: 'p', iconKey: 'folder', colorKey: 'gray' } } },
]
describe('settings theme consistency across pages', () => {
  it('updates the actual page theme consistently when switching presets', async () => {
    for (const item of inputs) {
      const wrapper = shallowMount(item.component as any, { props: { ...item.props, theme: SUNDAY_DARK_THEME }, global: { stubs: { Teleport: true } } })
      const vars = () => {
        const shell = wrapper.findComponent({ name: 'SettingsShell' })
        return item.component === CoreProjectSettings ? shell.props('settingsThemeStyle') as Record<string, string> : (wrapper.element as HTMLElement).style
      }
      const read = (name: string) => item.component === CoreProjectSettings ? (vars() as Record<string, string>)[name] : (vars() as CSSStyleDeclaration).getPropertyValue(name)
      expect(read('--settings-control-solid')).toBe(SUNDAY_DARK_THEME.controlStops[0].color)
      await wrapper.setProps({ theme: SUNDAY_LIGHT_THEME })
      expect(read('--settings-control-solid')).toBe(SUNDAY_LIGHT_THEME.controlStops[0].color)
      expect(read('--settings-main-text')).toBe(SUNDAY_LIGHT_THEME.mainText)
      wrapper.unmount()
    }
  })
})

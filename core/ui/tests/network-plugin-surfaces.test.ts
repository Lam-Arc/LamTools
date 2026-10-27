// user:“实现这个插件，也正好实验我们的新插件架构”+(左竖栏打开完整页，分屏和侧栏复用同一个服务)。
import { afterEach, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AppRail from '../src/components/AppRail.vue'
import { setPluginPageEntries } from '../src/plugins/contributions'

afterEach(() => setPluginPageEntries([]))
it('exposes a declared plugin page in the main rail and emits its verified identity', async () => {
  setPluginPageEntries([{ plugin: 'network-exploration', id: 'network', title: '网络拓展', navigation: true, entry_url: '/api/core/plugin-system/network-exploration/assets/ui/page.mjs' }])
  const wrapper = mount(AppRail)
  try {
    const button = wrapper.get('[data-plugin-rail="network-exploration:network"]')
    await button.trigger('click')
    expect(wrapper.emitted('open-plugin-page')?.[0]?.[0]).toMatchObject({ plugin: 'network-exploration', id: 'network' })
  } finally { wrapper.unmount() }
})

it('does not add ordinary split pages to the main navigation', () => {
  setPluginPageEntries([{ plugin: 'demo', id: 'detail', title: 'Detail', entry_url: '/api/core/plugin-system/demo/assets/page.mjs' }])
  const wrapper = mount(AppRail)
  try { expect(wrapper.find('[data-plugin-rail]').exists()).toBe(false) } finally { wrapper.unmount() }
})

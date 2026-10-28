// user:“注意一下插件市场，如果没有或者没做好的话给它做好”+(无缓存失败和失败安装必须明确提示，可恢复重试)。
import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import PluginMarket from '../src/components/PluginMarket.vue'

const plugin = { id: 'qq-bot', title: 'QQ robot', description: '连接 QQ 私聊与群聊', category: '消息与协作', capabilities: [], version: '0.1.1', installed_version: '', installable: true, update_available: false, repository_url: 'https://github.com/Lam-Arc/Sunday-Plugins' }

it('shows a load error even when unavailable placeholder entries exist', async () => {
  const requestRpc = vi.fn(async () => ({ plugins: [{ ...plugin, installable: false }], source: 'unavailable', error: '无法连接 GitHub，请重试' }))
  const wrapper = mount(PluginMarket, { props: { requestRpc } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('无法连接 GitHub')
  expect(wrapper.text()).not.toContain('当前显示缓存目录')
  wrapper.unmount()
})

it('does not announce success when installation did not produce an available plugin', async () => {
  const requestRpc = vi.fn(async (method: string) => method === 'plugin.market.list'
    ? { plugins: [plugin], source: 'github' }
    : { installed: true, available: false, backend: { state: 'failed', error: '插件启动失败' } })
  const wrapper = mount(PluginMarket, { props: { requestRpc } })
  await flushPromises()
  await wrapper.get('[data-market-action="qq-bot"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('插件启动失败')
  expect(wrapper.emitted('changed')).toBeUndefined()
  wrapper.unmount()
})

it.each(['disabled', 'safe_mode'])('preserves a successful %s installation instead of reporting startup failure', async (state) => {
  const requestRpc = vi.fn(async (method: string) => method === 'plugin.market.list'
    ? { plugins: [{ ...plugin, installed_version: '0.1.0', update_available: true }], source: 'github' }
    : { updated: true, available: false, backend: { state, error: null } })
  const wrapper = mount(PluginMarket, { props: { requestRpc } })
  await flushPromises()
  await wrapper.get('[data-market-action="qq-bot"]').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper.emitted('changed')).toHaveLength(1)
  expect(wrapper.text()).toContain(state === 'disabled' ? '仍保持禁用' : '安全模式')
  wrapper.unmount()
})

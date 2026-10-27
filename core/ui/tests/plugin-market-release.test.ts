// user:“插件页再加上插件市场的界面…目前市场就提供一个 QQ robot 和哔哩哔哩”+(验收真实市场加载、安装、更新与失败状态)。
import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PluginMarket from '../src/components/PluginMarket.vue'
import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'

const rows = [
  { id: 'qq-bot', title: 'QQ robot', description: 'QQ 私聊与群聊', category: '消息与协作', capabilities: ['持久会话'], version: '0.1.0', installed_version: '', installable: true, update_available: false, repository_url: 'https://github.com/Lam-Arc/Sunday-Plugins' },
  { id: 'bili-scroll', title: '刷B站', description: '视频与字幕', category: '内容与信息', capabilities: ['内容简报'], version: '2.3.0', installed_version: '2.2.0', installable: true, update_available: true, repository_url: 'https://github.com/Lam-Arc/Sunday-Plugins' },
]

describe('GitHub plugin market', () => {
  it('opens the market from the plugin page while retaining installed management', async () => {
    Object.defineProperty(document, 'fonts', { value: { ready: Promise.resolve() }, configurable: true })
    const requestRpc = vi.fn(async (method: string) => method === 'plugin.market.list' ? { plugins: rows } : { plugins: [], errors: [] })
    const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc } })
    await flushPromises()
    const marketTab = wrapper.findAll('.sunday-segmented__item').find(button => button.text() === '插件市场')!
    await marketTab.trigger('click')
    await flushPromises()
    expect(wrapper.findComponent(PluginMarket).exists()).toBe(true)
    expect(wrapper.text()).toContain('QQ robot')
    wrapper.unmount()
  })
  it('shows the two plugins and sends only identity for verified installation', async () => {
    const requestRpc = vi.fn(async (method: string) => method === 'plugin.market.list' ? { plugins: rows, source: 'github' } : { installed: true })
    const wrapper = mount(PluginMarket, { props: { requestRpc } })
    await flushPromises()
    expect(wrapper.findAll('[data-market-plugin]')).toHaveLength(2)
    expect(wrapper.text()).toContain('QQ robot')
    await wrapper.get('[data-market-action="qq-bot"]').trigger('click')
    await flushPromises()
    expect(requestRpc).toHaveBeenCalledWith('plugin.market.install', { name: 'qq-bot' }, 180_000)
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect(wrapper.get('[data-market-action="bili-scroll"]').text()).toContain('更新')
    wrapper.unmount()
  })

  it('keeps the page usable on download failure and can retry', async () => {
    const requestRpc = vi.fn(async (method: string) => {
      if (method === 'plugin.market.list') return { plugins: rows, source: 'cache', error: 'network unavailable' }
      throw new Error('下载失败')
    })
    const wrapper = mount(PluginMarket, { props: { requestRpc } })
    await flushPromises()
    expect(wrapper.text()).toContain('缓存')
    await wrapper.get('[data-market-action="qq-bot"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('下载失败')
    expect(wrapper.get('[data-market-action="qq-bot"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})

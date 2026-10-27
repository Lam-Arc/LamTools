// user:“该重建就重建”+(插件开关是用户意图，界面必须另外显示后端就绪和失败原因)。
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CorePluginSystemEditor from '../src/components/CorePluginSystemEditor.vue'

describe('rebuilt plugin host status', () => {
  it('shows failed enabled backends and offers an explicit retry', async () => {
    const rpc = vi.fn(async (method: string) => method === 'plugin.system.list'
      ? { plugins: [{ name: 'demo', version: '1', enabled: true, available: false, scope: 'global', root: 'demo',
        backend: { state: 'failed', error: { message: '无法连接服务' } } }], errors: [] }
      : { restart_required: true })
    const wrapper = mount(CorePluginSystemEditor, { props: { requestRpc: rpc } })
    await flushPromises()
    expect(wrapper.text()).toContain('启动失败')
    expect(wrapper.text()).toContain('无法连接服务')
    const retry = wrapper.findAll('button').find(button => button.text().includes('重试启动'))!
    expect(retry).toBeTruthy()
    await retry.trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('plugin.system.enable', { name: 'demo' })
    expect(wrapper.text()).toContain('重启应用')
    wrapper.unmount()
  })
})

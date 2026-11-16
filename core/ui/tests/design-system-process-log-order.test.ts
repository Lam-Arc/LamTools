import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import RightSidebarProcesses from '../src/components/RightSidebarProcesses.vue'

describe('process log interaction', () => {
  it('keeps the selected log when an older request finishes later', async () => {
    const pending: Record<string, (value: Record<string, unknown>) => void> = {}
    const rpc = vi.fn((method: string, params?: Record<string, unknown>) => {
      if (method === 'process.list') return Promise.resolve({ processes: [{ pid: 42, command: 'example', alive: true, owned: true }] })
      if (method === 'process.log') return new Promise<Record<string, unknown>>(resolve => { pending[String(params?.stream)] = resolve })
      return Promise.resolve({})
    })
    const wrapper = mount(RightSidebarProcesses, { props: { requestRpc: rpc, sessionId: 'demo' } })
    await flushPromises()
    await wrapper.get('.core-process-panel__main').trigger('click')
    await wrapper.get('[role="tab"]:last-child').trigger('click')
    pending.stderr({ content: 'new stderr' }); await flushPromises()
    expect(wrapper.text()).toContain('new stderr')
    pending.stdout({ content: 'old stdout' }); await flushPromises()
    expect(wrapper.text()).toContain('new stderr')
    expect(wrapper.text()).not.toContain('old stdout')
    wrapper.unmount()
  })
  it('shows an error when the selected log cannot be loaded', async () => {
    const rpc = vi.fn(async (method: string) => {
      if (method === 'process.list') return { processes: [{ pid: 42, command: 'example', alive: true, owned: true }] }
      throw new Error('日志读取失败')
    })
    const wrapper = mount(RightSidebarProcesses, { props: { requestRpc: rpc, sessionId: 'demo' } })
    await flushPromises()
    await wrapper.get('.core-process-panel__main').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('日志读取失败')
    wrapper.unmount()
  })
  it('does not show a previous process log after switching processes', async () => {
    const pending: Record<number, (value: Record<string, unknown>) => void> = {}
    const rpc = vi.fn((method: string, params?: Record<string, unknown>) => {
      if (method === 'process.list') return Promise.resolve({ processes: [42, 43].map(pid => ({ pid, command: `process-${pid}`, alive: true, owned: true })) })
      return new Promise<Record<string, unknown>>(resolve => { pending[Number(params?.pid)] = resolve })
    })
    const wrapper = mount(RightSidebarProcesses, { props: { requestRpc: rpc, sessionId: 'demo' } })
    await flushPromises()
    await wrapper.get('[data-process-pid="42"] .core-process-panel__main').trigger('click')
    await wrapper.get('[data-process-pid="43"] .core-process-panel__main').trigger('click')
    pending[43]({ content: 'current log' }); await flushPromises()
    pending[42]({ content: 'old log' }); await flushPromises()
    expect(wrapper.text()).toContain('current log')
    expect(wrapper.text()).not.toContain('old log')
    wrapper.unmount()
  })
})

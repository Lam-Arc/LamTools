import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RightSidebarProcesses from '../src/components/RightSidebarProcesses.vue'

function processPayload(overrides: Record<string, unknown> = {}) {
  return {
    pid: 4321,
    session_id: 'thread-1',
    command: 'python -m http.server 8123',
    started_at: Date.now() / 1000 - 90,
    persistent: true,
    stdout_log: 'C:/tmp/out.log',
    stderr_log: 'C:/tmp/err.log',
    alive: true,
    owned: true,
    can_terminate: true,
    ...overrides,
  }
}

function rpcWith(processes: Record<string, unknown>[]) {
  return vi.fn(async (method: string) => {
    if (method === 'process.list') return { processes }
    if (method === 'process.log') {
      return { pid: 4321, stream: 'stdout', path: 'C:/tmp/out.log', content: 'serving at port 8123', truncated: false, missing: false }
    }
    return {}
  })
}

describe('RightSidebarProcesses', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('fetches the session process list and renders running rows', async () => {
    const rpc = rpcWith([processPayload()])
    const wrapper = mount(RightSidebarProcesses, {
      props: { requestRpc: rpc, sessionId: 'thread-1' },
    })
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('process.list', expect.objectContaining({ session_id: 'thread-1', thread_id: 'thread-1' }))
    const row = wrapper.get('[data-process-pid="4321"]')
    expect(row.text()).toContain('python -m http.server 8123')
    expect(row.find('.core-process-panel__dot.is-running').exists()).toBe(true)
    expect(row.text()).toContain('运行中')
    expect(row.get('.core-process-panel__action.is-danger').attributes('aria-label')).toContain('终止进程 4321')
    wrapper.unmount()
  })

  it('renders nothing and issues no RPC without a session scope', async () => {
    const rpc = rpcWith([processPayload()])
    const wrapper = mount(RightSidebarProcesses, { props: { requestRpc: rpc, sessionId: null } })
    await flushPromises()

    expect(rpc).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('没有长期后台进程')
    wrapper.unmount()
  })

  it('refreshes when a backend process/changed event arrives', async () => {
    const rpc = rpcWith([processPayload()])
    const wrapper = mount(RightSidebarProcesses, {
      props: { requestRpc: rpc, sessionId: 'thread-1' },
    })
    await flushPromises()
    const callsAfterMount = rpc.mock.calls.length

    await wrapper.setProps({ processSignal: { method: 'process/changed', payload: { pid: 4321, action: 'killed' } } })
    await flushPromises()
    expect(rpc.mock.calls.length).toBeGreaterThan(callsAfterMount)
    wrapper.unmount()
  })

  it('terminates an owned running process and forgets an exited record', async () => {
    const rpc = rpcWith([processPayload()])
    const wrapper = mount(RightSidebarProcesses, {
      props: { requestRpc: rpc, sessionId: 'thread-1' },
    })
    await flushPromises()

    await wrapper.get('.core-process-panel__action.is-danger').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('process.kill', expect.objectContaining({ thread_id: 'thread-1', pid: 4321 }))
    wrapper.unmount()

    const exitedRpc = rpcWith([processPayload({ alive: false, can_terminate: false })])
    const exited = mount(RightSidebarProcesses, {
      props: { requestRpc: exitedRpc, sessionId: 'thread-1' },
    })
    await flushPromises()
    expect(exited.get('[data-process-pid="4321"]').text()).toContain('已退出')
    const forget = exited.get('.core-process-panel__action')
    expect(forget.attributes('aria-label')).toContain('移除')
    await forget.trigger('click')
    await flushPromises()
    expect(exitedRpc).toHaveBeenCalledWith('process.forget', expect.objectContaining({ thread_id: 'thread-1', pid: 4321 }))
    exited.unmount()
  })

  it('marks adopted processes as lost and offers no terminate action', async () => {
    const rpc = rpcWith([processPayload({ alive: true, owned: false, can_terminate: false })])
    const wrapper = mount(RightSidebarProcesses, {
      props: { requestRpc: rpc, sessionId: 'thread-1' },
    })
    await flushPromises()

    const row = wrapper.get('[data-process-pid="4321"]')
    expect(row.find('.core-process-panel__dot.is-lost').exists()).toBe(true)
    expect(row.text()).toContain('已失联')
    expect(row.find('.core-process-panel__action').exists()).toBe(false)
    wrapper.unmount()
  })

  it('expands a row to show the log tail from process.log', async () => {
    const rpc = rpcWith([processPayload()])
    const wrapper = mount(RightSidebarProcesses, {
      props: { requestRpc: rpc, sessionId: 'thread-1' },
    })
    await flushPromises()

    await wrapper.get('.core-process-panel__main').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('process.log', expect.objectContaining({ pid: 4321, stream: 'stdout' }))
    expect(wrapper.get('.core-process-panel__log').text()).toContain('serving at port 8123')
    wrapper.unmount()
  })
})

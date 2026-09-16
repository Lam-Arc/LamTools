import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import CoreToastHost from '../src/components/CoreToastHost.vue'
import {
  __resetCoreToastStoreForTests,
  createCoreConnectionErrorToastGate,
  dismissAllToasts,
  dismissToast,
  showToast,
  useCoreToast,
} from '../src/composables/useCoreToast'
import { mount } from '@vue/test-utils'

describe('useCoreToast service', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    __resetCoreToastStoreForTests()
  })

  it('queues toasts and auto-dismisses per kind after the default duration', () => {
    showToast('error', '发送失败')
    showToast('notice', '已保存')

    const { toasts } = useCoreToast()
    expect(toasts.value.map((toast) => toast.text)).toEqual(['发送失败', '已保存'])

    // error defaults to 8s, notice to 3s
    vi.advanceTimersByTime(3001)
    expect(toasts.value.map((toast) => toast.text)).toEqual(['发送失败'])
    vi.advanceTimersByTime(5000)
    expect(toasts.value).toHaveLength(0)
  })

  it('de-duplicates identical text within the window', () => {
    const first = showToast('error', '网络不可用')
    const second = showToast('error', '网络不可用')
    expect(second).toBe(first)
    const { toasts } = useCoreToast()
    expect(toasts.value).toHaveLength(1)
  })

  it('dismisses a single toast and clears its timer', () => {
    const id = showToast('error', '待关闭')
    dismissToast(id)
    const { toasts } = useCoreToast()
    expect(toasts.value).toHaveLength(0)
    // No auto-dismiss after the timer was cleared.
    vi.advanceTimersByTime(10000)
    expect(toasts.value).toHaveLength(0)
  })

  it('dismisses all and ignores empty text', () => {
    expect(showToast('notice', '  ')).toBe(-1)
    showToast('error', 'a')
    showToast('notice', 'b')
    dismissAllToasts()
    const { toasts } = useCoreToast()
    expect(toasts.value).toHaveLength(0)
  })

  it('honours an explicit duration override', () => {
    showToast('notice', '临时', 100)
    vi.advanceTimersByTime(101)
    const { toasts } = useCoreToast()
    expect(toasts.value).toHaveLength(0)
  })

  it('suppresses a transient disconnect that reconnects inside two seconds', () => {
    let connected = false
    const gate = createCoreConnectionErrorToastGate({ isConnected: () => connected })

    gate.report('LamTools direct transport disconnected (code=1006)', 8000)
    vi.advanceTimersByTime(1500)
    connected = true
    gate.onConnectionState('open')
    vi.advanceTimersByTime(1000)

    expect(useCoreToast().toasts.value).toHaveLength(0)
  })

  it('shows a diagnosed disconnect only after the two-second grace expires', () => {
    const gate = createCoreConnectionErrorToastGate({ isConnected: () => false })

    gate.report('LamTools direct transport disconnected (code=1013, reason=overflow)', 8000)
    vi.advanceTimersByTime(1999)
    expect(useCoreToast().toasts.value).toHaveLength(0)
    vi.advanceTimersByTime(1)

    expect(useCoreToast().toasts.value.map((toast) => toast.text)).toEqual([
      'LamTools direct transport disconnected (code=1013, reason=overflow)',
    ])
  })

  it('keeps non-transport errors immediate', () => {
    const gate = createCoreConnectionErrorToastGate({ isConnected: () => false })
    gate.report('模型供应商返回 502', 8000)
    expect(useCoreToast().toasts.value.map((toast) => toast.text)).toEqual(['模型供应商返回 502'])
  })
})

describe('CoreToastHost', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    __resetCoreToastStoreForTests()
  })

  it('renders a stacked, closable toast list without overwriting earlier toasts', async () => {
    showToast('error', '第一个错误')
    showToast('notice', '一条通知')
    const wrapper = mount(CoreToastHost)
    await nextTick()

    const items = wrapper.findAll('.core-toast')
    expect(items).toHaveLength(2)
    expect(items[0].classes()).toContain('core-toast--error')
    expect(items[0].attributes('role')).toBe('alert')
    expect(items[1].classes()).toContain('core-toast--notice')
    expect(items[1].attributes('role')).toBe('status')

    // Close the first toast via its dismiss button.
    await items[0].get('.core-toast__dismiss').trigger('click')
    await nextTick()
    const remaining = wrapper.findAll('.core-toast')
    expect(remaining).toHaveLength(1)
    expect(remaining[0].text()).toContain('一条通知')
  })

  it('renders nothing when the queue is empty', () => {
    const wrapper = mount(CoreToastHost)
    expect(wrapper.findAll('.core-toast')).toHaveLength(0)
  })
})

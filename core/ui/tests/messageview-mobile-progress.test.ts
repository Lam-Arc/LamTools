import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage } from '../src/types'
import { createFakeTransport } from './fake-transport'

function message(progress: Record<string, unknown>, content = ''): CoreMessage {
  return {
    id: 'assistant:mobile-turn', role: 'assistant', content, timestamp: '', parts: [],
    metadata: { mobile_turn_progress: progress },
  }
}

function mountProgress(msg: CoreMessage) {
  return mount(MessageView, { props: { msg, transport: createFakeTransport() } })
}

afterEach(() => vi.useRealTimers())

describe('mobile turn progress', () => {
  it('shows the current stage without rendering diagnostics as answer text', async () => {
    const wrapper = mountProgress(message({ stage: 'http_send_start', label: '正在发送模型请求', status: 'running' }))
    expect(wrapper.find('.mobile-turn-progress').attributes('aria-label')).toBe('执行进度：正在发送模型请求')
    expect(wrapper.find('.mobile-turn-progress__track').attributes('aria-hidden')).toBe('true')
    expect(wrapper.find('.assistant-answer').text()).not.toContain('正在发送模型请求')
    await wrapper.setProps({ msg: message({ stage: 'http_headers_received', label: '已收到模型响应头', status: 'running' }) })
    expect(wrapper.find('.mobile-turn-progress__label').text()).toBe('已收到模型响应头')
    wrapper.unmount()
  })

  it('briefly shows a terminal state, then keeps the answer while hiding progress', async () => {
    vi.useFakeTimers()
    const wrapper = mountProgress(message({ stage: 'done', label: '已完成', status: 'completed', expires_at: Date.now() + 1500 }, '最终回答'))
    expect(wrapper.find('.mobile-turn-progress').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(1500)
    expect(wrapper.find('.mobile-turn-progress').exists()).toBe(false)
    expect(wrapper.text()).toContain('最终回答')
    wrapper.unmount()
  })

  it('does not revive expired progress and clears its timer on unmount', () => {
    vi.useFakeTimers()
    const expired = mountProgress(message({ label: '运行失败', status: 'failed', expires_at: Date.now() - 1 }, '错误详情'))
    expect(expired.find('.mobile-turn-progress').exists()).toBe(false)
    expect(expired.text()).toContain('错误详情')
    expired.unmount()
    const clearTimeoutSpy = vi.spyOn(globalThis, 'clearTimeout')
    const active = mountProgress(message({ label: '已取消', status: 'cancelled', expires_at: Date.now() + 1500 }))
    active.unmount()
    expect(clearTimeoutSpy).toHaveBeenCalled()
    clearTimeoutSpy.mockRestore()
  })

  it('provides motion reduction for the indeterminate animation', () => {
    const source = readFileSync(resolve(__dirname, '../src/components/MessageView.vue'), 'utf8')
    expect(source).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.mobile-turn-progress__fill \{ animation: none;/)
  })
})

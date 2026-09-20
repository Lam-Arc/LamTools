import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatOutlineNavigator from '../src/components/ChatOutlineNavigator.vue'
import {
  CHAT_OUTLINE_ACTIVATION_RATIO,
  compactOutlineMarkerPositions,
  loadedUserMessageSignature,
  nearestMountedOutlineIndex,
  nearestOutlineIndex,
  normalizeChatOutlinePayload,
  outlineIndexFromScrollProgress,
  outlineMarkerStyle,
  resolveOutlineSelectedIndex,
} from '../src/components/chatOutlineNavigator'
import type { CoreMessage } from '../src/types'

function message(id: string, role: CoreMessage['role'], content = id): CoreMessage {
  return { id, role, content, timestamp: '', parts: [] }
}

describe('ChatOutlineNavigator contracts', () => {
  const originalGetContext = HTMLCanvasElement.prototype.getContext

  beforeEach(() => {
    HTMLCanvasElement.prototype.getContext = (() => ({
      setTransform: vi.fn(),
      clearRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
    })) as unknown as typeof HTMLCanvasElement.prototype.getContext
  })

  afterEach(() => {
    HTMLCanvasElement.prototype.getContext = originalGetContext
  })

  it('normalizes the thread.outline contract and drops malformed rows', () => {
    expect(normalizeChatOutlinePayload({
      items: [
        { message_id: 'm2', turn_id: 't2', seq: 2, timestamp: '2', prompt: 'second', response_excerpt: 'reply' },
        { message_id: 'm1', turn_id: 't1', seq: 1, timestamp: '1', prompt: 'first', response_excerpt: '' },
        { turn_id: 'missing-id' },
        null,
      ],
    })).toEqual([
      { message_id: 'm1', turn_id: 't1', seq: 1, timestamp: '1', prompt: 'first', response_excerpt: '' },
      { message_id: 'm2', turn_id: 't2', seq: 2, timestamp: '2', prompt: 'second', response_excerpt: 'reply' },
    ])
  })

  it('uses only loaded user ids as the refresh signature', () => {
    const first = [message('u1', 'user', 'draft'), message('a1', 'assistant', 'streaming')]
    const sameIds = [message('u1', 'user', 'edited locally'), message('a1', 'assistant', 'new token')]
    const next = [...sameIds, message('u2', 'user')]
    expect(loadedUserMessageSignature(first)).toBe(loadedUserMessageSignature(sameIds))
    expect(loadedUserMessageSignature(next)).not.toBe(loadedUserMessageSignature(sameIds))
  })

  it('chooses the marker nearest the 38% activation geometry and shortens distant markers', () => {
    expect(CHAT_OUTLINE_ACTIVATION_RATIO).toBe(0.38)
    expect(nearestOutlineIndex([20, 80, 180], 68)).toBe(1)
    const selected = outlineMarkerStyle(1, 1, 4)
    const near = outlineMarkerStyle(0, 1, 4)
    const middle = outlineMarkerStyle(3, 1, 4)
    const far = outlineMarkerStyle(4, 1, 4)
    expect(selected.length).toBeGreaterThan(near.length)
    expect(near.length).toBeGreaterThan(middle.length)
    expect(middle.length).toBeGreaterThan(far.length)
    expect(selected.opacity).toBeGreaterThan(far.opacity)
    expect(resolveOutlineSelectedIndex(3, 2, true)).toBe(3)
    expect(resolveOutlineSelectedIndex(-1, 2, true)).toBe(2)
    expect(resolveOutlineSelectedIndex(-1, 2, false)).toBe(-1)
  })

  it('keeps short marker groups compact while active selection uses mounted card geometry', () => {
    expect(compactOutlineMarkerPositions(4, 100, 300, 8)).toEqual([238, 246, 254, 262])
    expect(compactOutlineMarkerPositions(4, 100, 24, 12)).toEqual([100, 108, 116, 124])
    expect(compactOutlineMarkerPositions(1, 100, 300, 12)).toEqual([250])
    expect(nearestMountedOutlineIndex([
      { index: 0, centerY: 180 },
      { index: 3, centerY: 320 },
    ], 305)).toBe(3)
    expect(outlineIndexFromScrollProgress(0, 1000, 200, 4)).toBe(0)
    expect(outlineIndexFromScrollProgress(400, 1000, 200, 4)).toBe(2)
    expect(outlineIndexFromScrollProgress(800, 1000, 200, 4)).toBe(3)
  })

  it('fetches per session and loaded-user signature, then supports keyboard selection', async () => {
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    Object.defineProperty(thread, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 100, left: 0, width: 800, height: 500, right: 800, bottom: 600 }),
    })
    const requestRpc = vi.fn().mockResolvedValue({
      items: [
        { message_id: 'u1', turn_id: 't1', seq: 1, timestamp: '', prompt: 'first', response_excerpt: 'one' },
        { message_id: 'u2', turn_id: 't2', seq: 2, timestamp: '', prompt: 'second', response_excerpt: 'two' },
      ],
    })
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'session-1',
        messages: [message('u1', 'user'), message('a1', 'assistant')],
        requestRpc,
        scrollContainer: thread,
      },
    })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledWith('thread.outline', { thread_id: 'session-1' }))
    const root = wrapper.get('[data-chat-outline-navigator]')
    Object.defineProperty(root.element, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 0, left: 0, width: 32, height: 700, right: 32, bottom: 700 }),
    })
    const canvas = wrapper.get('canvas').element as HTMLCanvasElement
    Object.defineProperty(canvas, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ top: 0, left: 0, width: 32, height: 700, right: 32, bottom: 700 }),
    })
    expect(wrapper.get('.chat-outline-navigator__status').text()).toBe('')

    root.element.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))
    await vi.waitFor(() => expect(wrapper.get('.chat-outline-navigator__status').text()).toContain('共 2 条'))
    await root.trigger('keydown', { key: 'End' })
    await root.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')?.at(-1)).toEqual(['u2'])

    await wrapper.setProps({ messages: [message('u1', 'user'), message('a1', 'assistant', 'new token')] })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(requestRpc).toHaveBeenCalledTimes(1)
    await wrapper.setProps({ messages: [message('u1', 'user'), message('a1', 'assistant', 'new token'), message('u2', 'user')] })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledTimes(2))
    wrapper.unmount()
    thread.remove()
  })

  it('ignores an older session response that resolves after a switch', async () => {
    const pending: Array<(value: Record<string, unknown>) => void> = []
    const requestRpc = vi.fn().mockImplementation(() => new Promise<Record<string, unknown>>(resolve => {
      pending.push(resolve)
    }))
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'old-session',
        messages: [message('u1', 'user')],
        requestRpc,
        scrollContainer: thread,
      },
    })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledTimes(1))
    await wrapper.setProps({ sessionId: 'new-session' })
    await vi.waitFor(() => expect(requestRpc).toHaveBeenCalledTimes(2))
    pending[0]({ items: [{ message_id: 'old-message', seq: 1, prompt: 'stale' }] })
    pending[1]({ items: [{ message_id: 'new-message', seq: 1, prompt: 'fresh' }] })
    await vi.waitFor(() => expect(wrapper.get('[data-chat-outline-navigator]')).toBeTruthy())
    await wrapper.get('[data-chat-outline-navigator]').trigger('focusin')
    await vi.waitFor(() => expect(wrapper.get('[data-chat-outline-preview]')).toBeTruthy())
    expect(wrapper.get('[data-chat-outline-preview]').text()).toContain('fresh')
    expect(wrapper.get('[data-chat-outline-preview]').text()).not.toContain('stale')
    wrapper.unmount()
    thread.remove()
  })

  it('cancels a pending geometry frame when unmounted', async () => {
    const requestRpc = vi.fn().mockResolvedValue({
      items: [{ message_id: 'u1', seq: 1, prompt: 'first' }],
    })
    const thread = document.createElement('section')
    document.body.appendChild(thread)
    const requestFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation(() => 241)
    const cancelFrame = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => undefined)
    const wrapper = mount(ChatOutlineNavigator, {
      attachTo: document.body,
      props: {
        sessionId: 'session-1',
        messages: [message('u1', 'user')],
        requestRpc,
        scrollContainer: thread,
      },
    })
    await vi.waitFor(() => expect(requestFrame).toHaveBeenCalled())
    wrapper.unmount()
    expect(cancelFrame).toHaveBeenCalledWith(241)
    requestFrame.mockRestore()
    cancelFrame.mockRestore()
    thread.remove()
  })
})

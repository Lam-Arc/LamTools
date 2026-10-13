import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { hydrateSnapshot, applyCoreAppEvent, selectChatMessages, selectCoreWorkbenchMessages } from '../src/appServer'
import { coreSystemEventForItem, parseMemberWakeEntries } from '../src/appServer/systemEvents'
import type { CoreAppSnapshot } from '../src/appServer'
import type { CoreMessage } from '../src/types'
import CoreSystemEventRow from '../src/components/CoreSystemEventRow.vue'
import MessageView from '../src/components/MessageView.vue'
import { createFakeTransport } from './fake-transport'

/** A turn the runtime injected itself: `systemMessage` item, role `system`,
 *  with an origin marker on the item and on the turn. */
function injectedSnapshot(
  text: string,
  origin: string,
  options: { itemRole?: string; turnOrigin?: string; itemType?: string; extra?: Record<string, unknown> } = {},
): CoreAppSnapshot {
  const itemRole = options.itemRole ?? 'system'
  return hydrateSnapshot({
    thread_id: 'thread-system',
    snapshot_seq: 5,
    status: 'running',
    item_order: ['turn-2:system'],
    items: {
      'turn-2:system': {
        item_id: 'turn-2:system',
        turn_id: 'turn-2',
        type: options.itemType ?? 'systemMessage',
        role: itemRole,
        origin,
        status: 'completed',
        content: [{ type: 'text', text }],
        ...(options.extra || {}),
      },
    },
    turns: {
      'turn-2': { turn_id: 'turn-2', status: 'running', items: ['turn-2:system'], origin: options.turnOrigin ?? origin },
    },
    core: {
      thread_id: 'thread-system',
      snapshot_seq: 5,
      status: 'running',
      turns: { 'turn-2': { turn_id: 'turn-2', status: 'running', items: [] } },
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
    },
  })
}

function userSnapshot(text: string): CoreAppSnapshot {
  return injectedSnapshot(text, '', { itemType: 'userMessage', itemRole: '' })
}

describe('system event rows', () => {
  it('parses both wake shapes into name and optional message', () => {
    expect(parseMemberWakeEntries('子代理 cli_capture_v2 已完成。')).toEqual([
      { name: 'cli_capture_v2', state: '已完成', message: '' },
    ])
    expect(parseMemberWakeEntries('子代理 cli_capture_v2 已完成：改好了 3 个文件')).toEqual([
      { name: 'cli_capture_v2', state: '已完成', message: '改好了 3 个文件' },
    ])
    expect(parseMemberWakeEntries('子代理 cli_capture_v2 已失败。')).toEqual([
      { name: 'cli_capture_v2', state: '已失败', message: '' },
    ])
    expect(parseMemberWakeEntries('子代理 cli_capture_v2 已失败：沙箱超时')).toEqual([
      { name: 'cli_capture_v2', state: '已失败', message: '沙箱超时' },
    ])
  })

  it('recognises a member_wake item by type, role and origin, never by text', () => {
    const item = {
      item_id: 'x',
      type: 'systemMessage',
      role: 'system',
      origin: 'member_wake',
      content: [{ type: 'text', text: '任意文案，不带任何前缀' }],
    }
    const event = coreSystemEventForItem(item, '任意文案，不带任何前缀')
    expect(event?.kind).toBe('member_wake')
    // No text shim remains: the row is identified by the item's shape.
    expect(event?.entries).toEqual([])
  })

  it('reads the origin off the turn when the item omits it', () => {
    const item = { item_id: 'x', type: 'systemMessage', role: 'system', content: [{ type: 'text', text: '子代理 w 已完成。' }] }
    const event = coreSystemEventForItem(item, '子代理 w 已完成。', 'member_wake')
    expect(event?.kind).toBe('member_wake')
    expect(event?.entries).toHaveLength(1)
  })

  it('projected member_wake item renders the system row, never a user bubble', () => {
    const [message] = selectCoreWorkbenchMessages(injectedSnapshot('子代理 cli_capture_v2 已完成。', 'member_wake'))
    expect(message.metadata?.systemEvent).toMatchObject({ kind: 'member_wake' })

    const wrapper = mount(MessageView, { props: { msg: message, transport: createFakeTransport() } })
    expect(wrapper.find('[data-system-event-row]').exists()).toBe(true)
    expect(wrapper.find('.user-bubble').exists()).toBe(false)
    expect(wrapper.text()).toContain('cli_capture_v2')
    wrapper.unmount()
  })

  it('projected memory_resume item renders the system row with its own label', () => {
    const [message] = selectCoreWorkbenchMessages(injectedSnapshot('记忆续跑：继续上次未完成的任务。', 'memory_resume'))
    expect(message.metadata?.systemEvent).toMatchObject({ kind: 'memory_resume' })

    const wrapper = mount(MessageView, { props: { msg: message, transport: createFakeTransport() } })
    const row = wrapper.find('[data-system-event-row]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('记忆续跑')
    expect(wrapper.find('.user-bubble').exists()).toBe(false)
    wrapper.unmount()
  })

  it('an ordinary user item with no origin still renders as a bubble', () => {
    const [selected] = selectChatMessages(userSnapshot('帮我看一下这个文件'))
    expect(selected.metadata?.systemEvent).toBeUndefined()
    expect(selected.role).toBe('user')

    const message: CoreMessage = {
      id: selected.id,
      role: 'user',
      content: selected.content,
      timestamp: '',
      parts: [],
    }
    const wrapper = mount(MessageView, { props: { msg: message, transport: createFakeTransport() } })
    expect(wrapper.find('.user-bubble').exists()).toBe(true)
    expect(wrapper.find('[data-system-event-row]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not treat a plain systemMessage without an origin as a member wake', () => {
    const [message] = selectCoreWorkbenchMessages(injectedSnapshot('例行系统提示', '', { turnOrigin: '' }))
    expect(message.metadata?.systemEvent).toMatchObject({ kind: 'system' })
    expect(message.role).toBe('user')
  })

  it('keeps role and origin from the live item/started event, before any snapshot', () => {
    const base = hydrateSnapshot({
      thread_id: 'thread-live',
      snapshot_seq: 1,
      status: 'running',
      turns: { 'turn-2': { turn_id: 'turn-2', status: 'running', items: [] } },
      core: {
        thread_id: 'thread-live',
        snapshot_seq: 1,
        status: 'running',
        turns: { 'turn-2': { turn_id: 'turn-2', status: 'running', items: [] } },
        items: {},
        item_order: [],
        requests: {},
        artifacts: {},
      },
    })
    const next = applyCoreAppEvent(base, {
      event_id: 'e-wake',
      thread_id: 'thread-live',
      seq: 3,
      method: 'item/started',
      created_at: '2026-10-12T00:00:00Z',
      turn_id: 'turn-2',
      item_id: 'turn-2:system',
      payload: {
        type: 'systemMessage',
        role: 'system',
        status: 'completed',
        origin: 'member_wake',
        content: [{ type: 'text', text: '子代理 cli_capture_v2 已完成。' }],
      },
    })

    const [message] = selectCoreWorkbenchMessages(next)
    expect(message.id).toBe('turn-2:system')
    expect(message.metadata?.systemEvent).toMatchObject({ kind: 'member_wake' })
  })
})

describe('CoreSystemEventRow rendering', () => {
  it('renders name and state, with the member message when there is one', () => {
    const wrapper = mount(CoreSystemEventRow, {
      props: {
        event: {
          kind: 'member_wake' as const,
          text: '子代理 renderer_dev 已完成：渲染器与冒烟脚本都已交付。',
          entries: parseMemberWakeEntries('子代理 renderer_dev 已完成：渲染器与冒烟脚本都已交付。'),
        },
      },
    })
    const row = wrapper.find('[data-system-event-row]')
    expect(row.text()).toContain('子代理')
    expect(row.text()).toContain('renderer_dev')
    expect(row.text()).toContain('已完成')
    expect(row.text()).toContain('渲染器与冒烟脚本都已交付。')
    expect(row.find('.user-bubble').exists()).toBe(false)
    wrapper.unmount()
  })

  it('renders a bare completion line without a message', () => {
    const wrapper = mount(CoreSystemEventRow, {
      props: {
        event: {
          kind: 'member_wake' as const,
          text: '子代理 cli_capture_v2 已完成。',
          entries: parseMemberWakeEntries('子代理 cli_capture_v2 已完成。'),
        },
      },
    })
    const row = wrapper.find('[data-system-event-row]')
    expect(row.text()).toContain('cli_capture_v2')
    expect(row.text()).toContain('已完成')
    expect(row.text()).not.toContain('undefined')
    wrapper.unmount()
  })
})

describe('system row next to an earlier conclusion', () => {
  it('sits alongside the earlier turn conclusion without merging with it', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-wake-next',
      snapshot_seq: 9,
      status: 'running',
      item_order: ['r1', 'a1', 'turn-2:system', 'r2', 'a2'],
      items: {
        'turn-2:system': {
          item_id: 'turn-2:system',
          turn_id: 'turn-2',
          type: 'systemMessage',
          role: 'system',
          origin: 'member_wake',
          status: 'completed',
          content: [{ type: 'text', text: '子代理 renderer_dev 已完成。' }],
        },
      },
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['r1', 'a1'] },
        'turn-2': { turn_id: 'turn-2', status: 'running', items: ['turn-2:system', 'r2', 'a2'], origin: 'member_wake' },
      },
      core: {
        thread_id: 'thread-wake-next',
        snapshot_seq: 9,
        status: 'running',
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['r1', 'a1'] },
          'turn-2': { turn_id: 'turn-2', status: 'running', items: ['r2', 'a2'] },
        },
        item_order: ['r1', 'a1', 'r2', 'a2'],
        items: {
          r1: { item_id: 'r1', turn_id: 'turn-1', kind: 'thinking', status: 'completed', payload: { type: 'reasoning', content: '第一轮过程' } },
          a1: { item_id: 'a1', turn_id: 'turn-1', kind: 'message', status: 'completed', payload: { type: 'agentMessage', content: '第一轮的结论。' } },
          r2: { item_id: 'r2', turn_id: 'turn-2', kind: 'thinking', status: 'running', payload: { type: 'reasoning', content: '第二轮过程' } },
          a2: { item_id: 'a2', turn_id: 'turn-2', kind: 'message', status: 'running', payload: { type: 'agentMessage', content: '第二轮的回复。' } },
        },
        requests: {},
        artifacts: {},
      },
    })

    const messages = selectCoreWorkbenchMessages(snapshot)
    const systemRow = messages.find(message => message.id === 'turn-2:system')
    expect(systemRow?.metadata?.systemEvent).toMatchObject({ kind: 'member_wake' })
    const first = messages.find(message => message.id === 'assistant:turn-1')
    expect(first?.answerText).toBe('第一轮的结论。')
    expect((first?.processParts ?? []).map(part => part.id)).not.toContain('a1')
    expect(first?.content).not.toContain('renderer_dev')
  })
})

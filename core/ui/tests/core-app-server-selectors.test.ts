import { describe, expect, it } from 'vitest'
import { hydrateSnapshot, selectChatMessages, selectLatestTurnStatus } from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer'

describe('core appServer selectors', () => {
  it('migrates legacy compaction limits without exposing the retired target field', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 2,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 2,
        status: 'completed',
        item_order: ['compact-1'],
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['compact-1'] },
        },
        items: {
          'compact-1': {
            item_id: 'compact-1',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: {
              type: 'compaction',
              compaction_status: 'compacted',
              content: '[Compacted Context]\n- Continue.',
              target_tokens: 1200,
            },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const item = selectChatMessages(snapshot)[0]?.parts[0]

    expect(item?.limit_tokens).toBe(1200)
    expect(item).not.toHaveProperty('target_tokens')
  })

  it('projects a running Core live snapshot into user and assistant waiting messages', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 3,
      status: 'running',
      item_order: ['user-1'],
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['user-1'],
          input: [{ type: 'text', text: '写一个文档' }],
        },
      },
      items: {
        'user-1': {
          item_id: 'user-1',
          turn_id: 'turn-1',
          type: 'userMessage',
          status: 'completed',
          content: [{ type: 'text', text: '写一个文档' }],
          seq: 2,
        },
      },
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 3,
        status: 'running',
        item_order: ['running-1'],
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'running',
            items: ['running-1'],
          },
        },
        items: {
          'running-1': {
            item_id: 'running-1',
            turn_id: 'turn-1',
            kind: 'status',
            status: 'running',
            payload: { type: 'status', content: 'running' },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)

    expect(selectLatestTurnStatus(snapshot)).toBe('running')
    expect(messages).toMatchObject([
      { id: 'user-1', role: 'user', content: '写一个文档' },
      {
        id: 'assistant:turn-1',
        role: 'assistant',
        parts: [{ item_id: 'running-1', type: 'status', status: 'running' }],
      },
    ])
  })

  it('uses the latest completed agent message as assistant text', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 5,
      status: 'completed',
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 5,
        status: 'completed',
        item_order: ['reason-1', 'tool-1', 'text-1'],
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'completed',
            items: ['reason-1', 'tool-1', 'text-1'],
          },
        },
        items: {
          'reason-1': {
            item_id: 'reason-1',
            turn_id: 'turn-1',
            kind: 'thinking',
            status: 'completed',
            payload: { type: 'reasoning', content: '先思考' },
          },
          'tool-1': {
            item_id: 'tool-1',
            turn_id: 'turn-1',
            kind: 'tool_call',
            status: 'completed',
            payload: {
              type: 'dynamicToolCall',
              tool_name: 'write_file',
              arguments: { path: 'demo.md' },
            },
          },
          'text-1': {
            item_id: 'text-1',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'agentMessage', content: '已完成' },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)

    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({
      id: 'assistant:turn-1',
      role: 'assistant',
      content: '已完成',
      parts: [
        { item_id: 'reason-1', type: 'reasoning', content: '先思考' },
        { item_id: 'tool-1', type: 'dynamicToolCall', tool_name: 'write_file' },
      ],
    })
  })

  it('does not promote a JSON-RPC envelope into visible assistant text', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 2,
      status: 'completed',
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 2,
        status: 'completed',
        item_order: ['reason-1', 'protocol-1'],
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['reason-1', 'protocol-1'] },
        },
        items: {
          'reason-1': {
            item_id: 'reason-1', turn_id: 'turn-1', kind: 'thinking', status: 'completed',
            payload: { type: 'reasoning', content: '先思考' },
          },
          'protocol-1': {
            item_id: 'protocol-1', turn_id: 'turn-1', kind: 'message', status: 'completed',
            payload: {
              type: 'agentMessage',
              content: JSON.stringify({ jsonrpc: '2.0', method: 'runtime.done', params: { finish_reason: 'stop' } }),
            },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    expect(selectChatMessages(snapshot)).toMatchObject([
      { role: 'assistant', content: '', parts: [{ type: 'reasoning', content: '先思考' }] },
    ])
  })

  it('keeps ordinary JSON documents as assistant text', () => {
    const content = JSON.stringify({ title: 'example', lines: ['one', 'two'] })
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1', snapshot_seq: 1, status: 'completed',
      core: {
        thread_id: 'thread-1', snapshot_seq: 1, status: 'completed', item_order: ['text-1'],
        turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['text-1'] } },
        items: {
          'text-1': {
            item_id: 'text-1', turn_id: 'turn-1', kind: 'message', status: 'completed',
            payload: { type: 'agentMessage', content },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    expect(selectChatMessages(snapshot)[0]?.content).toBe(content)
  })

  it('keeps an assistant-only approval continuation after its originating user turn', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 1578,
      status: 'completed',
      item_order: ['turn-initial:user', 'turn-edit:user'],
      turns: {
        'turn-initial': { turn_id: 'turn-initial', status: 'completed', items: ['turn-initial:user'] },
        'turn-edit': { turn_id: 'turn-edit', status: 'completed', items: ['turn-edit:user'] },
      },
      items: {
        'turn-initial:user': {
          item_id: 'turn-initial:user', turn_id: 'turn-initial', type: 'userMessage', status: 'completed',
          content: [{ type: 'text', text: '写一个小说开头' }], seq: 2,
        },
        'turn-edit:user': {
          item_id: 'turn-edit:user', turn_id: 'turn-edit', type: 'userMessage', status: 'completed',
          content: [{ type: 'text', text: '续写一段' }], seq: 877,
        },
      },
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 1578,
        status: 'completed',
        item_order: ['initial:text', 'edit:read', 'edit:write', 'approval-continuation:text'],
        turns: {
          'turn-initial': { turn_id: 'turn-initial', status: 'completed', items: ['initial:text'] },
          'turn-edit': { turn_id: 'turn-edit', status: 'completed', items: ['edit:read', 'edit:write'] },
          'turn-approval-continuation': {
            turn_id: 'turn-approval-continuation', status: 'completed', items: ['approval-continuation:text'],
          },
        },
        items: {
          'initial:text': {
            item_id: 'initial:text', turn_id: 'turn-initial', kind: 'message', status: 'completed',
            payload: { type: 'agentMessage', content: '小说开头已完成' }, seq: 1,
          },
          'edit:read': {
            item_id: 'edit:read', turn_id: 'turn-edit', kind: 'tool_call', status: 'completed',
            payload: { type: 'dynamicToolCall', tool_name: 'read_file' }, seq: 1,
          },
          'edit:write': {
            item_id: 'edit:write', turn_id: 'turn-edit', kind: 'tool_call', status: 'completed',
            payload: { type: 'dynamicToolCall', tool_name: 'edit_file' }, seq: 2,
          },
          'approval-continuation:text': {
            item_id: 'approval-continuation:text', turn_id: 'turn-approval-continuation', kind: 'message', status: 'completed',
            payload: { type: 'agentMessage', content: '续写已完成' }, seq: 174,
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)

    expect(messages.map(({ id, role, content }) => ({ id, role, content }))).toEqual([
      { id: 'turn-initial:user', role: 'user', content: '写一个小说开头' },
      { id: 'assistant:turn-initial', role: 'assistant', content: '小说开头已完成' },
      { id: 'turn-edit:user', role: 'user', content: '续写一段' },
      { id: 'assistant:turn-edit', role: 'assistant', content: '' },
      { id: 'assistant:turn-approval-continuation', role: 'assistant', content: '续写已完成' },
    ])
    expect(messages[3]?.parts.map((part) => part.tool_name)).toEqual(['read_file', 'edit_file'])
  })
})

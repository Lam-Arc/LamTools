import { describe, expect, it } from 'vitest'
import { hydrateSnapshot, selectChatMessages, selectLatestTurnStatus } from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer'

describe('core appServer selectors', () => {
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
})

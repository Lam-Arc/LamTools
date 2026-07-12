import { describe, expect, it } from 'vitest'
import {
  hydrateSnapshot,
  coreMessageHasProcessParts,
  normalizeCoreSessionStatus,
  nextCoreProcessExpandedIds,
  selectCoreQueuedInputs,
  selectCoreWorkbenchMessages,
  selectLatestActiveTurnId,
  updateCoreSessionListStatus,
} from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer'

describe('core appServer workbench projection', () => {
  it('projects snapshot messages into CoreMessage rows with parts and attachment parts', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 6,
      status: 'running',
      item_order: ['user-1'],
      items: {
        'user-1': {
          item_id: 'user-1',
          turn_id: 'turn-1',
          type: 'userMessage',
          status: 'completed',
          content: [
            { type: 'text', text: 'read this' },
            {
              type: 'attachment',
              attachment_id: 'att-1',
              filename: 'note.md',
              mime_type: 'text/markdown',
              preview_type: 'text',
              size: 42,
            },
          ],
        },
      },
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 6,
        status: 'running',
        item_order: ['tool-1'],
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'running',
            items: ['tool-1'],
          },
        },
        items: {
          'tool-1': {
            item_id: 'tool-1',
            turn_id: 'turn-1',
            kind: 'tool_call',
            status: 'running',
            payload: {
              type: 'dynamicToolCall',
              tool_name: 'write_file',
              arguments: { path: 'demo.md' },
            },
          },
        },
        requests: {},
      },
    } satisfies CoreAppSnapshot)

    const messages = selectCoreWorkbenchMessages(snapshot, {
      source: 'core_app_server',
      active: true,
      shallowThinkingPending: true,
    })

    expect(messages).toMatchObject([
      {
        id: 'user-1',
        role: 'user',
        content: 'read this',
        parts: [
          {
            id: 'user-1:attachment:att-1',
            partType: 'attachment',
            status: 'completed',
            label: 'note.md',
          },
        ],
      },
      {
        id: 'assistant:turn-1',
        role: 'assistant',
        metadata: {
          source: 'core_app_server',
          shallowThinkingPending: true,
        },
        parts: [
          {
            id: 'tool-1',
            partType: 'tool_call',
            status: 'running',
            toolName: 'write_file',
          },
        ],
      },
    ])
  })

  it('projects queue tray items and latest active turn from a snapshot', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 9,
      queue: [
        {
          queue_item_id: 'queue-2',
          seq: 8,
          status: 'queued',
          mode: 'next_turn',
          input: [{ type: 'text', text: 'second' }],
        },
        {
          queue_item_id: 'queue-1',
          seq: 7,
          status: 'queued',
          mode: 'next_turn',
          input: [
            { type: 'skill', name: 'review', source_text: '/review' },
            { type: 'text', text: ' first' },
          ],
        },
      ],
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 9,
        status: 'running',
        turns: {
          'turn-old': { turn_id: 'turn-old', status: 'completed', last_seq: 2 },
          'turn-active': { turn_id: 'turn-active', status: 'waiting', last_seq: 6 },
        },
        items: {},
        item_order: [],
      },
    } satisfies CoreAppSnapshot)

    expect(selectLatestActiveTurnId(snapshot)).toBe('turn-active')
    expect(selectCoreQueuedInputs(snapshot)).toMatchObject([
      { id: 'queue-1', text: '/review first', position: 1, status: 'queued' },
      { id: 'queue-2', text: 'second', position: 2, status: 'queued' },
    ])
  })

  it('plans live process expansion for active assistant messages with process parts', () => {
    const current = new Set(['manual'])
    const expanded = nextCoreProcessExpandedIds([
      {
        id: 'assistant-1',
        role: 'assistant',
        content: '',
        timestamp: '',
        parts: [
          { id: 'text-1', partType: 'model_text', status: 'completed', content: 'answer' },
        ],
      },
      {
        id: 'assistant-2',
        role: 'assistant',
        content: '',
        timestamp: '',
        parts: [
          { id: 'tool-1', partType: 'tool_call', status: 'running', content: '', toolName: 'write_file' },
        ],
      },
      {
        id: 'user-1',
        role: 'user',
        content: 'hello',
        timestamp: '',
        parts: [
          { id: 'tool-user', partType: 'tool_call', status: 'running', content: '' },
        ],
      },
    ], current, true)

    expect(coreMessageHasProcessParts({
      id: 'assistant-1',
      role: 'assistant',
      content: '',
      timestamp: '',
      parts: [{ id: 'text-1', partType: 'model_text', status: 'completed', content: 'answer' }],
    })).toBe(false)
    expect([...expanded].sort()).toEqual(['assistant-2', 'manual'])
    expect(nextCoreProcessExpandedIds([], current, false)).toBe(current)
  })

  it('normalizes and updates only the active Core session list item', () => {
    const sessions = [
      { id: 'session-active', title: 'Active', status: 'idle', updatedAt: 'before' },
      { id: 'session-other', title: 'Other', status: 'running', updatedAt: 'unchanged' },
    ]

    const updated = updateCoreSessionListStatus(
      sessions,
      'session-active',
      'waiting',
      '2026-07-10T00:00:00.000Z',
    )

    expect(normalizeCoreSessionStatus('ACTIVE')).toBe('idle')
    expect(normalizeCoreSessionStatus('unknown')).toBe('idle')
    expect(updated).toEqual([
      { id: 'session-active', title: 'Active', status: 'waiting', updatedAt: '2026-07-10T00:00:00.000Z' },
      { id: 'session-other', title: 'Other', status: 'running', updatedAt: 'unchanged' },
    ])
    expect(updated).not.toBe(sessions)
    expect(updated[1]).toBe(sessions[1])
    expect(updateCoreSessionListStatus(updated, 'missing', 'running', 'later')).toBe(updated)
  })
})

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
  it('preserves canonical compaction state and progress metadata through the workbench projection', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 4,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 4,
        status: 'running',
        item_order: ['compact-1'],
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'running', items: ['compact-1'] },
        },
        items: {
          'compact-1': {
            item_id: 'compact-1',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: {
              type: 'compaction',
              compaction_status: 'not_needed',
              reason: 'no_gain',
              phase: 'segment',
              segment: 2,
              segments: 3,
              label: '无需压缩',
              before_tokens: 1800,
              after_tokens: 1800,
              limit_tokens: 1200,
            },
          },
        },
        requests: {},
      },
    } satisfies CoreAppSnapshot)

    const part = selectCoreWorkbenchMessages(snapshot)[0]?.parts[0]

    expect(part).toMatchObject({
      id: 'compact-1',
      partType: 'compaction',
      label: '无需压缩',
      metadata: {
        compaction_status: 'not_needed',
        reason: 'no_gain',
        phase: 'segment',
        segment: 2,
        segments: 3,
        before_tokens: 1800,
        after_tokens: 1800,
        limit_tokens: 1200,
      },
    })
  })

  it('keeps one compaction part id while streamed content grows into the final snapshot', () => {
    const project = (status: 'running' | 'compacted', content: string) => selectCoreWorkbenchMessages(hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: status === 'running' ? 2 : 3,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: status === 'running' ? 2 : 3,
        status: status === 'running' ? 'running' : 'completed',
        item_order: ['compact-1'],
        turns: {
          'turn-1': { turn_id: 'turn-1', status: status === 'running' ? 'running' : 'completed', items: ['compact-1'] },
        },
        items: {
          'compact-1': {
            item_id: 'compact-1',
            turn_id: 'turn-1',
            kind: 'message',
            status: status === 'running' ? 'running' : 'completed',
            content,
            payload: {
              type: 'compaction',
              compaction_status: status,
              content,
              label: status === 'running' ? '正在压缩上下文 · 第 1/2 段' : '上下文已压缩',
              before_tokens: 2400,
              after_tokens: status === 'running' ? 2400 : 900,
              limit_tokens: 1000,
            },
          },
        },
        requests: {},
      },
    } satisfies CoreAppSnapshot))[0]?.parts[0]

    const running = project('running', '')
    const streamed = project('running', '[Compacted Context]\n1. Current Goal')
    const completed = project('compacted', '[Compacted Context]\n1. Current Goal\n- Continue.')

    expect(running).toMatchObject({ id: 'compact-1', status: 'running', content: '' })
    expect(streamed).toMatchObject({ id: 'compact-1', status: 'running' })
    expect(streamed?.content).toContain('Current Goal')
    expect(completed).toMatchObject({ id: 'compact-1', status: 'completed' })
    expect(completed?.metadata).toMatchObject({ compaction_status: 'compacted', after_tokens: 900 })
  })

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

  it('projects shallow thinking markers as a reasoning part instead of visible protocol text', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 3,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 3,
        status: 'completed',
        item_order: ['assistant-1'],
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['assistant-1'] },
        },
        items: {
          'assistant-1': {
            item_id: 'assistant-1',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: {
              type: 'agentMessage',
              content: '[>SHALLOW_thinking_START<]\n[结论]\n先确认需求。\n[>SHALLOW_thinking_END<]\n\n最终正文。',
            },
          },
        },
        requests: {},
      },
    } satisfies CoreAppSnapshot)

    const messages = selectCoreWorkbenchMessages(snapshot)

    expect(messages[0]?.content).toBe('最终正文。')
    expect(messages[0]?.content).not.toContain('SHALLOW_thinking')
    expect(messages[0]?.parts).toContainEqual(expect.objectContaining({
      partType: 'reasoning',
      content: '[结论]\n先确认需求。',
      status: 'completed',
    }))
  })

  it('projects a failed turn status payload as a visible status part', () => {
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 2,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 2,
        status: 'failed',
        item_order: ['turn-1:terminal'],
        turns: {
          'turn-1': { turn_id: 'turn-1', status: 'failed', items: ['turn-1:terminal'] },
        },
        items: {
          'turn-1:terminal': {
            item_id: 'turn-1:terminal',
            turn_id: 'turn-1',
            kind: 'status',
            status: 'failed',
            payload: {
              type: 'turn',
              status: 'failed',
              message: 'Invalid tool message sequence',
            },
          },
        },
        requests: {},
      },
    } satisfies CoreAppSnapshot)

    expect(selectCoreWorkbenchMessages(snapshot)[0]?.parts[0]).toMatchObject({
      partType: 'status',
      status: 'error',
      content: 'Invalid tool message sequence',
    })
  })

  it('nests real child run items under the sub-agent call', () => {
    const parentId = 'thread-1:run-parent:call-sub:tool'
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 12,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 12,
        status: 'completed',
        item_order: [parentId, 'child-reasoning', 'child-write', 'child-text', 'main-text'],
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'completed',
            items: [parentId, 'child-reasoning', 'child-write', 'child-text', 'main-text'],
          },
        },
        items: {
          [parentId]: {
            item_id: parentId,
            turn_id: 'turn-1',
            kind: 'tool_result',
            status: 'completed',
            payload: {
              type: 'dynamicToolCall',
              tool_name: 'sub_agent',
              arguments: { agent: 'writer', task: 'write a story' },
              tool_result: 'Child saved story.txt.',
              metadata: { agent: 'writer', sub_session_id: 'child-session' },
            },
          },
          'child-reasoning': {
            item_id: 'child-reasoning',
            parent_item_id: parentId,
            turn_id: 'turn-1',
            kind: 'thinking',
            status: 'completed',
            payload: { type: 'reasoning', content: 'Plan the delegated write.' },
          },
          'child-write': {
            item_id: 'child-write',
            parent_item_id: parentId,
            turn_id: 'turn-1',
            kind: 'tool_result',
            status: 'completed',
            payload: {
              type: 'dynamicToolCall',
              tool_name: 'write_file',
              arguments: { path: 'story.txt' },
              tool_result: 'Wrote story.txt',
            },
          },
          'child-text': {
            item_id: 'child-text',
            parent_item_id: parentId,
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'agentMessage', content: 'Child saved story.txt.' },
          },
          'main-text': {
            item_id: 'main-text',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'agentMessage', content: 'Main received the child result.' },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectCoreWorkbenchMessages(snapshot)

    expect(messages).toHaveLength(1)
    expect(messages[0]?.content).toBe('Main received the child result.')
    // All agentMessages stay in parts for inline chronological rendering; the
    // last one also folds into content for backward compat
    expect(messages[0]?.parts).toHaveLength(2)
    expect(messages[0]?.parts[0]).toMatchObject({
      id: parentId,
      partType: 'agent_summary',
      toolName: 'sub_agent',
      metadata: {
        subLineParts: [
          { id: 'child-reasoning', partType: 'reasoning', content: 'Plan the delegated write.' },
          { id: 'child-write', partType: 'tool_call', toolName: 'write_file', toolResult: 'Wrote story.txt' },
          { id: 'child-text', partType: 'model_text', content: 'Child saved story.txt.' },
        ],
      },
    })
    expect(messages[0]?.parts[1]).toMatchObject({
      id: 'main-text',
      partType: 'model_text',
      content: 'Main received the child result.',
    })
  })

  it('shows an identical sub-agent handoff only inside the nested child timeline', () => {
    const parentId = 'thread-1:run-parent:call-sub:tool'
    const handoff = '任务已完成。\n\n**文件保存路径：** `story.txt`'
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 20,
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 20,
        status: 'completed',
        item_order: [parentId, 'child-text', 'main-text'],
        turns: {
          'turn-1': {
            turn_id: 'turn-1',
            status: 'completed',
            items: [parentId, 'child-text', 'main-text'],
          },
        },
        items: {
          [parentId]: {
            item_id: parentId,
            turn_id: 'turn-1',
            kind: 'tool_result',
            status: 'completed',
            content: handoff,
            payload: {
              type: 'dynamicToolCall',
              tool_name: 'sub_agent',
              tool_result: handoff,
            },
          },
          'child-text': {
            item_id: 'child-text',
            parent_item_id: parentId,
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'agentMessage', content: handoff },
          },
          'main-text': {
            item_id: 'main-text',
            turn_id: 'turn-1',
            kind: 'message',
            status: 'completed',
            payload: { type: 'agentMessage', content: handoff },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectCoreWorkbenchMessages(snapshot)

    expect(messages).toHaveLength(1)
    expect(messages[0]?.content).toBe('')
    expect(messages[0]?.parts).toHaveLength(1)
    expect(messages[0]?.parts[0]).toMatchObject({
      id: parentId,
      metadata: {
        subLineParts: [
          { id: 'child-text', partType: 'model_text', content: handoff },
        ],
      },
    })
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

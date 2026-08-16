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
    })
    // All renderable items stay in parts (chronological rendering); the
    // agentMessage also accumulates into the assistant text.
    expect(messages[0]?.parts.map((part) => ({
      item_id: part.item_id,
      type: part.type,
      content: part.content,
      tool_name: part.tool_name,
    }))).toEqual([
      { item_id: 'reason-1', type: 'reasoning', content: '先思考', tool_name: undefined },
      { item_id: 'tool-1', type: 'dynamicToolCall', content: undefined, tool_name: 'write_file' },
      { item_id: 'text-1', type: 'agentMessage', content: '已完成', tool_name: undefined },
    ])
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

    const messages = selectChatMessages(snapshot)

    // The envelope must not leak into the visible assistant text, but the
    // raw agentMessage item still stays in parts for chronological rendering.
    expect(messages).toHaveLength(1)
    expect(messages[0]).toMatchObject({ role: 'assistant', content: '' })
    expect(messages[0]?.parts.map((part) => ({ type: part.type, content: part.content }))).toEqual([
      { type: 'reasoning', content: '先思考' },
      {
        type: 'agentMessage',
        content: JSON.stringify({ jsonrpc: '2.0', method: 'runtime.done', params: { finish_reason: 'stop' } }),
      },
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
          // seq anchors are thread-global: user messages precede the runtime
          // items of their turn, and the approval continuation follows them.
          'initial:text': {
            item_id: 'initial:text', turn_id: 'turn-initial', kind: 'message', status: 'completed',
            payload: { type: 'agentMessage', content: '小说开头已完成' }, seq: 10,
          },
          'edit:read': {
            item_id: 'edit:read', turn_id: 'turn-edit', kind: 'tool_call', status: 'completed',
            payload: { type: 'dynamicToolCall', tool_name: 'read_file' }, seq: 878,
          },
          'edit:write': {
            item_id: 'edit:write', turn_id: 'turn-edit', kind: 'tool_call', status: 'completed',
            payload: { type: 'dynamicToolCall', tool_name: 'edit_file' }, seq: 879,
          },
          'approval-continuation:text': {
            item_id: 'approval-continuation:text', turn_id: 'turn-approval-continuation', kind: 'message', status: 'completed',
            payload: { type: 'agentMessage', content: '续写已完成' }, seq: 880,
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

  it('interleaves a mid-turn guide user message at its chronological position', () => {
    // A queue guide (`turn:user:guide:*`) lands mid-turn: its seq sits between
    // the turn's runtime items, so it must render between the two assistant
    // segments instead of above the whole assistant block.
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 10,
      status: 'completed',
      item_order: ['user-1', 'turn-1:user:guide:q1'],
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['user-1', 'turn-1:user:guide:q1'] },
      },
      items: {
        'user-1': {
          item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', status: 'completed',
          content: [{ type: 'text', text: '写一个文档' }], seq: 1,
        },
        'turn-1:user:guide:q1': {
          item_id: 'turn-1:user:guide:q1', turn_id: 'turn-1', type: 'userMessage', status: 'completed',
          content: [{ type: 'text', text: '先做调研' }], seq: 5,
        },
      },
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 10,
        status: 'completed',
        item_order: ['text-1', 'tool-1', 'text-2'],
        turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['text-1', 'tool-1', 'text-2'] } },
        items: {
          'text-1': {
            item_id: 'text-1', turn_id: 'turn-1', kind: 'message', status: 'completed', seq: 2,
            payload: { type: 'agentMessage', content: '开始处理' },
          },
          'tool-1': {
            item_id: 'tool-1', turn_id: 'turn-1', kind: 'tool_call', status: 'completed', seq: 3,
            payload: { type: 'dynamicToolCall', tool_name: 'search' },
          },
          'text-2': {
            item_id: 'text-2', turn_id: 'turn-1', kind: 'message', status: 'completed', seq: 8,
            payload: { type: 'agentMessage', content: '完成' },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)

    expect(messages.map(({ id, role }) => ({ id, role }))).toEqual([
      { id: 'user-1', role: 'user' },
      { id: 'assistant:turn-1', role: 'assistant' },
      { id: 'turn-1:user:guide:q1', role: 'user' },
      { id: 'assistant:turn-1#2', role: 'assistant' },
    ])
    expect(messages[1]?.parts.map((part) => part.tool_name ?? part.type)).toEqual(['agentMessage', 'search'])
    expect(messages[1]?.content).toBe('开始处理')
    expect(messages[3]?.parts.map((part) => part.tool_name ?? part.type)).toEqual(['agentMessage'])
    expect(messages[3]?.content).toBe('完成')
  })

  it('keeps one assistant segment per turn when turn ids contain colons', () => {
    // Real turn ids are `<session>:turn:<run>` (two colons). Segment parsing
    // must not split on those colons — otherwise every runtime item becomes
    // its own assistant message.
    const realTurnId = '2b34c6365779499d91b449d8c1fdb2e5:turn:1f40a07b9825'
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-1',
      snapshot_seq: 5,
      status: 'completed',
      item_order: [`${realTurnId}:user`],
      turns: { [realTurnId]: { turn_id: realTurnId, status: 'completed', items: [`${realTurnId}:user`] } },
      items: {
        [`${realTurnId}:user`]: {
          item_id: `${realTurnId}:user`, turn_id: realTurnId, type: 'userMessage', status: 'completed',
          content: [{ type: 'text', text: '写一个文档' }], seq: 2,
        },
      },
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 5,
        status: 'completed',
        item_order: ['text-1', 'tool-1', 'text-2'],
        turns: { [realTurnId]: { turn_id: realTurnId, status: 'completed', items: ['text-1', 'tool-1', 'text-2'] } },
        items: {
          'text-1': {
            item_id: 'text-1', turn_id: realTurnId, kind: 'message', status: 'completed', seq: 3,
            payload: { type: 'agentMessage', content: '开始' },
          },
          'tool-1': {
            item_id: 'tool-1', turn_id: realTurnId, kind: 'tool_call', status: 'completed', seq: 4,
            payload: { type: 'dynamicToolCall', tool_name: 'search' },
          },
          'text-2': {
            item_id: 'text-2', turn_id: realTurnId, kind: 'message', status: 'completed', seq: 5,
            payload: { type: 'agentMessage', content: '完成' },
          },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)

    expect(messages.map(({ id, role }) => ({ id, role }))).toEqual([
      { id: `${realTurnId}:user`, role: 'user' },
      // All three runtime items belong to ONE assistant message.
      { id: `assistant:${realTurnId}`, role: 'assistant' },
    ])
    expect(messages[1]?.parts.map((part) => part.item_id)).toEqual(['text-1', 'tool-1', 'text-2'])
    expect(messages[1]?.content).toBe('完成')
  })
})

// ── 审批请求快照恢复（ask-user 卡不显示修复）──
// 事件流里 approval_request 的 kind='approval_request'；持久化快照里同一 item
// kind 保持 'tool_call'（后端 _upsert_item 不覆盖既有 kind），只更新
// last_kind / payload.type='serverRequest'。断连重连走快照恢复时必须识别，
// 否则 question/decision_point 等 control tool 不渲染审批卡。
describe('core appServer approval snapshot recovery', () => {
  it('projects a tool_call item with last_kind=approval_request as a decision part', () => {
    const turnId = 'turn-approval'
    const toolItemId = `${turnId}:call_00_abc:tool`
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-approval',
      snapshot_seq: 11,
      core: {
        thread_id: 'thread-approval',
        snapshot_seq: 11,
        status: 'waiting',
        item_order: [`${turnId}:user`, toolItemId],
        turns: {
          [turnId]: {
            turn_id: turnId,
            status: 'waiting',
            last_kind: 'approval_request',
            items: [`${turnId}:user`, toolItemId],
          },
        },
        items: {
          [`${turnId}:user`]: {
            item_id: `${turnId}:user`, turn_id: turnId, kind: 'message', status: 'completed',
            payload: { type: 'userMessage', content: [{ type: 'text', text: '问我一个问题' }] },
          },
          [toolItemId]: {
            item_id: toolItemId,
            turn_id: turnId,
            // 快照持久化后的形态：kind 回落 tool_call，只留 last_kind 与 payload
            kind: 'tool_call',
            last_kind: 'approval_request',
            status: 'waiting',
            payload: {
              type: 'serverRequest',
              request_id: 'req-1',
              tool_name: 'question',
              question: '你希望我做什么？',
              options: [{ id: 'a', label: '选项 A' }],
            },
          },
        },
        requests: {
          'req-1': { request_id: 'req-1', status: 'open', item_id: toolItemId, turn_id: turnId },
        },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)
    const assistant = messages.find((m) => m.role === 'assistant')
    // selectChatMessages 的 parts 是 CoreAppItem（type 字段）；MessagePart 转换在
    // workbenchProjection（coreAppItemToWorkbenchPart），另测。
    const decision = assistant?.parts?.find((part) => part.type === 'serverRequest')

    expect(decision).toBeDefined()
    expect(decision?.tool_name).toBe('question')
    expect(decision?.status).toBe('waiting')
    expect(decision?.request_id).toBe('req-1')
  })

  it('projects an approval_request item by kind (event stream shape) as a decision part', () => {
    const turnId = 'turn-approval-2'
    const toolItemId = `${turnId}:call_00_def:tool`
    const snapshot = hydrateSnapshot({
      thread_id: 'thread-approval-2',
      snapshot_seq: 3,
      core: {
        thread_id: 'thread-approval-2',
        snapshot_seq: 3,
        status: 'waiting',
        item_order: [toolItemId],
        turns: { [turnId]: { turn_id: turnId, status: 'waiting', items: [toolItemId] } },
        items: {
          [toolItemId]: {
            item_id: toolItemId,
            turn_id: turnId,
            kind: 'approval_request',
            status: 'waiting',
            payload: { type: 'serverRequest', request_id: 'req-2', tool_name: 'question' },
          },
        },
        requests: { 'req-2': { request_id: 'req-2', status: 'open', item_id: toolItemId, turn_id: turnId } },
      },
    } satisfies CoreAppSnapshot)

    const messages = selectChatMessages(snapshot)
    const decision = messages.find((m) => m.role === 'assistant')?.parts?.find((part) => part.type === 'serverRequest')

    expect(decision).toBeDefined()
    expect(decision?.status).toBe('waiting')
  })
})

import assert from 'node:assert/strict'
import test from 'node:test'
import { hydrateSnapshot } from '../../src/appServer/snapshot.ts'
import { selectApprovalCards, selectChatMessages, selectLatestTurnStatus, selectQueueTray } from '../../src/appServer/selectors.ts'
import type { WriterAppSnapshot } from '../../src/appServer/protocol.ts'

function snapshot(partial: Partial<WriterAppSnapshot>): WriterAppSnapshot {
  return hydrateSnapshot({
    thread_id: 'thread-1',
    snapshot_seq: 1,
    ...partial,
  })
}

test('selectors expose chat, queue, approval, and status from snapshot state', () => {
  const state = snapshot({
    status: 'waiting',
    turns: { 'turn-1': { turn_id: 'turn-1', status: 'waiting', items: ['user-1', 'tool-1'] } },
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    queue: [{ queue_item_id: 'queue-1', status: 'queued', seq: 5 }],
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'waiting',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'waiting', items: ['tool-1'] },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'approval_request',
          status: 'waiting',
          payload: { type: 'serverRequest', request_id: 'request-1', kind: 'approval' },
        },
      },
      requests: { 'request-1': { request_id: 'request-1', status: 'open', item_id: 'tool-1', turn_id: 'turn-1' } },
      artifacts: {},
    },
  })

  assert.equal(selectLatestTurnStatus(state), 'waiting')
  assert.equal(selectChatMessages(state)[0].content, 'Start')
  assert.equal(selectChatMessages(state)[1].parts[0].item_id, 'tool-1')
  assert.equal(selectQueueTray(state)[0].queue_item_id, 'queue-1')
  assert.equal(selectApprovalCards(state)[0].request_id, 'request-1')
})

test('selectors project user message attachment input into chat metadata', () => {
  const state = snapshot({
    status: 'idle',
    item_order: ['user-1'],
    items: {
      'user-1': {
        item_id: 'user-1',
        turn_id: 'turn-1',
        type: 'userMessage',
        status: 'completed',
        content: [
          { type: 'text', text: '看附件' },
          {
            type: 'attachment',
            attachment_id: 'att-1',
            filename: 'note.md',
            mime_type: 'text/markdown',
            size: 120,
            preview_type: 'text',
          },
        ],
      },
    },
  })

  const [message] = selectChatMessages(state)

  assert.equal(message.content, '看附件')
  assert.equal(message.attachments?.[0].id, 'att-1')
  assert.equal(message.attachments?.[0].filename, 'note.md')
  assert.equal(message.attachments?.[0].preview_type, 'text')
})

test('selectors drop outer runtime projection items', () => {
  const state = snapshot({
    item_order: ['user-1', 'bad-tool', 'tool-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
      'bad-tool': { item_id: 'bad-tool', turn_id: 'turn-1', type: 'tool_call', status: 'running', content: 'runtime.part' },
      'tool-1': { item_id: 'tool-1', turn_id: 'turn-1', type: 'dynamicToolCall', tool_name: 'write_file', status: 'running' },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'running', items: ['tool-1'] },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'tool_call',
          status: 'running',
          payload: { type: 'dynamicToolCall', tool_name: 'write_file' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 2)
  assert.equal(messages[0].content, 'Start')
  assert.equal(messages[1].content, '')
  assert.equal(messages[1].parts.length, 1)
  assert.equal(messages[1].parts[0].item_id, 'tool-1')
})

test('selectors keep model retry status items visible', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'running', items: ['retry-1'] },
      },
      item_order: ['retry-1'],
      items: {
        'retry-1': {
          item_id: 'retry-1',
          turn_id: 'turn-1',
          kind: 'status',
          status: 'running',
          content: '模型请求重试中 (1/9)',
          payload: {
            type: 'status',
            attempt: 1,
            max_retries: 9,
            delay_seconds: 1,
          },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 2)
  assert.equal(messages[1].parts.length, 1)
  assert.equal(messages[1].parts[0].type, 'status')
  assert.equal(messages[1].parts[0].content, '模型请求重试中 (1/9)')
})

test('selectors keep automatic compaction items visible', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'running', items: ['compact-1'] },
      },
      item_order: ['compact-1'],
      items: {
        'compact-1': {
          item_id: 'compact-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          content: '[Compacted Context]\n1. Current Goal\n- Continue.',
          payload: {
            type: 'compaction',
            content: '[Compacted Context]\n1. Current Goal\n- Continue.',
            before_tokens: 1800,
            after_tokens: 1100,
            target_tokens: 1200,
          },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 2)
  assert.equal(messages[1].parts.length, 1)
  assert.equal(messages[1].parts[0].type, 'compaction')
  assert.equal(messages[1].parts[0].content, '[Compacted Context]\n1. Current Goal\n- Continue.')
  assert.equal(messages[1].parts[0].before_tokens, 1800)
  assert.equal(messages[1].parts[0].after_tokens, 1100)
  assert.equal(messages[1].parts[0].limit_tokens, 1200)
  assert.equal('target_tokens' in messages[1].parts[0], false)
})

test('selectors keep manual compact command at the latest position', () => {
  const state = snapshot({
    status: 'completed',
    turns: {
      'turn-1': { turn_id: 'turn-1', status: 'completed', seq: 900, items: ['user-1'] },
      'turn-2': { turn_id: 'turn-2', status: 'completed', seq: 1000, items: ['user-2'] },
    },
    item_order: ['user-1', 'user-2'],
    items: {
      'user-1': {
        item_id: 'user-1',
        turn_id: 'turn-1',
        type: 'userMessage',
        status: 'completed',
        seq: 900,
        content: [{ type: 'text', text: 'Earlier' }],
      },
      'user-2': {
        item_id: 'user-2',
        turn_id: 'turn-2',
        type: 'userMessage',
        status: 'completed',
        seq: 1000,
        content: [{ type: 'text', text: 'Latest before compact' }],
      },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 1443,
      seen_event_ids: ['compact-event'],
      status: 'completed',
      turns: {
        'thread-1:command:compact': {
          turn_id: 'thread-1:command:compact',
          status: 'completed',
          items: ['compact-1'],
          last_seq: 1443,
        },
      },
      item_order: ['compact-1'],
      items: {
        'compact-1': {
          item_id: 'compact-1',
          turn_id: 'thread-1:command:compact',
          kind: 'message',
          status: 'completed',
          last_seq: 1443,
          content: '[Compacted Context]\n1. Current Goal\n- Continue.',
          payload: {
            type: 'contextCompaction',
            content: '[Compacted Context]\n1. Current Goal\n- Continue.',
            compacted_messages: 4,
          },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.at(-1)?.role, 'assistant')
  assert.equal(messages.at(-1)?.parts[0].type, 'contextCompaction')
})

test('selectors show a transient live placeholder before the first assistant item', () => {
  const state = snapshot({
    status: 'running',
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'running', items: [] },
      },
      item_order: [],
      items: {},
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 2)
  assert.equal(messages[0].role, 'user')
  assert.equal(messages[1].role, 'assistant')
  assert.equal(messages[1].metadata?.live, true)
  assert.equal(messages[1].metadata?.initialWaiting, true)
  assert.equal(messages[1].parts.length, 0)
})

test('selectors remove the transient placeholder after the first assistant item', () => {
  const state = snapshot({
    status: 'running',
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'running', items: ['reasoning-1'] },
      },
      item_order: ['reasoning-1'],
      items: {
        'reasoning-1': {
          item_id: 'reasoning-1',
          turn_id: 'turn-1',
          kind: 'thinking',
          status: 'running',
          content: 'Thinking',
          payload: { type: 'reasoning', content: 'Thinking' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 2)
  assert.equal(messages[1].metadata?.initialWaiting, undefined)
  assert.equal(messages[1].parts[0].item_id, 'reasoning-1')
})

test('selectors interleave outer user messages with canonical core replies across turns', () => {
  const state = snapshot({
    status: 'completed',
    turns: {
      'turn-1': { turn_id: 'turn-1', status: 'completed', seq: 99, items: ['user-1'] },
      'turn-2': { turn_id: 'turn-2', status: 'completed', seq: 35, items: ['user-2'] },
    },
    item_order: ['user-1', 'user-2'],
    items: {
      'user-1': {
        item_id: 'user-1',
        turn_id: 'turn-1',
        type: 'userMessage',
        status: 'completed',
        seq: 2,
        content: [{ type: 'text', text: '你好' }],
      },
      'user-2': {
        item_id: 'user-2',
        turn_id: 'turn-2',
        type: 'userMessage',
        status: 'completed',
        seq: 36,
        content: [{ type: 'text', text: '展现你的思维链' }],
      },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'completed',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['reply-1'] },
        'turn-2': { turn_id: 'turn-2', status: 'completed', items: ['reasoning-2', 'reply-2'] },
      },
      item_order: ['reply-1', 'reasoning-2', 'reply-2'],
      items: {
        'reply-1': {
          item_id: 'reply-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          content: '你好！有什么我可以帮你的吗？',
          payload: { type: 'agentMessage' },
        },
        'reasoning-2': {
          item_id: 'reasoning-2',
          turn_id: 'turn-2',
          kind: 'thinking',
          status: 'completed',
          content: '好的，我来透明地展示我的思维过程',
          payload: { type: 'reasoning' },
        },
        'reply-2': {
          item_id: 'reply-2',
          turn_id: 'turn-2',
          kind: 'message',
          status: 'completed',
          content: '我可以给出可检查摘要。',
          payload: { type: 'agentMessage' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.deepEqual(messages.map(message => `${message.role}:${message.content || message.parts[0]?.item_id}`), [
    'user:你好',
    'assistant:你好！有什么我可以帮你的吗？',
    'user:展现你的思维链',
    'assistant:我可以给出可检查摘要。',
  ])
  assert.equal(messages[3].parts[0].item_id, 'reasoning-2')
})

test('resolved server request returns active turn status to running', () => {
  const state = snapshot({
    status: 'running',
    turns: { 'turn-1': { turn_id: 'turn-1', status: 'running', items: ['request-item'] } },
    item_order: ['request-item'],
    items: {
      'request-item': { item_id: 'request-item', turn_id: 'turn-1', type: 'serverRequest', status: 'waiting', request_id: 'request-1' },
    },
    requests: {
      'request-1': { request_id: 'request-1', status: 'resolved', item_id: 'request-item', turn_id: 'turn-1', decision: 'approve_once' },
    },
  })

  assert.equal(selectLatestTurnStatus(state), 'running')
  assert.equal(selectApprovalCards(state)[0].status, 'resolved')
})

test('selectors read completed turn status from canonical core snapshot', () => {
  const state = snapshot({
    status: 'running',
    turns: { 'turn-1': { turn_id: 'turn-1', status: 'running', items: [] } },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-status-1'],
      status: 'completed',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'completed', items: [] },
      },
      item_order: [],
      items: {},
      requests: {},
      artifacts: {},
    },
  })

  assert.equal(selectLatestTurnStatus(state), 'completed')
})

test('selectors read approval cards from canonical core requests', () => {
  const state = snapshot({
    requests: {},
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-request-1'],
      status: 'waiting',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'waiting', items: ['request-item'] },
      },
      item_order: ['request-item'],
      items: {
        'request-item': {
          item_id: 'request-item',
          turn_id: 'turn-1',
          kind: 'approval_request',
          status: 'waiting',
          payload: { type: 'serverRequest', request_id: 'request-1', message: 'Allow command?' },
        },
      },
      requests: {
        'request-1': {
          request_id: 'request-1',
          status: 'open',
          item_id: 'request-item',
          turn_id: 'turn-1',
          message: 'Allow command?',
        },
      },
      artifacts: {},
    },
  })

  assert.equal(selectLatestTurnStatus(state), 'waiting')
  assert.equal(selectApprovalCards(state)[0].request_id, 'request-1')
  assert.equal(selectApprovalCards(state)[0].message, 'Allow command?')
})

test('selectors attach artifacts to their owning process item', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'running', items: ['tool-1'] },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'tool_result',
          status: 'completed',
          payload: { type: 'dynamicToolCall', tool_name: 'write_file' },
        },
      },
      requests: {},
      artifacts: {
        'artifact-1': {
          artifact_id: 'artifact-1',
          item_id: 'tool-1',
          kind: 'file_create',
          name: 'report.md',
          path: 'E:/tmp/report.md',
        },
      },
    },
  })

  const part = selectChatMessages(state)[1].parts[0]

  assert.equal(part.item_id, 'tool-1')
  assert.deepEqual(part.artifacts, [{
    artifact_id: 'artifact-1',
    item_id: 'tool-1',
    kind: 'file_create',
    name: 'report.md',
    path: 'E:/tmp/report.md',
  }])
})

test('selectors ignore outer turn runtime metrics', () => {
  const state = snapshot({
    turns: {
      'turn-1': {
        turn_id: 'turn-1',
        status: 'running',
        items: ['tool-1'],
        runtime_metrics: { input_tokens: 10, output_tokens: 3, total_tokens: 13, cached_tokens: 5, cache_hit_rate: 0.5, llm_calls: 1 },
      },
    },
    item_order: ['tool-1'],
    items: {
      'tool-1': { item_id: 'tool-1', turn_id: 'turn-1', type: 'dynamicToolCall', tool_name: 'shell' },
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 0)
})

test('selectors read process metrics from canonical core usage without outer turn metrics', () => {
  const state = snapshot({
    item_order: ['tool-1'],
    items: {
      'tool-1': { item_id: 'tool-1', turn_id: 'turn-1', type: 'dynamicToolCall', tool_name: 'shell' },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['tool-1'],
          usage: { input_tokens: 12, output_tokens: 4, total_tokens: 16 },
        },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'tool_call',
          status: 'running',
          payload: { type: 'dynamicToolCall', tool_name: 'shell' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const message = selectChatMessages(state)[0]

  assert.deepEqual(message.metadata?.processMetrics, {
    input_tokens: 12,
    output_tokens: 4,
    total_tokens: 16,
  })
})

test('selectors render canonical core tool calls without outer app items', () => {
  const state = snapshot({
    item_order: [],
    items: {},
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['tool-1'],
        },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'tool_call',
          status: 'running',
          payload: {
            type: 'dynamicToolCall',
            tool_name: 'write_file',
            arguments: { path: 'draft.md' },
          },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const part = selectChatMessages(state)[0].parts[0]

  assert.equal(part.type, 'dynamicToolCall')
  assert.equal(part.tool_name, 'write_file')
  assert.deepEqual(part.arguments, { path: 'draft.md' })
})

test('selectors preserve canonical tool input preview payload', () => {
  const state = snapshot({
    item_order: [],
    items: {},
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['tool-1'],
        },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'tool_call',
          status: 'running',
          payload: {
            type: 'dynamicToolCall',
            tool_name: 'write_file',
            arguments: { path: 'draft.md' },
            input_preview: {
              field: 'content',
              content: '<html>',
              chars: 6,
              truncated: false,
            },
          },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const part = selectChatMessages(state)[0].parts[0]

  assert.deepEqual(part.input_preview, {
    field: 'content',
    content: '<html>',
    chars: 6,
    truncated: false,
  })
})

test('selectors promote canonical sub_agent tool items to agent summaries', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Review' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'completed',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'completed',
          items: ['agent-tool-1'],
        },
      },
      item_order: ['agent-tool-1'],
      items: {
        'agent-tool-1': {
          item_id: 'agent-tool-1',
          turn_id: 'turn-1',
          kind: 'tool_result',
          status: 'completed',
          content: '独立复盘完成',
          payload: {
            type: 'dynamicToolCall',
            tool_name: 'sub_agent',
            arguments: { agent: 'retrospective-analyst', task: '复盘失败过程' },
            metadata: {
              agent_index: '001',
              agent_name: 'retrospective_analyst',
              sub_session_id: 'thread-1:sub:001:retrospective_analyst',
              task: '复盘失败过程',
            },
          },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const part = selectChatMessages(state)[1].parts[0]

  assert.equal(part.type, 'agent_summary')
  assert.equal(part.tool_name, 'sub_agent')
  assert.equal(part.content, '独立复盘完成')
  assert.deepEqual(part.arguments, { agent: 'retrospective-analyst', task: '复盘失败过程' })
  assert.deepEqual(part.metadata, {
    agent_index: '001',
    agent_name: 'retrospective_analyst',
    sub_session_id: 'thread-1:sub:001:retrospective_analyst',
    task: '复盘失败过程',
  })
})

test('selectors suppress sub_agent duplicate child output from the main timeline', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Review' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'completed',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'completed',
          items: ['agent-tool-1', 'child-run:stream-fallback', 'child-run:response-0:text', 'main-reply'],
        },
      },
      item_order: ['agent-tool-1', 'child-run:stream-fallback', 'child-run:response-0:text', 'main-reply'],
      items: {
        'agent-tool-1': {
          item_id: 'agent-tool-1',
          turn_id: 'turn-1',
          kind: 'tool_result',
          status: 'completed',
          content: '# 复盘报告\n\n子 agent 的完整结论。',
          payload: {
            type: 'dynamicToolCall',
            tool_name: 'sub_agent',
            arguments: { agent: 'retrospective-analyst', task: '复盘失败过程' },
          },
        },
        'child-run:stream-fallback': {
          item_id: 'child-run:stream-fallback',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'failed',
          content: 'LLM API error 503',
          payload: { type: 'error', content: 'LLM API error 503' },
        },
        'child-run:response-0:text': {
          item_id: 'child-run:response-0:text',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          content: '# 复盘报告\n\n子 agent 的完整结论。',
          payload: { type: 'agentMessage', content: '# 复盘报告\n\n子 agent 的完整结论。' },
        },
        'main-reply': {
          item_id: 'main-reply',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          content: '主 Writer 已完成总结。',
          payload: { type: 'agentMessage', content: '主 Writer 已完成总结。' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const assistant = selectChatMessages(state)[1]

  assert.equal(assistant.content, '主 Writer 已完成总结。')
  assert.deepEqual(assistant.parts.map(part => part.item_id), ['agent-tool-1'])
  assert.equal(assistant.parts[0].type, 'agent_summary')
})

test('selectors render canonical core messages and thinking without outer app items', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 3,
      seen_event_ids: ['core-event-1', 'core-event-2'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['thinking-1', 'agent-1'],
        },
      },
      item_order: ['thinking-1', 'agent-1'],
      items: {
        'thinking-1': {
          item_id: 'thinking-1',
          turn_id: 'turn-1',
          kind: 'thinking',
          status: 'running',
          content: '分析中',
          payload: { type: 'reasoning' },
        },
        'agent-1': {
          item_id: 'agent-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          content: 'core answer',
          payload: { type: 'agentMessage' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages[0].content, 'Start')
  assert.equal(messages[1].content, '')
  assert.equal(messages[1].parts[0].type, 'reasoning')
  assert.equal(messages[1].parts[0].content, '分析中')
  assert.equal(messages[1].parts[1].type, 'agentMessage')
  assert.equal(messages[1].parts[1].content, 'core answer')
})

test('selectors prefer canonical core runtime items over outer app projection items', () => {
  const state = snapshot({
    status: 'running',
    turns: {
      'turn-1': {
        turn_id: 'turn-1',
        status: 'running',
        items: ['user-1', 'agent-1'],
        runtime_metrics: { total_tokens: 1 },
      },
    },
    item_order: ['user-1', 'agent-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
      'agent-1': { item_id: 'agent-1', turn_id: 'turn-1', type: 'agentMessage', content: 'truncated' },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['agent-1'],
          usage: { total_tokens: 42 },
        },
      },
      item_order: ['agent-1'],
      items: {
        'agent-1': {
          item_id: 'agent-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          content: 'complete canonical answer',
          payload: { type: 'agentMessage' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages[0].content, 'Start')
  assert.equal(messages[1].content, '')
  assert.equal(messages[1].parts[0].content, 'complete canonical answer')
  assert.deepEqual(messages[1].metadata?.processMetrics, { total_tokens: 42 })
  assert.equal(selectLatestTurnStatus(state), 'running')
})

test('selectors include canonical core items missing from outer app item order', () => {
  const state = snapshot({
    turns: {
      'turn-1': { turn_id: 'turn-1', status: 'running', items: ['user-1'] },
    },
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['agent-1'],
        },
      },
      item_order: ['agent-1'],
      items: {
        'agent-1': {
          item_id: 'agent-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          content: 'core only response',
          payload: { type: 'agentMessage' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 2)
  assert.equal(messages[0].content, 'Start')
  assert.equal(messages[1].content, '')
  assert.equal(messages[1].parts[0].content, 'core only response')
})

test('selectors only put the final completed agent message in assistant content', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: 'Start' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'completed',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'completed',
          items: ['draft-1', 'retry-1', 'reply-1'],
        },
      },
      item_order: ['draft-1', 'retry-1', 'reply-1'],
      items: {
        'draft-1': {
          item_id: 'draft-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          content: 'intermediate model text',
          payload: { type: 'agentMessage' },
        },
        'retry-1': {
          item_id: 'retry-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          content: '模型请求重试中 (1/9)',
          payload: { type: 'status' },
        },
        'reply-1': {
          item_id: 'reply-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'completed',
          content: 'final answer',
          payload: { type: 'agentMessage' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages[1].content, 'final answer')
  assert.deepEqual(messages[1].parts.map(part => `${part.type}:${part.content}`), [
    'agentMessage:intermediate model text',
    'status:模型请求重试中 (1/9)',
  ])
})

test('selectors treat the last agent message as final when the turn is already completed', () => {
  const state = snapshot({
    item_order: ['user-1'],
    items: {
      'user-1': { item_id: 'user-1', turn_id: 'turn-1', type: 'userMessage', content: [{ type: 'text', text: '你好' }] },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'completed',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'completed',
          items: ['reasoning-1', 'reply-1'],
        },
      },
      item_order: ['reasoning-1', 'reply-1'],
      items: {
        'reasoning-1': {
          item_id: 'reasoning-1',
          turn_id: 'turn-1',
          kind: 'thinking',
          status: 'running',
          content: '用户在打招呼。',
          payload: { type: 'reasoning' },
        },
        'reply-1': {
          item_id: 'reply-1',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          content: '你好！有什么我可以帮你的吗？',
          payload: { type: 'agentMessage' },
        },
      },
      requests: {},
      artifacts: {},
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages[1].content, '你好！有什么我可以帮你的吗？')
  assert.deepEqual(messages[1].parts.map(part => `${part.type}:${part.content}`), [
    'reasoning:用户在打招呼。',
  ])
})

test('selectors attach canonical core artifacts to their owning process item', () => {
  const state = snapshot({
    item_order: ['tool-1'],
    items: {
      'tool-1': { item_id: 'tool-1', turn_id: 'turn-1', type: 'dynamicToolCall', tool_name: 'write_file' },
    },
    core: {
      thread_id: 'thread-1',
      snapshot_seq: 2,
      seen_event_ids: ['core-event-1'],
      status: 'running',
      turns: {
        'turn-1': {
          turn_id: 'turn-1',
          status: 'running',
          items: ['tool-1'],
        },
      },
      item_order: ['tool-1'],
      items: {
        'tool-1': {
          item_id: 'tool-1',
          turn_id: 'turn-1',
          kind: 'tool_result',
          status: 'completed',
          content: 'Created report.md',
          payload: { type: 'dynamicToolCall', tool_name: 'write_file' },
        },
      },
      requests: {},
      artifacts: {
        'artifact-1': {
          artifact_id: 'artifact-1',
          item_id: 'tool-1',
          kind: 'file_create',
          name: 'report.md',
          path: 'E:/tmp/report.md',
        },
      },
    },
  })

  const part = selectChatMessages(state)[0].parts[0]

  assert.equal(part.content, 'Created report.md')
  assert.deepEqual(part.artifacts, [{
    artifact_id: 'artifact-1',
    item_id: 'tool-1',
    kind: 'file_create',
    name: 'report.md',
    path: 'E:/tmp/report.md',
  }])
})

test('selectors ignore outer final runtime metrics', () => {
  const state = snapshot({
    turns: {
      'turn-1': {
        turn_id: 'turn-1',
        status: 'running',
        items: ['tool-1'],
        runtime_metrics: { duration_ms: 12_300, input_tokens: 10, output_tokens: 3, total_tokens: 13, cache_hit_rate: 0.5, llm_calls: 1 },
      },
    },
    item_order: ['tool-1'],
    items: {
      'tool-1': { item_id: 'tool-1', turn_id: 'turn-1', type: 'dynamicToolCall', tool_name: 'shell' },
    },
  })

  const messages = selectChatMessages(state)

  assert.equal(messages.length, 0)
})

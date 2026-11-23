// user:“让「写进会话」真的能看见：补 item 写入端点”+(气泡只从 core.items 组装，
// 只写 messages 表的会话永远是空的。这条用例吃到的是新端点写出的真实行形状：
// kind='message' + payload.type='agentMessage' → selectChatMessages 必须产出助手气泡。)
import { describe, expect, it } from 'vitest'
import { selectChatMessages } from '../src/appServer'
import type { CoreAppSnapshot } from '../src/appServer/protocol'

function emptySnapshot(): CoreAppSnapshot {
  return {
    thread_id: 'session-1',
    snapshot_seq: 7,
    status: 'completed',
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    artifacts: {},
    core: {
      thread_id: 'session-1',
      snapshot_seq: 7,
      seen_event_ids: [],
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
      status: 'completed',
    },
  }
}

/** The row shape POST /api/core/sessions/{id}/items projects into the snapshot. */
function importedSnapshot(text: string): { snapshot: CoreAppSnapshot; itemId: string } {
  const snapshot = emptySnapshot()
  const turnId = 'session-1:turn:import:d504d1aca5cc423b'
  const itemId = `${turnId}:item:2d56d5fd49614d23`
  snapshot.core!.items = {
    [itemId]: {
      item_id: itemId,
      turn_id: turnId,
      parent_item_id: '',
      kind: 'message',
      content: text,
      deltas: [],
      status: 'completed',
      last_kind: 'message',
      last_seq: 6,
      seq: 6,
      payload: {
        type: 'agentMessage',
        content: text,
        metadata: { origin: 'api.items', api_item_kind: 'text' },
      },
    },
  }
  snapshot.core!.item_order = [itemId]
  snapshot.core!.turns = {
    [turnId]: {
      turn_id: turnId,
      status: 'completed',
      items: [itemId],
      last_kind: 'status',
      last_seq: 7,
    },
  }
  return { snapshot, itemId }
}

describe('session items written through the API', () => {
  it('renders the assistant bubble instead of an empty transcript', () => {
    const { snapshot, itemId } = importedSnapshot('验收会话现在有内容了。')
    const messages = selectChatMessages(snapshot)
    expect(messages).toHaveLength(1)
    const [message] = messages
    expect(message.role).toBe('assistant')
    expect(message.content).toBe('验收会话现在有内容了。')
    expect(message.parts.map(part => part.type)).toEqual(['agentMessage'])
    expect(message.parts[0].item_id).toBe(itemId)
  })

  it('keeps markdown fences (chart/mermaid/writing) readable in the bubble', () => {
    const text = ['看看这张图：', '```chart\n{"type":"bar","categories":["A"]}\n```', '```writing{title="草稿"}\n正文\n```'].join('\n\n')
    const messages = selectChatMessages(importedSnapshot(text).snapshot)
    expect(messages[0].content).toContain('```chart')
    expect(messages[0].content).toContain('```writing')
  })

  it('shows nothing for a session that only ever wrote the messages table', () => {
    // 这正是「写得进、看不见」的现场：记录表有行，core.items 空着。
    const snapshot = emptySnapshot()
    expect(selectChatMessages(snapshot)).toEqual([])
  })
})

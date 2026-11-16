import { describe, expect, it } from 'vitest'

import type { CoreAppEvent, CoreAppSnapshot } from '@/appServer/protocol.ts'
import { applyCoreAppEvent } from '@/appServer/store.ts'
import { hydrateSnapshot } from '@/appServer/snapshot.ts'
import { selectCoreWorkbenchMessages } from '@/appServer/workbenchProjection.ts'

/**
 * user:“连纯文本都没有”+(提问组有两种进入前端的路径：逐事件应用与快照恢复。
 * 两条都必须产出 questionGroup 分片，否则刷新后它就从时间线消失。)
 */

const THREAD = 'th'
const ITEM_ID = `${THREAD}:turn-1:call-1:tool:question`

const QUESTIONS = [
  {
    id: 'q1',
    title: '要不要继续？',
    description: '',
    type: 'single',
    required: true,
    options: [
      { label: '继续', description: '' },
      { label: '停止', description: '' },
    ],
    placeholder: '',
  },
]

function summaryOf(snapshot: CoreAppSnapshot) {
  const messages = selectCoreWorkbenchMessages(snapshot)
  const parts = messages.flatMap((message) => message.parts ?? [])
  return parts.map((part) => ({
    type: part.partType,
    content: String(part.content ?? '').slice(0, 24),
    questions: Array.isArray((part.metadata as Record<string, unknown> | undefined)?.questions)
      ? ((part.metadata as Record<string, unknown>).questions as unknown[]).length
      : 'none',
  }))
}

function runItem(
  seq: number,
  kind: string,
  itemId: string,
  body: Record<string, unknown>,
  status = 'completed',
  turnId = 'turn-1',
): CoreAppEvent {
  return {
    event_id: `${THREAD}:${seq}`,
    thread_id: THREAD,
    seq,
    method: 'core/runItem',
    created_at: '',
    payload: {
      kind,
      thread_id: THREAD,
      event_id: `${THREAD}:${seq}`,
      seq,
      turn_id: turnId,
      item_id: itemId,
      status,
      payload: body,
      created_at_ms: 0,
    },
  } as unknown as CoreAppEvent
}

function emptyEventSnapshot(): CoreAppSnapshot {
  return {
    thread_id: THREAD,
    snapshot_seq: 0,
    revision: 0,
    status: 'running',
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    seen_event_ids: [],
  } as CoreAppSnapshot
}

/** The shape the server persists: no top-level ``type``, only payload.type. */
function storedSnapshot(): CoreAppSnapshot {
  const item = {
    item_id: ITEM_ID,
    turn_id: 'turn-1',
    kind: 'message',
    last_kind: 'message',
    status: 'completed',
    content: '需要你回答：1. 要不要继续？',
    payload: {
      type: 'questionGroup',
      content: '需要你回答：1. 要不要继续？',
      question_group_id: 'g1',
      questions: QUESTIONS,
    },
  }
  return hydrateSnapshot({
    thread_id: THREAD,
    snapshot_seq: 1,
    revision: 1,
    status: 'paused',
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    seen_event_ids: [],
    core: {
      thread_id: THREAD,
      snapshot_seq: 1,
      revision: 1,
      status: 'paused',
      turns: {
        'turn-1': { turn_id: 'turn-1', status: 'paused', items: [ITEM_ID], seq: 1 },
      },
      items: { [ITEM_ID]: item },
      item_order: [ITEM_ID],
      requests: {},
      artifacts: {},
      seen_event_ids: [],
    },
  } as unknown as CoreAppSnapshot)
}

describe('question group projection', () => {
  it('keeps the part type and carries the questions (live event path)', () => {
    let snapshot = emptyEventSnapshot()
    snapshot = applyCoreAppEvent(
      snapshot,
      runItem(2, 'message', ITEM_ID, {
        type: 'questionGroup',
        content: '需要你回答：1. 要不要继续？',
        question_group_id: 'g1',
        questions: QUESTIONS,
      }),
    )
    const summary = summaryOf(snapshot)
    expect(summary, `actual: ${JSON.stringify(summary)}`).toEqual([
      { type: 'questionGroup', content: '需要你回答：1. 要不要继续？', questions: 1 },
    ])
  })

  it('survives a server snapshot reload (stored items have no top-level type)', () => {
    const summary = summaryOf(storedSnapshot())
    expect(summary, `actual: ${JSON.stringify(summary)}`).toEqual([
      { type: 'questionGroup', content: '需要你回答：1. 要不要继续？', questions: 1 },
    ])
  })
})

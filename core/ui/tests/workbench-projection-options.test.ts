import { describe, expect, it } from 'vitest'
import { coreAppItemToWorkbenchPart } from '../src/appServer/workbenchProjection.ts'
import type { CoreAppSnapshot } from '../src/appServer/protocol.ts'

describe('decision card options', () => {
  it('reads approval options from the run item payload', () => {
    const snapshot = {
      thread_id: 'thread-1',
      snapshot_seq: 0,
      items: {},
      item_order: [],
      requests: {},
      core: {
        thread_id: 'thread-1',
        snapshot_seq: 0,
        items: {},
        item_order: [],
        requests: {},
        seen_event_ids: [],
      },
    } as unknown as CoreAppSnapshot
    const part = coreAppItemToWorkbenchPart(snapshot, {
      item_id: 'item-1',
      turn_id: 'turn-1',
      kind: 'tool_call',
      status: 'waiting',
      request_id: 'req-1',
      tool_name: 'write_file',
      payload: {
        type: 'serverRequest',
        request_id: 'req-1',
        tool_name: 'write_file',
        message: '需要授权后才能执行工具：write_file',
        options: [
          { id: 'approve', label: '批准执行', response: 'approve' },
          { id: 'deny', label: '拒绝执行', response: 'deny' },
        ],
      },
    } as never)

    expect(part.toolArgs?.options).toEqual([
      { id: 'approve', label: '批准执行', response: 'approve' },
      { id: 'deny', label: '拒绝执行', response: 'deny' },
    ])
    expect(part.metadata?.options).toEqual(part.toolArgs?.options)
  })
})

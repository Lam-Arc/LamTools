import { describe, expect, it } from 'vitest'
import {
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  selectCoreWorkbenchMessagesWindow,
  createCoreWorkbenchProjectionCache,
  type CoreAppServerRuntimeClient,
  type CoreAppEvent,
  type CoreAppSnapshot,
} from '../src/appServer'

const THREAD = 'thread-1'
const TURN = 'turn-1'
const PARENT_RUN = 'run-1'
const PARENT_CALL = 'call-sub-1'
const TOOL_ITEM = `${THREAD}:${PARENT_RUN}:${PARENT_CALL}:tool`
const CHILD_RUN = 'child-run-1'
const CHILD_TEXT_ITEM = `${CHILD_RUN}:response-0:text`

function fakeClient(): CoreAppServerRuntimeClient {
  return {
    async connect() {},
    request: async () => ({ snapshot: snapshot('running') }),
    close() {},
  }
}

function snapshot(status: CoreAppSnapshot['status']): CoreAppSnapshot {
  return {
    thread_id: THREAD,
    snapshot_seq: 1,
    status,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    artifacts: {},
    core: {
      thread_id: THREAD,
      snapshot_seq: 1,
      seen_event_ids: [],
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
      status,
    },
  }
}

function runItemEvent(
  eventId: string,
  kind: string,
  itemId: string,
  payload: Record<string, unknown>,
  extra: Partial<CoreAppEvent> = {},
): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: THREAD,
    seq: 0,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:00Z',
    item_id: itemId,
    turn_id: TURN,
    payload: {
      event_id: eventId,
      thread_id: THREAD,
      item_id: itemId,
      turn_id: TURN,
      kind,
      payload,
      ...extra,
    },
  }
}

function findSubLinePart(message: { parts?: Array<Record<string, unknown>> }) {
  return (message.parts || []).find((part) => {
    const type = part.partType as string
    return type === 'agent_summary' || type === 'sub_line'
  })
}

function isSubLinePart(part: Record<string, unknown>): boolean {
  const type = part.partType as string
  return type === 'agent_summary' || type === 'sub_line'
}

function subLineTexts(part: Record<string, unknown> | undefined): string[] {
  const metadata = (part?.metadata || {}) as Record<string, unknown>
  const parts = Array.isArray(metadata.subLineParts) ? metadata.subLineParts as Array<Record<string, unknown>> : []
  const texts: string[] = []
  const walk = (items: Array<Record<string, unknown>>) => {
    for (const item of items) {
      const content = String(item.content || '')
      if (content) texts.push(content)
      const children = (item.metadata || {}) as Record<string, unknown>
      if (Array.isArray(children.subLineParts)) walk(children.subLineParts as Array<Record<string, unknown>>)
    }
  }
  walk(parts)
  return texts
}

describe('sub-agent streaming through the projection cache', () => {
  it('sub-line body reflects child deltas while the sub_agent tool is still running', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient()
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('http://127.0.0.1:6173', THREAD)

    const flush = () => {
      while (frames.length) frames.shift()!()
    }

    // 1) parent emits sub_agent tool.started (creates the agent_summary card)
    onEvent?.(runItemEvent('evt-tool-started', 'tool_call', TOOL_ITEM, {
      type: 'dynamicToolCall',
      tool_name: 'sub_agent',
      arguments: { task: 'summarize', agent: 'worker' },
      summary: '',
    }, { status: 'running' }))
    flush()

    // 2) child streams reply deltas while its parent tool is still running
    onEvent?.(runItemEvent('evt-delta-1', 'message', CHILD_TEXT_ITEM, {
      type: 'agentMessage', delta: 'Sub ',
    }, { status: 'running', parent_item_id: TOOL_ITEM, seq: 4 }))
    onEvent?.(runItemEvent('evt-delta-2', 'message', CHILD_TEXT_ITEM, {
      type: 'agentMessage', delta: 'agent ',
    }, { status: 'running', parent_item_id: TOOL_ITEM, seq: 5 }))
    onEvent?.(runItemEvent('evt-delta-3', 'message', CHILD_TEXT_ITEM, {
      type: 'agentMessage', delta: 'answer.',
    }, { status: 'running', parent_item_id: TOOL_ITEM, seq: 6 }))
    flush()

    // 3) project with the same cache instance the live app keeps across frames
    const cache = createCoreWorkbenchProjectionCache()
    const projected = selectCoreWorkbenchMessagesWindow(runtime.state!, { tailWindow: 50 }, cache)
    const subPart = projected.messages
      .flatMap((m) => m.parts || [])
      .find(isSubLinePart)
    const texts = subLineTexts(subPart)
    expect(String((subPart || {}).status || '')).toBe('running')
    expect(texts).toContain('Sub agent answer.')

    // 4) more child deltas arrive (same parent tool still running); project
    //    again with the SAME cache instance the live app keeps across frames.
    //    Regression: the part cache keyed on the parent item's own reference
    //    (stable while the child streams) previously froze the sub-line body —
    //    the sub-agent output only appeared after the parent tool finished.
    onEvent?.(runItemEvent('evt-delta-4', 'message', CHILD_TEXT_ITEM, {
      type: 'agentMessage', delta: ' more',
    }, { status: 'running', parent_item_id: TOOL_ITEM, seq: 7 }))
    flush()
    const projected2 = selectCoreWorkbenchMessagesWindow(runtime.state!, { tailWindow: 50 }, cache)
    const subPart2 = projected2.messages
      .flatMap((m) => m.parts || [])
      .find(isSubLinePart)
    const texts2 = subLineTexts(subPart2)
    expect(texts2).toContain('Sub agent answer. more')
  })
})

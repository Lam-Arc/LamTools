import { setTimeout as delay } from 'node:timers/promises'
import { describe, expect, it, vi } from 'vitest'
import {
  CoreSessionStateStore,
  createCoreAppServerRuntimeController,
  createCoreAppServerRuntimeState,
  hydrateSnapshot,
  selectChatMessages,
  selectCoreWorkbenchMessages,
  type CoreAppServerRuntimeClient,
  type CoreAppEvent,
  type CoreAppSnapshot,
} from '../src/appServer'
import { TransportRpcError } from '../src/transport'

describe('core appServer runtime store', () => {
  it('preserves custom snapshot fields through hydrate and history-page merge', async () => {
    interface ExtendedSnapshot extends CoreAppSnapshot {
      extension: { owner: string }
    }
    const initial: ExtendedSnapshot = {
      ...snapshot(2, 'completed'),
      extension: { owner: 'mobile' },
      history_page: {
        char_limit: 200_000,
        character_count: 20,
        item_count: 1,
        total_items: 2,
        has_more: true,
        next_before_seq: 2,
      },
    }
    const hydrated = hydrateSnapshot(initial)
    const owner: string = hydrated.extension.owner
    expect(owner).toBe('mobile')

    const runtime = createCoreAppServerRuntimeState<ExtendedSnapshot>()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method) => method === 'thread/resume'
        ? { snapshot: initial }
        : {}),
    })
    await controller.connect('thread-1')
    const olderPage: ExtendedSnapshot = {
      ...initial,
      extension: { owner: 'older-page' },
      core: {
        ...initial.core!,
        items: {
          'older-item': { item_id: 'older-item', seq: 1, type: 'message', content: 'older' },
        },
        item_order: ['older-item'],
      },
      history_page: {
        char_limit: 200_000,
        character_count: 10,
        item_count: 1,
        total_items: 2,
        has_more: false,
        next_before_seq: null,
      },
    }
    expect(controller.mergeSnapshotPage(olderPage)).toBe(true)
    expect(runtime.state?.extension.owner).toBe('mobile')
    expect(runtime.state?.core?.items?.['older-item']?.content).toBe('older')
  })

  it('applies native run-item deltas in order with one render-frame flush', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runItemDelta('delta-1', 'hel'))
    onEvent?.(runItemDelta('delta-2', 'lo'))

    expect(frames).toHaveLength(1)
    expect(runtime.state?.core?.items?.['response-1']).toBeUndefined()
    frames[0]()
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('hello')
  })

  it('applies a run-item turn terminal state without requiring an item id', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runStatusEvent('done-1', 'completed', undefined, 12_300))
    frames[0]()

    expect(runtime.state?.core?.turns?.['turn-1']?.status).toBe('completed')
    expect(runtime.state?.core?.turns?.['turn-1']?.duration_ms).toBe(12_300)
    expect(runtime.state?.core?.status).toBe('completed')
  })

  it('reports a rejected guide instead of pretending it was accepted', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method) => {
        if (method === 'thread/resume') return { snapshot: snapshot(1, 'running') }
        if (method === 'turn/steer') return { applied: false, reason: 'run_not_active' }
        return {}
      }),
      scheduleFrame: () => undefined,
    })
    await controller.connect('thread-1')

    // 后端明确拒绝（这一轮已经结束）：不能静默当成成功，否则界面会声称"引导已发送"
    await expect(controller.steerTurn('thread-1', 'turn-1', '改成蓝色'))
      .rejects.toThrow('这一轮已经结束，引导没有生效')
  })

  it('does not let an older snapshot or event roll a terminal turn back to running', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: versionedSnapshot(1, 'running', 1) }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.({ ...runStatusEvent('terminal-ordered', 'completed'), revision: 3, seq: 3 })
    onEvent?.({ ...runStatusEvent('stale-running', 'running'), revision: 2, seq: 2 })
    frames[0]()

    expect(runtime.state?.core?.status).toBe('completed')
    expect(runtime.state?.revision).toBe(3)

    controller.hydrate(versionedSnapshot(2, 'running', 2))
    expect(runtime.state?.core?.status).toBe('completed')
    expect(runtime.state?.revision).toBe(3)
  })

  it('applies a terminal event even when its persisted revision is stale', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: versionedSnapshot(8, 'running', 13) }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    // A raced live projection can stamp the final event with an older
    // revision than a later stream item. The terminal event still closes the
    // turn and must not be discarded by the CAS guard.
    onEvent?.({ ...runStatusEvent('terminal-stale-revision', 'completed'), seq: 9, revision: 10 })
    frames[0]()

    expect(runtime.state?.core?.status).toBe('completed')
    expect(runtime.state?.core?.turns?.['turn-1']?.status).toBe('completed')
    expect(runtime.state?.revision).toBe(13)
  })

  it('keeps the newer live turn running after switching away and replaying an older terminal event', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const current = versionedSnapshot(20, 'running', 20)
    current.turns = {
      'turn-1': { turn_id: 'turn-1', status: 'completed', items: [] },
      'turn-2': { turn_id: 'turn-2', status: 'running', items: [] },
    }
    current.core!.turns = {
      'turn-1': { turn_id: 'turn-1', status: 'completed', items: [] },
      'turn-2': { turn_id: 'turn-2', status: 'running', items: ['current-text'] },
    }
    current.core!.items = {
      'current-text': {
        item_id: 'current-text', turn_id: 'turn-2', seq: 19,
        kind: 'message', status: 'completed', content: '正在检查',
        payload: { type: 'agentMessage', content: '正在检查', final_response: false, has_tool_calls: true },
      },
    }
    current.core!.item_order = ['current-text']
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        if (method !== 'thread/resume') return {}
        if (params.thread_id === 'thread-2') return { snapshot: { ...snapshot(1, 'idle'), thread_id: 'thread-2' } }
        return {
          snapshot: current,
          events: [{ ...runStatusEvent('old-terminal-replay', 'completed'), seq: 10, revision: 10 }],
        }
      }),
    })

    await controller.connect('thread-1')
    await controller.switchThread('thread-2')
    await controller.switchThread('thread-1')

    expect(runtime.state?.core?.status).toBe('running')
    expect(runtime.state?.core?.turns?.['turn-2']?.status).toBe('running')
    const live = selectCoreWorkbenchMessages(runtime.state!, { active: true }).find(message => message.id === 'assistant:turn-2')
    expect(live?.metadata?.live).toBe(true)
    expect(live?.content).toBe('')
    expect(live?.processParts?.map(part => part.id)).toContain('current-text')
    expect(live?.answerPart).toBeNull()
  })

  it('refreshes and retries turn/start once with the same idempotency key', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    let turnAttempts = 0
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        calls.push({ method, params })
        if (method === 'thread/resume') return { snapshot: versionedSnapshot(1, 'completed', 1) }
        if (method === 'thread/read') return { snapshot: versionedSnapshot(2, 'completed', 2) }
        if (method === 'turn/start' && turnAttempts++ === 0) {
          throw new TransportRpcError('REVISION_CONFLICT', 'stale', { code: 'REVISION_CONFLICT' })
        }
        return {}
      }),
    })
    await controller.connect('thread-1')
    await controller.startTurn('thread-1', 'hello')

    const turnCalls = calls.filter((call) => call.method === 'turn/start')
    expect(turnCalls).toHaveLength(2)
    expect(turnCalls.map((call) => call.params.expected_revision)).toEqual([1, 2])
    expect(turnCalls[0].params.client_message_id).toBe(turnCalls[1].params.client_message_id)
  })

  it('advances the tracked revision from sync/change so the next command sends a fresh expected_revision', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    const syncChangeSink: { current: ((change: { thread_id?: string; revision?: number }) => void) | null } = {
      current: null,
    }
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: ({ onSyncChange }) => {
        syncChangeSink.current = onSyncChange ?? null
        return fakeClient(async (method, params) => {
          calls.push({ method, params })
          if (method === 'thread/resume') return { snapshot: versionedSnapshot(1, 'completed', 10) }
          return {}
        })
      },
    })
    await controller.connect('thread-1')
    expect(runtime.state?.revision).toBe(10)

    // Persisted run-item notifications carry no revision; the journal
    // sync/change notification is what keeps the CAS token current mid-turn.
    syncChangeSink.current?.({ thread_id: 'thread-1', revision: 42 })
    expect(runtime.state?.revision).toBe(42)

    await controller.executeCommand('thread-1', 'compact')
    const commandCalls = calls.filter((call) => call.method === 'command.execute')
    expect(commandCalls).toHaveLength(1)
    expect(commandCalls[0].params.expected_revision).toBe(42)
  })

  it('refreshes and retries command.execute once after a revision conflict', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    let commandAttempts = 0
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        calls.push({ method, params })
        if (method === 'thread/resume') return { snapshot: versionedSnapshot(1, 'completed', 1) }
        if (method === 'thread/read') return { snapshot: versionedSnapshot(2, 'completed', 2) }
        if (method === 'command.execute' && commandAttempts++ === 0) {
          throw new TransportRpcError('REVISION_CONFLICT', 'stale', { code: 'REVISION_CONFLICT' })
        }
        return {}
      }),
    })
    await controller.connect('thread-1')
    await controller.executeCommand('thread-1', 'compact')

    const commandCalls = calls.filter((call) => call.method === 'command.execute')
    expect(commandCalls).toHaveLength(2)
    expect(commandCalls.map((call) => call.params.expected_revision)).toEqual([1, 2])
  })

  it('aggregates multiple usage events of one turn instead of overwriting', async () => {
    // A multi-step tool turn emits one usage event per model call; the last
    // event must not clobber earlier per-call counters, and the turn-level
    // cache hit rate is recomputed from the summed totals.
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runUsageEvent('usage-1', {
      input_tokens: 1000,
      output_tokens: 50,
      total_tokens: 1050,
      cached_tokens: 800,
      cache_hit_rate: 0.8,
      llm_calls: 1,
    }))
    onEvent?.(runUsageEvent('usage-2', {
      input_tokens: 2000,
      output_tokens: 100,
      total_tokens: 2100,
      cached_tokens: 100,
      cache_hit_rate: 0.05,
      llm_calls: 1,
    }))
    frames[0]()

    expect(runtime.state?.core?.turns?.['turn-1']?.usage).toMatchObject({
      input_tokens: 3000,
      output_tokens: 150,
      total_tokens: 3150,
      cached_tokens: 900,
      llm_calls: 2,
      cache_hit_rate: 0.3,
    })
  })

  it('stores replace-flagged metrics as context without aggregating turn usage', async () => {
    // `runtime.metrics` items (`replace: true`) carry session-cumulative
    // context state (steps_total), not per-call usage deltas — merging them
    // would inflate llm_calls to a quadratic sum and wipe token accumulations.
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runUsageEvent('usage-1', {
      input_tokens: 1000,
      output_tokens: 50,
      total_tokens: 1050,
      llm_calls: 1,
    }))
    onEvent?.(runMetricsEvent('metrics-1', {
      steps_total: 1,
      context_window_tokens: 128_000,
    }))
    onEvent?.(runUsageEvent('usage-2', {
      input_tokens: 2000,
      output_tokens: 100,
      total_tokens: 2100,
      llm_calls: 1,
    }))
    frames[0]()

    expect(runtime.state?.core?.turns?.['turn-1']?.usage).toMatchObject({
      input_tokens: 3000,
      output_tokens: 150,
      total_tokens: 3150,
      llm_calls: 2,
    })
    expect(runtime.state?.core?.turns?.['turn-1']?.usage).not.toHaveProperty('steps_total')
    expect(runtime.state?.core?.turns?.['turn-1']?.context_metrics).toEqual({
      steps_total: 1,
      context_window_tokens: 128_000,
    })
  })

  it('keeps terminal runtime metrics out of provider usage', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runUsageEvent('usage-1', {
      input_tokens: 100,
      output_tokens: 10,
      total_tokens: 110,
      llm_calls: 1,
      usage_available: true,
    }))
    onEvent?.(runStatusEvent('done-1', 'completed', {
      estimated_prompt_tokens: 6_925,
      context_window_tokens: 50_000,
      steps_total: 1,
    }))
    frames[0]()

    expect(runtime.state?.core?.turns?.['turn-1']?.usage).toMatchObject({
      input_tokens: 100,
      output_tokens: 10,
      total_tokens: 110,
      llm_calls: 1,
    })
    expect(runtime.state?.core?.turns?.['turn-1']?.usage).not.toHaveProperty('estimated_prompt_tokens')
    expect(runtime.state?.core?.turns?.['turn-1']?.context_metrics).toMatchObject({
      estimated_prompt_tokens: 6_925,
      context_window_tokens: 50_000,
    })
  })

  it('uses response snapshots as the authoritative frontend state', () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    controller.applyResponse({ snapshot: snapshot(3, 'idle') })

    expect(runtime.state?.snapshot_seq).toBe(3)
    expect(runtime.state?.status).toBe('idle')
  })

  it('applies response events after hydrating a response snapshot', () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    // The event is newer than the hydrating snapshot (seq 4 > 3): it carries a
    // fact the snapshot cannot contain yet, so it must still be applied.
    controller.applyResponse({
      snapshot: snapshot(3, 'running'),
      events: [{ ...runStatusEvent('terminal-1', 'completed'), seq: 4 }],
    })

    expect(runtime.state?.snapshot_seq).toBe(4)
    expect(runtime.state?.core?.status).toBe('completed')
    expect(runtime.state?.core?.seen_event_ids).toContain('terminal-1')
  })

  it('never re-applies journal catch-up events the resume snapshot already covers', () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })
    // Resume pages the conversation down to the newest turn (snapshot_seq 100)
    // while last_seen_seq 0 re-delivers the journal from the beginning. The
    // paged-out turn below lives at seq 1-3 — the snapshot already reflects
    // it; re-applying it used to materialize the turn as an orphan assistant
    // card appended to the bottom of the thread on every restart.
    const paged = snapshot(100, 'cancelled')
    const core = paged.core!
    core.turns!['turn-new'] = {
      turn_id: 'turn-new',
      status: 'cancelled',
      items: ['turn-new:terminal'],
    }
    core.items!['turn-new:terminal'] = {
      item_id: 'turn-new:terminal',
      turn_id: 'turn-new',
      kind: 'status',
      status: 'cancelled',
      seq: 100,
      payload: { type: 'turn', status: 'cancelled', raw_end_reason: 'user_interrupt', message: '已中断。' },
    }
    core.item_order = ['turn-new:terminal']

    const catchUpEvent = (eventId: string, seq: number, kind: string, status: string, payload: Record<string, unknown>): CoreAppEvent => ({
      event_id: eventId,
      thread_id: 'thread-1',
      seq,
      method: 'core/runItem',
      created_at: '2026-10-11T00:00:00Z',
      turn_id: 'turn-old',
      payload: {
        event_id: eventId,
        thread_id: 'thread-1',
        turn_id: 'turn-old',
        kind,
        status,
        payload,
      },
    })
    controller.applyResponse({
      snapshot: paged,
      events: [
        catchUpEvent('old-1', 1, 'status', 'running', { type: 'turn', status: 'running' }),
        catchUpEvent('old-2', 2, 'tool_call', 'running', { type: 'dynamicToolCall', tool_name: 'run_command' }),
        catchUpEvent('old-3', 3, 'status', 'cancelled', { type: 'turn', status: 'cancelled', raw_end_reason: 'unexpected_shutdown', message: '已中断。' }),
      ],
    })

    const messages = selectChatMessages(runtime.state!)
    expect(messages.some(message => String(message.id).includes('turn-old'))).toBe(false)
    expect(runtime.state?.core?.turns?.['turn-old']).toBeUndefined()
  })

  it('transports text, structured input items, and command operations', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown>; timeoutMs?: number }> = []
    runtime.client = fakeClient(async (method, params, timeoutMs) => {
      calls.push({ method, params, timeoutMs })
      if (method === 'command.catalog') return {
        commands: [{ name: 'compact', action: 'run_action', kind: 'action', accepts_args: false }],
      }
      if (method === 'command.execute') return { result: { status: 'compacted' }, snapshot: snapshot(2, 'idle') }
      if (method === 'queue/guide') return { applied: true, reason: '', snapshot: snapshot(3, 'running') }
      return { snapshot: snapshot(1, 'running') }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.startTurn('thread-1', [
      { type: 'text', text: '请 ' },
      { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
    ])
    const commands = await controller.listCommands('E:\\LamTools')
    const result = await controller.executeCommand('thread-1', 'compact', 'E:\\LamTools', '创建发布计划')
    const guided = await controller.guideQueueInput('thread-1', 'turn-1', 'queue-1', 'updated guidance')

    expect(calls[0].method).toBe('turn/start')
    expect(calls[0].params.input).toEqual([
      { type: 'text', text: '请 ' },
      { type: 'skill', name: 'reviewer', source_text: '/reviewer' },
    ])
    expect(commands).toEqual([{ name: 'compact', action: 'run_action', kind: 'action', accepts_args: false }])
    expect(result).toEqual({ status: 'compacted' })
    expect(calls[2]).toEqual({
      method: 'command.execute',
      timeoutMs: 30 * 60_000,
      params: {
        thread_id: 'thread-1',
        command: 'compact',
        arguments: '创建发布计划',
        work_root: 'E:\\LamTools',
        expected_revision: 0,
      },
    })
    expect(guided).toEqual({ applied: true, reason: '' })
    expect(calls[3]).toMatchObject({
      method: 'queue/guide',
      params: {
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        queue_item_id: 'queue-1',
        client_message_id: 'queue-guide:queue-1',
        text: 'updated guidance',
      },
    })
    expect(runtime.state?.snapshot_seq).toBe(3)
  })

  it('responds through the explicit approval operation with the logical request id', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    runtime.client = fakeClient(async (method, params) => {
      calls.push({ method, params })
      return { snapshot: snapshot(4, 'running') }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.respondApproval('functions.write_file:0', 'approve_once', '')

    expect(calls).toEqual([
      {
        method: 'approval/respond',
        // thread_id is sent explicitly since P0-3 (backend binds approval
        // responses to the subscribed thread).
        params: {
          thread_id: runtime.activeThreadId,
          request_id: 'functions.write_file:0',
          decision: 'approve_once',
          guidance: '',
          expected_revision: 0,
        },
      },
    ])
    expect(runtime.state?.snapshot_seq).toBe(4)
  })

  it('interrupts without requesting a potentially large thread snapshot', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    runtime.client = fakeClient(async (method, params) => {
      calls.push({ method, params })
      return { events: [] }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.interruptTurn('thread-large', 'turn-active')

    expect(calls).toEqual([{
      method: 'turn/interrupt',
      params: {
        thread_id: 'thread-large',
        turn_id: 'turn-active',
        include_snapshot: false,
        expected_revision: 0,
      },
    }])
  })

  it('force-resets a stuck turn with a fresh snapshot applied', async () => {
    // Audit 21 S2: the force-reset escape hatch had zero coverage. It must
    // send turn/force_reset (with include_snapshot) and apply the returned
    // snapshot to the runtime state.
    const runtime = createCoreAppServerRuntimeState()
    const calls: Array<{ method: string; params: Record<string, unknown> }> = []
    runtime.client = fakeClient(async (method, params) => {
      calls.push({ method, params })
      return { snapshot: snapshot(7, 'idle') }
    })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    await controller.forceResetTurn('thread-stuck', 'turn-stuck')

    expect(calls).toEqual([{
      method: 'turn/force_reset',
      params: {
        thread_id: 'thread-stuck',
        turn_id: 'turn-stuck',
        include_snapshot: true,
        expected_revision: 0,
      },
    }])
    expect(runtime.state?.core?.status).toBe('idle')
    expect(runtime.state?.snapshot_seq).toBe(7)
  })

  it('reconnects after socket close and resumes from last snapshot sequence', async () => {
    const runtime = createCoreAppServerRuntimeState<CoreAppSnapshot, ReconnectingClient>()
    ReconnectingClient.instances = []
    ReconnectingClient.requests = []
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: ({ onSnapshot, onConnectionState }) => new ReconnectingClient(onSnapshot, onConnectionState),
      reconnectBaseMs: 25,
      reconnectMaxMs: 2_000,
    })

    await controller.connect('thread-1')
    expect(runtime.state?.snapshot_seq).toBe(8)

    ReconnectingClient.instances[0].close()
    await delay(80)

    expect(ReconnectingClient.instances.length).toBeGreaterThanOrEqual(2)
    const resumes = ReconnectingClient.requests.filter((request) => request.method === 'thread/resume')
    expect(resumes).toHaveLength(2)
    expect(resumes[1].params.last_seen_seq).toBe(8)
    expect(runtime.state?.snapshot_seq).toBe(12)
  })

  it('skips hydrating a snapshot that carries nothing new', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    controller.hydrate(initial)
    expect(runtime.state?.snapshot_seq).toBe(1)

    // Newer seq, but every event is already seen and no derived state
    // (requests / queue / status / items) differs — the state must NOT be
    // replaced (that would bust projection caches and force a full re-render).
    const redundant = snapshot(5, 'running')
    redundant.seen_event_ids = ['e1']
    controller.hydrate(redundant)
    expect(runtime.state?.snapshot_seq).toBe(1)
  })

  it('advances the revision in place when only the CAS revision is newer', async () => {
    // 内容与已收事件都一样、只有 revision 更新（例如远端改了队列）：必须只推进
    // 版本号，不能把整批 item 换成新对象——item 身份是投影缓存的键
    // （2026-09-25 审计 P2）。
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    initial.revision = 3
    controller.hydrate(initial)
    const itemsBefore = runtime.state?.core?.items

    const redundant = snapshot(1, 'running')
    redundant.seen_event_ids = ['e1']
    redundant.revision = 4
    controller.hydrate(redundant)

    expect(runtime.state?.revision).toBe(4)
    expect(runtime.state?.core?.items).toBe(itemsBefore)
  })

  it('hydrates when the snapshot contains events not seen on the wire', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    controller.hydrate(initial)

    const missed = snapshot(5, 'running')
    missed.seen_event_ids = ['e1', 'e2']
    controller.hydrate(missed)
    expect(runtime.state?.snapshot_seq).toBe(5)
  })

  it('skips a snapshot whose events were all received on the wire mid-session', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runItemDelta('wire-1', 'hel'))

    const redundant = snapshot(5, 'running')
    redundant.seen_event_ids = ['wire-1']
    controller.hydrate(redundant)
    expect(runtime.state?.snapshot_seq).toBe(1)
  })

  it('hydrates when approval request states changed', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const initial = snapshot(1, 'running')
    initial.seen_event_ids = ['e1']
    controller.hydrate(initial)

    const withDecision = snapshot(5, 'running')
    withDecision.seen_event_ids = ['e1']
    withDecision.requests = {
      'functions.write_file:0': {
        request_id: 'functions.write_file:0',
        status: 'resolved',
        decision: 'approve_once',
      },
    }
    controller.hydrate(withDecision)
    expect(runtime.state?.snapshot_seq).toBe(5)
    expect(runtime.state?.requests?.['functions.write_file:0']?.status).toBe('resolved')
  })

  it('merges tool_result artifacts from the runItem top level into chat parts', async () => {
    // RunItemEvent serializes artifacts OUTSIDE payload (run_item.py to_dict);
    // the store must merge value.artifacts so image cards render from the
    // event stream without waiting for the turn-boundary snapshot.
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.(runItemToolResult('tr-1', 'img-1'))
    frames[0]()

    // Artifacts merged into the snapshot-level core artifacts map.
    expect(runtime.state?.core?.artifacts?.['art-1']?.uri).toBe('.lam/artifacts/images/x.png')

    // Chat parts carry artifacts (image preview rendering prerequisite).
    const messages = selectChatMessages(runtime.state!)
    // CoreAppItem's index signature types artifacts as unknown; cast to the
    // artifact-array shape for the predicate and the assertions below.
    const part = messages
      .flatMap((message) => message.parts)
      .find((p) => (p.artifacts as Array<Record<string, unknown>> | undefined)?.length) as
      | { artifacts?: Array<Record<string, unknown>> }
      | undefined
    expect(part?.artifacts).toHaveLength(1)
    expect(part?.artifacts?.[0]?.kind).toBe('image')
    expect(part?.artifacts?.[0]?.artifact_id).toBe('art-1')
  })

  it('keeps a terminal failure explanation and closes the leftovers', async () => {
    // 2026-10-10：内存不足把会话打断在"写终态"这一步，界面就一直停在运行中。
    // 服务端把失败原因放在终态项的 payload 里，实时路径也必须留下它，而且必须
    // 把悬挂的工具项收掉——否则用户看到的永远是"正在创建文件…"。
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    // A tool call left mid-flight when the machine ran out of memory.
    onEvent?.({
      event_id: 'tool-running',
      thread_id: 'thread-1',
      seq: 2,
      method: 'core/runItem',
      created_at: '2026-07-15T00:00:01Z',
      turn_id: 'turn-1',
      item_id: 'turn-1:tool:write_file',
      payload: {
        event_id: 'tool-running',
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        item_id: 'turn-1:tool:write_file',
        kind: 'tool_call',
        status: 'running',
        payload: { type: 'dynamicToolCall', tool_name: 'write_file' },
      },
    } as CoreAppEvent)
    frames[0]()

    const explanation = '本机内存不足，本轮已中断。可用内存（物理内存 + 页面文件）大于 4 GB 时 Sunday 会自动继续。'
    onEvent?.({
      event_id: 'oom-terminal',
      thread_id: 'thread-1',
      seq: 3,
      method: 'core/runItem',
      created_at: '2026-07-15T00:00:02Z',
      turn_id: 'turn-1',
      item_id: 'turn-1:terminal',
      payload: {
        event_id: 'oom-terminal',
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        item_id: 'turn-1:terminal',
        kind: 'status',
        status: 'failed',
        payload: {
          type: 'turn',
          status: 'failed',
          raw_end_reason: 'host_memory_exhausted',
          message: explanation,
        },
      },
    } as CoreAppEvent)
    frames[1]()

    // The turn is terminal, the terminal item carries the reason…
    expect(runtime.state?.core?.turns?.['turn-1']?.status).toBe('failed')
    const terminal = runtime.state?.core?.items?.['turn-1:terminal']
    expect(terminal?.status).toBe('failed')
    expect(terminal?.payload?.raw_end_reason).toBe('host_memory_exhausted')
    expect(terminal?.payload?.message).toBe(explanation)
    expect(runtime.state?.core?.turns?.['turn-1']?.items).toContain('turn-1:terminal')
    // …and nothing is left claiming to be running.
    expect(runtime.state?.core?.items?.['turn-1:tool:write_file']?.status).toBe('failed')

    // What the failure banner reads: a status part in error state whose
    // payload keeps the explanation.
    // What MessageView's failure banner reads: the workbench projection turns
    // the terminal item into a status part in error state, and the explanation
    // reaches the part's own text (terminalErrorText reads detail/content).
    const parts = selectCoreWorkbenchMessages(runtime.state!).flatMap((message) => message.parts ?? [])
    const banner = parts.find((part) => part.partType === 'status' && part.status === 'error')
    expect(banner).toBeDefined()
    expect(String(banner?.detail || banner?.content || '')).toContain('内存不足')
    expect(String(banner?.detail || banner?.content || '')).toContain('4 GB')
  })

  it('does not itemize the final reply of a cleanly finished turn as a status row', async () => {
    // A completed turn's terminal event carries the same fields as a failed
    // one (`raw_end_reason`, plus the final reply text as `message`). The
    // server projection only stores the terminal explanation item for
    // failed/cancelled/error endings; the live path must match, or every
    // clean finish grows a stray "status" row holding the whole reply.
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    const reply = '收工。这一轮把"跳切"那个问题解决掉了，账目如下。'
    onEvent?.({
      event_id: 'final-message',
      thread_id: 'thread-1',
      seq: 2,
      method: 'core/runItem',
      created_at: '2026-07-15T00:00:01Z',
      turn_id: 'turn-1',
      item_id: 'turn-1:response-1:text',
      payload: {
        event_id: 'final-message',
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        item_id: 'turn-1:response-1:text',
        kind: 'message',
        status: 'completed',
        payload: {
          type: 'agentMessage',
          content: reply,
          final_response: true,
          has_tool_calls: false,
        },
      },
    } as CoreAppEvent)
    frames[0]()

    onEvent?.({
      event_id: 'clean-terminal',
      thread_id: 'thread-1',
      seq: 3,
      method: 'core/runItem',
      created_at: '2026-07-15T00:00:02Z',
      turn_id: 'turn-1',
      item_id: 'turn-1:terminal',
      payload: {
        event_id: 'clean-terminal',
        thread_id: 'thread-1',
        turn_id: 'turn-1',
        item_id: 'turn-1:terminal',
        kind: 'status',
        status: 'completed',
        payload: {
          type: 'turn',
          status: 'completed',
          raw_end_reason: 'completed',
          message: reply,
        },
      },
    } as CoreAppEvent)
    frames[1]()

    expect(runtime.state?.core?.turns?.['turn-1']?.status).toBe('completed')
    expect(runtime.state?.core?.items?.['turn-1:terminal']).toBeUndefined()
    expect(runtime.state?.core?.turns?.['turn-1']?.items).not.toContain('turn-1:terminal')
    // The reply itself stays an ordinary message item.
    expect(runtime.state?.core?.items?.['turn-1:response-1:text']?.content).toBe(reply)
  })

  it('anchors incremental items on the envelope seq for chronological interleaving', async () => {
    // Mid-turn queue guide messages must interleave between runtime items; the
    // store saves the envelope seq (thread-global) — NOT the batch-relative
    // payload seq — so the selector can order them chronologically.
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    onEvent?.({
      event_id: 'guide-event-1',
      thread_id: 'thread-1',
      seq: 42,
      method: 'item/started',
      created_at: '2026-07-15T00:00:03Z',
      item_id: 'turn-1:user:guide:q1',
      turn_id: 'turn-1',
      payload: {
        type: 'userMessage',
        content: [{ type: 'text', text: '先做调研' }],
        // Deliberately misleading batch-relative seq — must NOT win.
        seq: 0,
      },
    })
    onEvent?.({
      event_id: 'delta-1',
      thread_id: 'thread-1',
      seq: 43,
      method: 'core/runItem',
      created_at: '2026-07-15T00:00:00Z',
      transient: true,
      item_id: 'response-1',
      turn_id: 'turn-1',
      payload: {
        event_id: 'delta-1',
        thread_id: 'thread-1',
        item_id: 'response-1',
        turn_id: 'turn-1',
        kind: 'message',
        status: 'running',
        payload: {
          type: 'agentMessage',
          delta: 'hel',
          // Deliberately misleading batch-relative seq — must NOT become the
          // item's ordering anchor (snapshot_store overrides it with the
          // envelope seq for the same reason).
          seq: 0,
        },
      },
    })
    frames[0]()

    expect(runtime.state?.items?.['turn-1:user:guide:q1']?.seq).toBe(42)
    expect(runtime.state?.core?.items?.['response-1']?.seq).toBe(43)
    // The batch-relative payload seq stays in the payload; the envelope seq
    // is what the selector's chronological interleaving reads.
    expect(runtime.state?.core?.items?.['response-1']?.payload?.seq).toBe(0)
  })

  it('ignores transient envelope seq=0 so stream deltas never sort above the user message', async () => {
    // Transient stream deltas (default_agent `_persist_core_event_live`) are
    // published with seq=0 (no persisted anchor). A 0 anchor would sort the
    // item BEFORE every outer userMessage (0 < any real seq) — the observed
    // "assistant streaming above my message" bug.
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    // 1) First event for a new item is a transient delta (seq=0) — must NOT
    //    anchor the item at 0.
    onEvent?.({
      event_id: 'stream-1', thread_id: 'thread-1', seq: 0, method: 'core/runItem',
      created_at: '2026-07-15T00:00:00Z', transient: true, item_id: 'response-2', turn_id: 'turn-1',
      payload: {
        event_id: 'stream-1', thread_id: 'thread-1', item_id: 'response-2', turn_id: 'turn-1',
        kind: 'message', status: 'running',
        payload: { type: 'agentMessage', delta: 'hi' },
      },
    })
    frames[0]()
    expect(runtime.state?.core?.items?.['response-2']?.seq).toBeUndefined()

    // 2) A later real (persisted) event anchors it with the global seq.
    onEvent?.({
      event_id: 'stream-2', thread_id: 'thread-1', seq: 50, method: 'core/runItem',
      created_at: '2026-07-15T00:00:00Z', item_id: 'response-2', turn_id: 'turn-1',
      payload: {
        event_id: 'stream-2', thread_id: 'thread-1', item_id: 'response-2', turn_id: 'turn-1',
        kind: 'message', status: 'completed',
        payload: { type: 'agentMessage', content: 'hi' },
      },
    })
    frames[0]()
    expect(runtime.state?.core?.items?.['response-2']?.seq).toBe(50)

    // 3) An already-anchored item receiving another transient delta keeps its seq.
    onEvent?.({
      event_id: 'stream-3', thread_id: 'thread-1', seq: 0, method: 'core/runItem',
      created_at: '2026-07-15T00:00:00Z', transient: true, item_id: 'response-2', turn_id: 'turn-1',
      payload: {
        event_id: 'stream-3', thread_id: 'thread-1', item_id: 'response-2', turn_id: 'turn-1',
        kind: 'message', status: 'running',
        payload: { type: 'agentMessage', delta: '!' },
      },
    })
    frames[0]()
    expect(runtime.state?.core?.items?.['response-2']?.seq).toBe(50)
  })

  it('retainOnly keeps the requested thread and evicts every other cached thread', () => {
    const store = new CoreSessionStateStore()
    expect(store.applySnapshot(versionedSnapshot(1, 'idle', 1))).toBe(true)
    expect(store.applySnapshot({ ...versionedSnapshot(2, 'idle', 2), thread_id: 'thread-2' })).toBe(true)
    expect(store.get('thread-1')).not.toBeNull()
    expect(store.get('thread-2')).not.toBeNull()

    store.retainOnly('thread-2')
    expect(store.get('thread-2')).not.toBeNull()
    expect(store.get('thread-1')).toBeNull()

    // Retaining a thread that is not cached legitimately empties the cache —
    // the contract is "keep only this id" — and must not throw.
    store.retainOnly('thread-3')
    expect(store.get('thread-2')).toBeNull()
    expect(store.get('thread-3')).toBeNull()
  })

  it('switching sessions evicts every non-active thread from the session cache', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        if (method !== 'thread/resume') return {}
        const threadId = String(params.thread_id)
        return {
          snapshot: {
            ...versionedSnapshot(1, 'idle', 1),
            thread_id: threadId,
            core: { ...coreState(1, 'idle'), thread_id: threadId },
          },
        }
      }),
    })
    const retainOnly = vi.spyOn(CoreSessionStateStore.prototype, 'retainOnly')
    try {
      await controller.connect('thread-1')
      // First connect opens the only thread; there is nothing to evict.
      expect(retainOnly).not.toHaveBeenCalled()

      await controller.switchThread('thread-2')
      expect(retainOnly).toHaveBeenLastCalledWith('thread-2')

      await controller.switchThread('thread-1')
      expect(retainOnly).toHaveBeenLastCalledWith('thread-1')
    } finally {
      retainOnly.mockRestore()
    }
  })

  it('rehydrates a revisited thread from the newest server snapshot after eviction', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const resumes: string[] = []
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        if (method !== 'thread/resume') return {}
        const threadId = String(params.thread_id)
        resumes.push(threadId)
        const revision = threadId === 'thread-1' && resumes.filter((id) => id === threadId).length > 1 ? 9 : 5
        return {
          snapshot: {
            ...versionedSnapshot(1, 'idle', revision),
            thread_id: threadId,
            core: { ...coreState(1, 'idle'), thread_id: threadId, revision },
          },
        }
      }),
    })

    await controller.connect('thread-1')
    expect(runtime.state?.revision).toBe(5)
    await controller.switchThread('thread-2')
    expect(runtime.state?.thread_id).toBe('thread-2')
    await controller.switchThread('thread-1')
    // The revisit must show the fresh server state, not a blend with the
    // evicted visit's cached snapshot.
    expect(runtime.state?.thread_id).toBe('thread-1')
    expect(runtime.state?.revision).toBe(9)
  })

  it('applies the journal tail that follows the resume snapshot after a switch', async () => {
    // 新后端语义：resume 的日志增量从快照序号之后开始。快照说 running，尾部
    // 事件说 completed——快照先水合、尾部事件随后补上，两段必须都生效。
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        if (method !== 'thread/resume') return {}
        const threadId = String(params.thread_id)
        const resumed = {
          ...versionedSnapshot(10, 'running', 10),
          thread_id: threadId,
          core: { ...coreState(10, 'running'), thread_id: threadId },
        }
        const events = threadId === 'thread-1'
          ? [{ ...runStatusEvent('tail-done', 'completed'), seq: 11 }]
          : []
        return { snapshot: resumed, events }
      }),
    })

    await controller.switchThread('thread-1')

    expect(runtime.state?.thread_id).toBe('thread-1')
    expect(runtime.state?.core?.status).toBe('completed')
    expect(runtime.state?.snapshot_seq).toBe(11)
    expect(runtime.state?.core?.seen_event_ids).toContain('tail-done')
  })

  it('keeps untouched item identities when a journal tail event lands on the resumed snapshot', () => {
    // 投影缓存按条目对象引用判定是否重建：尾部事件只改动自己那条 item，
    // 其余 item 的引用必须原样保留，未变化的消息才不会整窗重渲。
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const base = snapshot(10, 'running')
    const core = base.core!
    core.turns!['turn-1'] = { turn_id: 'turn-1', status: 'running', items: ['item-a', 'item-b'] }
    core.items!['item-a'] = {
      item_id: 'item-a', turn_id: 'turn-1', kind: 'message', status: 'running',
      content: 'partial', payload: { type: 'agentMessage' },
    }
    core.items!['item-b'] = {
      item_id: 'item-b', turn_id: 'turn-1', kind: 'tool_call', status: 'completed',
      content: 'done', payload: { type: 'dynamicToolCall', tool_name: 'read_file' },
    }
    core.item_order = ['item-a', 'item-b']
    controller.applyResponse({ snapshot: base })
    const itemsBefore = runtime.state?.core?.items

    controller.applyResponse({
      events: [{
        event_id: 'tail-delta',
        thread_id: 'thread-1',
        seq: 11,
        method: 'core/runItem',
        created_at: '2026-10-11T00:00:00Z',
        item_id: 'item-a',
        turn_id: 'turn-1',
        payload: {
          event_id: 'tail-delta',
          thread_id: 'thread-1',
          item_id: 'item-a',
          turn_id: 'turn-1',
          kind: 'message',
          status: 'running',
          payload: { type: 'agentMessage', delta: ' full' },
        },
      }],
    })

    expect(runtime.state?.core?.items?.['item-a']?.content).toBe('partial full')
    expect(runtime.state?.core?.items?.['item-b']).toBe(itemsBefore?.['item-b'])
  })

  it('applies two rapid switches in order and lands on the last selected thread', async () => {
    // 快速连续切换：两次切换串行执行，最终状态是最后选择的线程，中间线程的
    // 快照不得泄漏成当前状态；竞态到达的旧线程快照推送同样必须被忽略。
    const runtime = createCoreAppServerRuntimeState()
    const resumedThreads: string[] = []
    let pushSnapshot: ((snapshot: CoreAppSnapshot) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: ({ onConnectionState, onSnapshot }) => {
        pushSnapshot = onSnapshot
        return {
          async connect() { onConnectionState?.('open') },
          async request(method: string, params: Record<string, unknown> = {}) {
            if (method !== 'thread/resume') return {}
            const threadId = String(params.thread_id)
            resumedThreads.push(threadId)
            return {
              snapshot: {
                ...versionedSnapshot(1, 'idle', 1),
                thread_id: threadId,
                core: { ...coreState(1, 'idle'), thread_id: threadId },
              },
            }
          },
          respondServerRequest: () => false,
          close() {},
        }
      },
    })

    const first = controller.switchThread('thread-2')
    const second = controller.switchThread('thread-1')
    await Promise.all([first, second])

    expect(runtime.activeThreadId).toBe('thread-1')
    expect(runtime.state?.thread_id).toBe('thread-1')
    expect(resumedThreads).toEqual(['thread-2', 'thread-1'])

    // A racing snapshot push for the thread we already left must not take
    // over the visible state.
    pushSnapshot?.({
      ...versionedSnapshot(9, 'running', 9),
      thread_id: 'thread-2',
      core: { ...coreState(9, 'running'), thread_id: 'thread-2', revision: 9 },
    })
    expect(runtime.state?.thread_id).toBe('thread-1')
    expect(runtime.state?.snapshot_seq).toBe(1)
  })

  it('ignores a mutation response snapshot for a thread the user has switched away from', async () => {
    // 执行命令这类长耗时请求的响应带着整包快照回来时，用户可能已经切走。
    // 旧线程的快照不得顶掉当前界面，否则当前会话会整卡显示成旧会话。
    const runtime = createCoreAppServerRuntimeState()
    let resolveCommand!: (value: Record<string, unknown>) => void
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(async (method, params) => {
        if (method === 'thread/resume') {
          const threadId = String(params.thread_id)
          return {
            snapshot: {
              ...versionedSnapshot(1, 'idle', 1),
              thread_id: threadId,
              core: { ...coreState(1, 'idle'), thread_id: threadId },
            },
          }
        }
        if (method === 'command.execute') {
          return await new Promise<Record<string, unknown>>((resolve) => { resolveCommand = resolve })
        }
        return {}
      }),
    })

    await controller.connect('thread-1')
    const running = controller.executeCommand('thread-1', 'compact')
    await controller.switchThread('thread-2')
    expect(runtime.state?.thread_id).toBe('thread-2')

    resolveCommand({
      result: {},
      snapshot: {
        ...versionedSnapshot(2, 'idle', 2),
        thread_id: 'thread-1',
        core: { ...coreState(2, 'idle'), thread_id: 'thread-1' },
      },
    })
    await running

    expect(runtime.state?.thread_id).toBe('thread-2')
    expect(runtime.state?.snapshot_seq).toBe(1)
  })

  it('still hydrates snapshot pushes for the active thread', async () => {
    // 过滤不能误伤正常路径：活跃线程自己的快照推送（回合边界）必须照常生效。
    const runtime = createCoreAppServerRuntimeState()
    let pushSnapshot: ((snapshot: CoreAppSnapshot) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: ({ onSnapshot }) => {
        pushSnapshot = onSnapshot
        return fakeClient(async (method, params) => {
          if (method !== 'thread/resume') return {}
          const threadId = String(params.thread_id)
          return {
            snapshot: {
              ...versionedSnapshot(1, 'idle', 1),
              thread_id: threadId,
              core: { ...coreState(1, 'idle'), thread_id: threadId },
            },
          }
        })
      },
    })

    await controller.connect('thread-1')
    pushSnapshot?.({ ...versionedSnapshot(5, 'completed', 5), core: { ...coreState(5, 'completed'), revision: 5 } })

    expect(runtime.state?.thread_id).toBe('thread-1')
    expect(runtime.state?.snapshot_seq).toBe(5)
    expect(runtime.state?.core?.status).toBe('completed')
  })

  it('records applied journal tail ids so the next boundary snapshot can be skipped', () => {
    // 切会话补拉事件的标识补录进已收集合后，回合边界快照若只罗列已收事件
    // 且内容一致，就应整体跳过，不再强制一次全量替换（投影缓存得以保留）。
    const runtime = createCoreAppServerRuntimeState()
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: () => fakeClient(),
    })

    const base = snapshot(10, 'running')
    base.core!.turns!['turn-1'] = { turn_id: 'turn-1', status: 'running', items: ['response-1'] }
    base.core!.items!['response-1'] = {
      item_id: 'response-1', turn_id: 'turn-1', kind: 'message', status: 'running',
      content: 'hello', payload: { type: 'agentMessage' },
    }
    base.core!.item_order = ['response-1']
    controller.applyResponse({ snapshot: base })

    controller.applyResponse({
      events: [{ ...runItemDelta('tail-1', ' tail'), seq: 11 }],
    })
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('hello tail')

    // The boundary snapshot adds nothing the client has not already received
    // and its content matches the event-derived state — skip the hydration.
    const boundary = snapshot(12, 'running')
    boundary.seen_event_ids = ['tail-1']
    boundary.core!.turns!['turn-1'] = { turn_id: 'turn-1', status: 'running', items: ['response-1'] }
    boundary.core!.items!['response-1'] = {
      item_id: 'response-1', turn_id: 'turn-1', kind: 'message', status: 'running',
      content: 'hello tail', seq: 11, payload: { type: 'agentMessage' },
    }
    boundary.core!.item_order = ['response-1']
    const stateBefore = runtime.state
    controller.hydrate(boundary)

    expect(runtime.state).toBe(stateBefore)
    expect(runtime.state?.snapshot_seq).toBe(11)
  })
})

function fakeClient(
  request: (
    method: string,
    params: Record<string, unknown>,
    timeoutMs?: number,
  ) => Promise<Record<string, unknown>> = async () => ({}),
): CoreAppServerRuntimeClient {
  return {
    async connect() {},
    request,
    respondServerRequest() { return false },
    close() {},
  }
}

class ReconnectingClient implements CoreAppServerRuntimeClient {
  static instances: ReconnectingClient[] = []
  static requests: Array<{ method: string; params: Record<string, unknown> }> = []

  constructor(
    private readonly onSnapshot: (snapshot: CoreAppSnapshot) => void,
    private readonly onConnectionState: (state: 'connecting' | 'open' | 'closed' | 'error') => void,
  ) {
    ReconnectingClient.instances.push(this)
  }

  async connect() {
    this.onConnectionState('open')
  }

  async request(method: string, params: Record<string, unknown> = {}) {
    ReconnectingClient.requests.push({ method, params })
    if (method === 'thread/resume') {
      const first = ReconnectingClient.requests.filter((item) => item.method === 'thread/resume').length === 1
      const seq = first ? 8 : 12
      const resumed = snapshot(seq, 'running')
      // The second resume snapshot carries an event the client has not seen
      // (it happened while disconnected), so it must be hydrated.
      resumed.seen_event_ids = first ? ['s1'] : ['s1', 's2']
      return { snapshot: resumed }
    }
    return { ok: true }
  }

  respondServerRequest() { return false }

  close() {
    this.onConnectionState('closed')
  }
}

function snapshot(seq: number, status: CoreAppSnapshot['status']): CoreAppSnapshot {
  return {
    thread_id: 'thread-1',
    snapshot_seq: seq,
    status,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    queue: [],
    requests: {},
    artifacts: {},
    core: coreState(seq, status),
  }
}

function versionedSnapshot(
  seq: number,
  status: CoreAppSnapshot['status'],
  revision: number,
): CoreAppSnapshot {
  const value = snapshot(seq, status)
  value.revision = revision
  if (value.core) value.core.revision = revision
  return value
}

function coreState(seq: number, status: CoreAppSnapshot['status']): NonNullable<CoreAppSnapshot['core']> {
  return {
    thread_id: 'thread-1',
    snapshot_seq: seq,
    seen_event_ids: [],
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    status,
  }
}

function runItemDelta(eventId: string, delta: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 0,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:00Z',
    transient: true,
    item_id: 'response-1',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      item_id: 'response-1',
      turn_id: 'turn-1',
      kind: 'message',
      status: 'running',
      payload: { type: 'agentMessage', delta },
    },
  }
}

function runStatusEvent(
  eventId: string,
  status: string,
  runtimeMetrics?: Record<string, unknown>,
  durationMs?: number,
): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 2,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:01Z',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      turn_id: 'turn-1',
      kind: 'status',
      status,
      payload: {
        type: 'turn',
        status,
        ...(runtimeMetrics ? { runtime_metrics: runtimeMetrics } : {}),
        ...(durationMs !== undefined ? { duration_ms: durationMs } : {}),
      },
    },
  }
}

function runUsageEvent(eventId: string, usage: Record<string, unknown>): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 2,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:01Z',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      turn_id: 'turn-1',
      kind: 'usage',
      status: 'running',
      usage,
      payload: { type: 'turn', runtime_metrics: usage },
    },
  }
}

function runMetricsEvent(eventId: string, usage: Record<string, unknown>): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 2,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:01Z',
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      turn_id: 'turn-1',
      kind: 'usage',
      status: 'running',
      usage,
      payload: { type: 'turn', runtime_metrics: usage, replace: true },
    },
  }
}

function runItemToolResult(eventId: string, itemId: string): CoreAppEvent {
  return {
    event_id: eventId,
    thread_id: 'thread-1',
    seq: 3,
    method: 'core/runItem',
    created_at: '2026-07-15T00:00:02Z',
    transient: true,
    item_id: itemId,
    turn_id: 'turn-1',
    payload: {
      event_id: eventId,
      thread_id: 'thread-1',
      item_id: itemId,
      turn_id: 'turn-1',
      kind: 'tool_result',
      status: 'completed',
      payload: {
        type: 'dynamicToolCall',
        tool_name: 'generate_image',
        tool_result: '[generate_image] 已生成 1 张图片',
        status: 'ok',
      },
      artifacts: [{
        artifact_id: 'art-1',
        item_id: itemId,
        kind: 'image',
        name: 'x.png',
        uri: '.lam/artifacts/images/x.png',
      }],
    },
  }
}

  it('holds events arriving before the first snapshot and replays them after hydrate (audit 16 S2)', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    let resolveResume!: (value: Record<string, unknown>) => void
    const resumePromise = new Promise<Record<string, unknown>>((resolve) => { resolveResume = resolve })
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => (method === 'thread/resume' ? await resumePromise : {}))
      },
      scheduleFrame: (callback) => frames.push(callback),
    })

    const connecting = controller.connect('thread-1')
    // A transient delta arrives while the resume snapshot is still in flight.
    onEvent?.(runItemDelta('delta-1', 'hel'))

    // First flush: no state yet — events must be held, not dropped.
    expect(frames).toHaveLength(1)
    frames[0]()
    expect(frames).toHaveLength(2) // re-scheduled, not dropped
    expect(runtime.state?.core?.items?.['response-1']).toBeUndefined()

    resolveResume({ snapshot: snapshot(1, 'running') })
    await connecting
    frames[1]()
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('hel')
  })

  it('filters coalesced batches by id instead of dropping unseen events (audit 16 S3)', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: { ...snapshot(1, 'running'), core: { ...coreState(1, 'running'), seen_event_ids: ['seen-1'] } } }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    // One coalesced batch mixing an already-seen id and a fresh delta.
    onEvent?.({
      ...runItemDelta('new-1', 'tail'),
      payload: {
        ...runItemDelta('new-1', 'tail').payload,
        _coalesced_event_ids: ['seen-1', 'new-1'],
      },
    })
    frames[0]()
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('tail')
  })

  it('hydrates when core.items content diverges from the event-derived state (audit 16 S2)', async () => {
    const runtime = createCoreAppServerRuntimeState()
    const frames: Array<() => void> = []
    let onEvent: ((event: CoreAppEvent) => void) | undefined
    const controller = createCoreAppServerRuntimeController(runtime, {
      createClient: (callbacks) => {
        onEvent = callbacks.onEvent
        return fakeClient(async (method) => method === 'thread/resume'
          ? { snapshot: snapshot(1, 'running') }
          : {})
      },
      scheduleFrame: (callback) => frames.push(callback),
    })
    await controller.connect('thread-1')

    // Event-derived state with a truncated content.
    onEvent?.(runItemDelta('delta-1', 'part'))
    frames[0]()
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('part')

    // A boundary snapshot with canonical full content and only seen ids:
    // only the new core.items fingerprint comparison can force the hydrate.
    const fullSnapshot: CoreAppSnapshot = {
      ...snapshot(2, 'completed'),
      core: {
        ...coreState(2, 'completed'),
        seen_event_ids: ['delta-1'],
        item_order: ['response-1'],
        turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: ['response-1'] } },
        items: {
          'response-1': {
            item_id: 'response-1',
            turn_id: 'turn-1',
            kind: 'message',
            type: 'agentMessage',
            status: 'completed',
            content: 'part full canonical content',
            payload: { type: 'agentMessage' },
          },
        },
      },
    }
    controller.hydrate(fullSnapshot)
    expect(runtime.state?.core?.items?.['response-1']?.content).toBe('part full canonical content')
    expect(runtime.state?.core?.status).toBe('completed')
  })

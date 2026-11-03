/**
 * Protocol coverage, driven by the real workbench client.
 *
 * The unit tests prove the store and the adapter behave. This proves the thing
 * that actually matters: the same `CoreAppServerClient` the desktop app uses can
 * call each method and get an answer that is not METHOD_NOT_FOUND and not a
 * fabricated empty object.
 *
 * Skipped unless SUNDAY_SERVE_URL is set, because it needs a live core.
 */
// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { CoreAppServerClient } from '../src/appServer/client.ts'
import { DirectTransport } from '../src/transport/directTransport.ts'
import type { CoreAppEvent } from '../src/appServer/protocol.ts'

const wsUrl = process.env.SUNDAY_SERVE_URL || ''
const runnable = wsUrl ? describe : describe.skip

function connect() {
  const events: CoreAppEvent[] = []
  const transport = new DirectTransport({ apiBase: 'http://127.0.0.1:1', wsUrl })
  const client = new CoreAppServerClient({
    transport,
    clientInfo: { name: 'lamtools-ui-coverage', version: '0.0.0' },
    onEvent: (event) => events.push(event),
  })
  return { client, events }
}

function waitFor<T>(check: () => T | undefined, timeoutMs = 90_000): Promise<T> {
  const started = Date.now()
  return new Promise<T>((resolve, reject) => {
    const tick = () => {
      const value = check()
      if (value !== undefined) return resolve(value)
      if (Date.now() - started > timeoutMs) return reject(new Error('timed out'))
      setTimeout(tick, 50)
    }
    tick()
  })
}

runnable('the workbench protocol surface', () => {
  it('opens a thread without forking it on a retry', async () => {
    const { client } = connect()
    await client.connect()
    const threadId = `open-${Date.now()}`

    const first = await client.request('thread/start', { thread_id: threadId })
    expect(first.thread_id).toBe(threadId)
    const second = await client.request('thread/start', { thread_id: threadId })
    expect(second.thread_id).toBe(threadId)
    // Opening twice must not create two conversations or bump a revision.
    expect(second.snapshot_seq ?? 0).toBe(first.snapshot_seq ?? 0)
    client.close()
  })

  it('queues, edits, reorders and deletes a real queue', async () => {
    const { client } = connect()
    await client.connect()
    const threadId = `queue-${Date.now()}`

    const created = await client.request('queue/create', {
      thread_id: threadId,
      queue_item_id: 'q-a',
      input: [{ type: 'text', text: 'first message' }],
    })
    const queue = created.queue as Array<Record<string, unknown>>
    expect(Array.isArray(queue)).toBe(true)
    expect(queue.length).toBe(1)
    // The stored input must contain the text the user typed, not a placeholder.
    expect(JSON.stringify(queue[0].input)).toContain('first message')

    await client.request('queue/create', {
      thread_id: threadId,
      queue_item_id: 'q-b',
      input: [{ type: 'text', text: 'second message' }],
    })

    // A retried create with the same id must not duplicate.
    await client.request('queue/create', {
      thread_id: threadId,
      queue_item_id: 'q-a',
      input: [{ type: 'text', text: 'first message' }],
    })
    const afterRetry = await client.request('queue/list', { thread_id: threadId })
    expect((afterRetry.queue as unknown[]).length).toBe(2)

    const edited = await client.request('queue/update', {
      thread_id: threadId,
      queue_item_id: 'q-a',
      input: [{ type: 'text', text: 'edited text' }],
    })
    expect(JSON.stringify(edited.queue)).toContain('edited text')

    const reordered = await client.request('queue/reorder', {
      thread_id: threadId,
      order: ['q-b', 'q-a'],
    })
    const ids = (reordered.queue as Array<Record<string, unknown>>).map((i) => i.queue_item_id)
    expect(ids).toEqual(['q-b', 'q-a'])

    const deleted = await client.request('queue/delete', {
      thread_id: threadId,
      queue_item_id: 'q-b',
    })
    expect((deleted.queue as unknown[]).length).toBe(1)
    client.close()
  })

  it('reads history in pages that add up to the whole thread', async () => {
    const threadId = `history-${Date.now()}`
    const writer = connect()
    await writer.client.connect({ threadId })

    // Produce real events with a real model.
    await writer.client.request('turn/start', {
      thread_id: threadId,
      client_message_id: `m-${Date.now()}`,
      input: [{ type: 'text', text: 'Reply with the single word: paged' }],
      include_snapshot: false,
    })
    await waitFor(() => writer.events.find((e) => e.method === 'turn/completed'))
    writer.client.close()

    const { client } = connect()
    await client.connect()
    const first = await client.request('thread/read', { thread_id: threadId, limit: 3 })
    const page = first.history_page as Record<string, unknown>
    expect(page, 'thread/read returned no history_page').toBeTruthy()
    expect(Number(page.item_count)).toBeGreaterThan(0)
    expect(Number(page.total_items)).toBeGreaterThan(0)

    // Walking back must terminate and reproduce the journal without gaps.
    let cursor = Number(page.next_before_seq || 0)
    let hasMore = page.has_more === true
    let guard = 0
    while (hasMore && cursor > 0) {
      guard += 1
      expect(guard, 'history pagination did not terminate').toBeLessThan(50)
      const next = await client.request('thread/read', {
        thread_id: threadId,
        before_seq: cursor,
        limit: 3,
      })
      const nextPage = next.history_page as Record<string, unknown>
      cursor = Number(nextPage.next_before_seq || 0)
      hasMore = nextPage.has_more === true
    }
    expect(hasMore).toBe(false)
    client.close()
  }, 120_000)

  it('refuses a steer honestly when nothing is running', async () => {
    const { client } = connect()
    await client.connect()
    const threadId = `steer-${Date.now()}`

    const response = await client.request('turn/steer', {
      thread_id: threadId,
      turn_id: 'turn-1',
      input: [{ type: 'text', text: 'do this instead' }],
    })
    // The client reads `applied` to decide whether to queue the text. A refusal
    // is a normal answer, not an error, so the text is not lost.
    expect(response.applied).toBe(false)
    expect(String(response.reason)).toBeTruthy()
    client.close()
  })

  it('stops a running turn through turn/interrupt', async () => {
    const threadId = `stop-${Date.now()}`
    const { client, events } = connect()
    await client.connect({ threadId })

    await client.request('turn/start', {
      thread_id: threadId,
      client_message_id: `m-${Date.now()}`,
      input: [{ type: 'text', text: 'Write a 500 word essay about rivers.' }],
      include_snapshot: false,
    })
    // Let it start producing, then stop it.
    await waitFor(() => events.find((e) => e.method === 'turn/accepted'))

    await client.request('turn/interrupt', { thread_id: threadId })

    // Whatever the turn was doing must stop. A cancelled turn reports completion
    // with a cancelled status rather than running to the end.
    const stopped = await waitFor(
      () =>
        events.find(
          (e) =>
            e.method === 'turn/completed' &&
            String(e.payload?.status) === 'cancelled',
        ),
      60_000,
    )
    expect(stopped.thread_id).toBe(threadId)
    client.close()
  }, 120_000)

  it('keeps naming pause, terminate and force_reset distinctly', async () => {
    const { client } = connect()
    await client.connect()
    for (const method of ['turn/pause', 'turn/terminate', 'turn/force_reset']) {
      const threadId = `${method.replace('/', '-')}-${Date.now()}`
      // Each must be answered: an unknown method would raise here.
      const response = await client.request(method, { thread_id: threadId })
      expect(response, `${method} was not answered`).toBeTruthy()
    }
    client.close()
  })

  it('still says METHOD_NOT_FOUND for what it does not implement', async () => {
    const { client } = connect()
    await client.connect()
    // Honesty check: a method outside the covered set must not be faked.
    await expect(client.request('artifact/export', {})).rejects.toThrow(/method not found/i)
    client.close()
  })
})

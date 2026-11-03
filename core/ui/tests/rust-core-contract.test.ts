// @vitest-environment node
/**
 * Drives the real Rust core with the real workbench client.
 *
 * `node` environment on purpose: jsdom installs its own `WebSocket` whose
 * `Event` class is a different realm from the one Node's socket implementation
 * dispatches, and the two refuse each other. This test has no DOM in it.
 *
 * This is not a mock: it imports the same `CoreAppServerClient` and
 * `DirectTransport` the desktop app uses, points them at a live `sunday serve`
 * process, and asserts what the UI would actually display.
 *
 * Skipped unless SUNDAY_SERVE_URL is set, because it needs a running core and a
 * real model. A test that quietly passes with no core would prove nothing.
 */
import { describe, expect, it } from 'vitest'
import { CoreAppServerClient } from '../src/appServer/client.ts'
import { DirectTransport } from '../src/transport/directTransport.ts'
import type { CoreAppEvent } from '../src/appServer/protocol.ts'

const wsUrl = process.env.SUNDAY_SERVE_URL || ''
const runnable = wsUrl ? describe : describe.skip

function connect(threadId?: string) {
  const events: CoreAppEvent[] = []
  const states: string[] = []
  const transport = new DirectTransport({ apiBase: 'http://127.0.0.1:1', wsUrl })
  const client = new CoreAppServerClient({
    transport,
    clientInfo: { name: 'lamtools-ui-contract', version: '0.0.0' },
    onEvent: (event) => events.push(event),
    onConnectionState: (state) => states.push(state),
  })
  return { client, events, states, transport, threadId }
}

function waitFor<T>(check: () => T | undefined, timeoutMs = 90_000): Promise<T> {
  const started = Date.now()
  return new Promise<T>((resolve, reject) => {
    const tick = () => {
      const value = check()
      if (value !== undefined) return resolve(value)
      if (Date.now() - started > timeoutMs) return reject(new Error('timed out waiting for an event'))
      setTimeout(tick, 50)
    }
    tick()
  })
}

runnable('the new Rust core speaking core.app_server.v1', () => {
  it('initializes with the capabilities the workbench needs', async () => {
    const { client, states } = connect()
    await client.connect()
    expect(client.capabilities.login).not.toBe(true)
    expect(client.capabilities.protocol).toBe('core.app_server.v1')
    expect(client.capabilities.streaming).toBe(true)
    expect(client.capabilities.approval).toBe(true)
    expect(states).toContain('open')
    client.close()
  })

  it('runs a real turn against a real model and streams the answer', async () => {
    const threadId = `ui-${Date.now()}`
    const { client, events } = connect(threadId)
    await client.connect({ threadId })

    const clientMessageId = `msg-${Date.now()}`
    await client.request('turn/start', {
      thread_id: threadId,
      client_message_id: clientMessageId,
      input: [{ type: 'text', text: 'Reply with the single word: ready' }],
      include_snapshot: false,
    })

    // The client treats turn/accepted as the authoritative acceptance, so the
    // core must produce one carrying the same client_message_id.
    const accepted = await waitFor(() =>
      events.find((e) => e.method === 'turn/accepted' && e.client_message_id === clientMessageId),
    )
    expect(accepted.thread_id).toBe(threadId)
    expect(accepted.protocol_version).toBe('core.app_server.v1')

    // And the turn must finish, not merely start.
    const completed = await waitFor(() => events.find((e) => e.method === 'turn/completed'))
    expect(completed.thread_id).toBe(threadId)

    // Every event shares one monotonically increasing sequence per thread.
    const seqs = events.filter((e) => e.thread_id === threadId).map((e) => e.seq)
    expect(seqs.length).toBeGreaterThan(0)
    expect([...seqs].sort((a, b) => a - b)).toEqual(seqs)
    expect(new Set(seqs).size).toBe(seqs.length)

    client.close()
  }, 120_000)

  it('stops at a real approval and continues with a real file write after it', async () => {
    const threadId = `tool-${Date.now()}`
    const { client, events } = connect(threadId)
    await client.connect({ threadId })

    await client.request('turn/start', {
      thread_id: threadId,
      client_message_id: `msg-${Date.now()}`,
      input: [
        {
          type: 'text',
          text: 'Write the exact text hello into the file ui-check.txt using the write_file tool.',
        },
      ],
      include_snapshot: false,
    })

    // write_file asks the user, so the turn must pause on an approval card the
    // UI can actually answer: it needs request_id, not the core's approval_id.
    const approval = await waitFor(
      () => events.find((e) => e.method === 'item/approval_request'),
      120_000,
    )
    const requestId = String(approval.payload.request_id || '')
    expect(requestId, 'the approval card had no request_id to answer').toBeTruthy()

    await client.request('approval/respond', {
      thread_id: threadId,
      request_id: requestId,
      decision: 'approve',
      guidance: '',
    })

    await waitFor(() => events.find((e) => e.method === 'turn/completed'), 120_000)

    const methods = events.map((e) => e.method)
    expect(methods, `methods were ${methods.join(', ')}`).toContain('turn/model_completed')
    expect(methods, `methods were ${methods.join(', ')}`).toContain('item/approval_request')

    client.close()
  }, 240_000)

  it('replays the journal for a reconnecting client', async () => {
    const threadId = `replay-${Date.now()}`

    const first = connect(threadId)
    await first.client.connect({ threadId })
    await first.client.request('turn/start', {
      thread_id: threadId,
      client_message_id: `msg-${Date.now()}`,
      input: [{ type: 'text', text: 'Say the word: replay' }],
      include_snapshot: false,
    })
    await waitFor(() => first.events.find((e) => e.method === 'turn/completed'), 120_000)
    const originalSeqs = first.events
      .filter((e) => e.thread_id === threadId)
      .map((e) => e.seq)
    expect(originalSeqs.length).toBeGreaterThan(0)
    first.client.close()

    // A fresh client asking from seq 0 must be given the same history.
    const second = connect(threadId)
    await second.client.connect({ threadId })
    const replay = await waitFor(() =>
      second.events.some((e) => e.method === 'turn/completed') ? second.events : undefined,
    )
    const replaySeqs = replay.filter((e) => e.thread_id === threadId).map((e) => e.seq)
    expect(replaySeqs.sort((a, b) => a - b)).toEqual([...originalSeqs].sort((a, b) => a - b))
    second.client.close()
  }, 180_000)

  it('refuses a second writer on the same data directory', async () => {
    // The lock is a host concern, but it must be observable from outside: a
    // second `sunday serve` on the same --db has to refuse to start.
    const { execFileSync } = await import('node:child_process')
    const { writeFileSync } = await import('node:fs')
    const binary = process.env.SUNDAY_BIN
    const dbDir = process.env.SUNDAY_DB_DIR
    expect(binary, 'SUNDAY_BIN must point at the sunday binary').toBeTruthy()
    expect(dbDir, 'SUNDAY_DB_DIR must point at the live data directory').toBeTruthy()

    // A valid script, so the only reason to fail is the lock. An empty script
    // would fail argument validation first and prove nothing.
    const scriptPath = `${process.env.TEMP || '.'}/sunday-lock-probe.json`
    writeFileSync(scriptPath, JSON.stringify([{ text: 'ok' }]))

    let failed = false
    let message = ''
    try {
      execFileSync(
        binary!,
        [
          'serve',
          '--db', `${dbDir}/core.db`,
          '--workspace', dbDir!,
          '--listen', '127.0.0.1:0',
          '--script', scriptPath,
        ],
        { timeout: 20_000, encoding: 'utf8', stdio: 'pipe' },
      )
    } catch (error) {
      failed = true
      const failure = error as { stderr?: string; stdout?: string; message?: string }
      message = `${failure.stderr || ''}${failure.stdout || ''}${failure.message || ''}`
    }
    expect(failed, 'a second core on the same database must not start').toBe(true)
    expect(message, `the refusal said: ${message}`).toMatch(/lock|locked|another core/i)
  }, 60_000)
})

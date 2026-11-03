// @vitest-environment node
/**
 * Proves data written before a restart is still there after one.
 *
 * The other coverage tests create a fresh thread each run, so they would pass
 * even if the store were wiped on relaunch. This one uses a fixed thread id and
 * a fixed queue item, so it can only pass if the database really survived.
 *
 * Run it in two phases:
 *   before restart:  SUNDAY_PHASE=write
 *   after restart:   SUNDAY_PHASE=read
 */
import { describe, expect, it } from 'vitest'
import { CoreAppServerClient } from '../src/appServer/client.ts'
import { DirectTransport } from '../src/transport/directTransport.ts'

const wsUrl = process.env.SUNDAY_SERVE_URL || ''
const phase = process.env.SUNDAY_PHASE || 'write'
const threadId = 'android-persistence-check'
const queueText = 'written before the restart'

function connect() {
  const transport = new DirectTransport({ apiBase: 'http://127.0.0.1:1', wsUrl })
  return new CoreAppServerClient({
    transport,
    clientInfo: { name: 'persistence-check', version: '0.0.0' },
  })
}

const runnable = wsUrl ? describe : describe.skip

runnable(`persistence across a restart (${phase})`, () => {
  it(phase === 'write' ? 'writes a queue item to a fixed thread' : 'reads it back after the restart', async () => {
    const client = connect()
    await client.connect()
    await client.request('thread/start', { thread_id: threadId })

    if (phase === 'write') {
      await client.request('queue/create', {
        thread_id: threadId,
        queue_item_id: 'persist-1',
        input: [{ type: 'text', text: queueText }],
      })
      const check = await client.request('queue/list', { thread_id: threadId })
      expect(JSON.stringify(check.queue)).toContain(queueText)
    } else {
      // The queue item must still be there, with its text, after the process was
      // killed and the app relaunched.
      const check = await client.request('queue/list', { thread_id: threadId })
      const queue = check.queue as Array<Record<string, unknown>>
      expect(queue.length, 'the queue was empty after a restart').toBeGreaterThan(0)
      expect(JSON.stringify(queue)).toContain(queueText)
    }

    client.close()
  }, 60_000)
})

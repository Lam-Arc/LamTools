// Verify the library contract on the live demo window.
//
//   node scripts/demo-video/verify-library.mjs --new --ask "<produce something>"
//   node scripts/demo-video/verify-library.mjs --ask "把这次的结果整理进资料库。"
//
// Two invocations so the catalog can be inspected in between: the first turn
// produces files (a deliverable plus scratch), the second asks the agent to file
// this turn's result.  What actually lands in the catalog is checked out of band
// against the demo database — not from this script.

import { connectSunday, createActor, sleep } from './driver/sunday.mjs'
import { newSession, askPrompt } from './beats/_lib.mjs'

const args = process.argv.slice(2)
const value = (name, fallback = null) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}
const has = (name) => args.includes(`--${name}`)

/** Wait for a turn to start and finish, judged by the composer's send/stop state. */
async function waitForTurn(
  page,
  { startTimeout = 120000, timeout = 60 * 60 * 1000, stableMs = 8000 } = {},
) {
  await page.waitForFunction(
    () => {
      const button = document.querySelector('.core-send-stop-button')
      const running = button && button.dataset.state === 'stop'
      const answered = document.querySelector('[data-assistant-actions]')
      return Boolean(running || answered)
    },
    null,
    { timeout: startTimeout, polling: 200 },
  )
  const deadline = Date.now() + timeout
  let idleSince = 0
  for (;;) {
    if (Date.now() > deadline) throw new Error('turn did not finish within the timeout')
    const busy = await page.evaluate(
      () => document.querySelector('.core-send-stop-button')?.dataset.state === 'stop',
    )
    if (busy) idleSince = 0
    else if (!idleSince) idleSince = Date.now()
    else if (Date.now() - idleSince >= stableMs) break
    await sleep(400)
  }
}

const { page } = await connectSunday()
const actor = createActor(page)
const ctx = {
  actor,
  page,
  waitTurn: (options) => waitForTurn(page, options),
  hold: (ms) => sleep(ms),
  note: (message) => console.log(`   ${message}`),
}

if (has('new')) {
  await newSession(ctx)
  console.log('new session ready')
}

const ask = value('ask')
if (!ask) {
  console.log('nothing to ask; pass --ask "<text>"')
  process.exit(0)
}

console.log(`asking: ${ask}`)
await askPrompt(ctx, ask, { delay: 20 })
console.log('turn finished')
process.exit(0)

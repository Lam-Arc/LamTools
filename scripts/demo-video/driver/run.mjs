// Run one scripted beat against the live Sunday window, with or without capture.
//
//   node scripts/demo-video/driver/run.mjs --take smoke [--beat smoke] [--no-capture]
//
// The runner owns everything a beat should not care about: attaching to the
// window, the demo viewport, the frame-supply ticker, the screencast, the
// action log, screenshots, and a run report.  A beat is a plain async function
// that drives the UI; if it throws, the run is marked failed and no take is
// considered usable.

import fs from 'node:fs'
import path from 'node:path'
import { connectSunday, createActor, startCapture, takeDir, sleep, applyDemoLayout, assertForeground, sizeDemoWindow, DEMO_LAYOUT } from './sunday.mjs'
import { ensureAnimating } from './health.mjs'

const args = process.argv.slice(2)
const value = (name, fallback = null) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}
const has = (name) => args.includes(`--${name}`)
const all = (name) => {
  const out = []
  args.forEach((item, index) => {
    if (item === `--${name}` && args[index + 1]) out.push(args[index + 1])
  })
  return out
}

export const VIEWPORT = {
  width: Number(value('width', process.env.DEMO_VIEWPORT_W || 1440)),
  height: Number(value('height', process.env.DEMO_VIEWPORT_H || 900)),
  scale: Number(value('scale', process.env.DEMO_VIEWPORT_SCALE || 2)),
}

/** Wait for a turn to start and finish, judging by the composer's send/stop state. */
export async function waitForTurn(
  page,
  { startTimeout = 90000, timeout = 45 * 60 * 1000, stableMs = 6000 } = {},
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
  // A turn can look idle in the seams — between a truncated stream and the
  // retry, or between tool batches — so require the idle state to hold before
  // calling the run finished.  Reporting "done" early would end a take while
  // the app is still working.
  const deadline = Date.now() + timeout
  let idleSince = 0
  for (;;) {
    if (Date.now() > deadline) throw new Error('turn did not finish within the timeout')
    const busy = await page.evaluate(
      () => document.querySelector('.core-send-stop-button')?.dataset.state === 'stop',
    )
    if (busy) {
      idleSince = 0
    } else if (!idleSince) {
      idleSince = Date.now()
    } else if (Date.now() - idleSince >= stableMs) {
      break
    }
    await sleep(400)
  }
  // The UI settles its post-run state (actions row, jump pill) after the flag flips.
  await sleep(1200)
}

async function main() {
  const take = value('take')
  if (!take) throw new Error('--take is required')
  const beatName = value('beat', take)
  const dir = takeDir(take)
  fs.mkdirSync(dir, { recursive: true })
  const captureEnabled = !has('no-capture')
  const keepAlive = has('keep-alive')

  const report = {
    take,
    beat: beatName,
    startedAt: new Date().toISOString(),
    viewport: VIEWPORT,
    capture: captureEnabled,
    status: 'running',
  }

  const { browser, context, page } = await connectSunday()
  const actor = createActor(page, { logFile: path.join(dir, 'actions.jsonl') })
  let capture = null
  let failure = null

  try {
    // Workspace reset first: a replay must re-run the same tools on the same
    // starting state, and stale outputs would show up in tool results.
    for (const target of all('reset')) {
      fs.rmSync(target, { recursive: true, force: true })
      console.log(`reset ${target}`)
    }

    // The window must cover the screen for input to land and stay undisrupted;
    // sizing is part of every run so a take is reproducible from scratch.
    sizeDemoWindow()
    await page.evaluate(`
      (() => {
        const node = document.createElement('div')
        node.setAttribute('data-demo-ticker', '1')
        node.style.cssText = 'position:fixed;left:0;top:0;width:2px;height:2px;pointer-events:none;z-index:2147483647;opacity:0.01;background:#fff;will-change:transform'
        document.documentElement.appendChild(node)
        let n = 0
        const step = () => { n = (n + 1) % 4096; node.style.transform = 'translate3d(' + n + 'px,0,0)'; window.__demoTicker = requestAnimationFrame(step) }
        window.__demoTicker = requestAnimationFrame(step)
        return 'installed'
      })()
    `)
    const fps = await ensureAnimating(context, page)
    report.frameSupplyFps = Number(fps.toFixed(1))
    if (fps < 10) throw new Error(`window is not producing frames (${fps.toFixed(1)} fps)`)

    report.layout = await applyDemoLayout(context, page)
    await assertForeground(page)
    report.foreground = true

    if (captureEnabled) {
      capture = await startCapture(context, page, { dir, scale: 1, quality: 92 })
      report.captureStartedAt = new Date().toISOString()
    }

    const beat = await import(`../beats/${beatName}.mjs`)
    const ctx = {
      page,
      actor,
      context,
      dir,
      take,
      viewport: VIEWPORT,
      waitTurn: (options) => waitForTurn(page, options),
      /** Park on a UI state for the edit without any motion. */
      hold: async (ms) => sleep(ms),
      shot: async (name) => {
        const target = path.join(dir, 'stills', `${name}.png`)
        fs.mkdirSync(path.dirname(target), { recursive: true })
        await page.screenshot({ path: target })
        return target
      },
      note: (message) => {
        console.log(`   ${message}`)
      },
    }
    console.log(`beat ${beatName}: starting`)
    await beat.run(ctx)
    console.log(`beat ${beatName}: done`)
    report.status = 'ok'
  } catch (error) {
    failure = error
    report.status = 'failed'
    report.error = String(error && error.stack ? error.stack : error)
    console.error(`beat ${beatName} failed:`, error)
    await page.screenshot({ path: path.join(dir, 'failure.png') }).catch(() => {})
  } finally {
    if (capture) {
      report.capture = await capture.stop()
    }
    report.endedAt = new Date().toISOString()
    report.actions = actor.events.length
    fs.writeFileSync(path.join(dir, 'run.json'), JSON.stringify(report, null, 2))
    if (!keepAlive) await browser.close()
  }

  if (failure) process.exit(1)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})

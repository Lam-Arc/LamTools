// Drive the real Sunday window over CDP and capture it.
//
// Everything the demo needs from the app goes through here:
//   connectSunday()  attach to the running Tauri window (WebView2 debug port)
//   createActor()    click/type with an action log (element box + wall clock),
//                    which the compositor later turns into an animated cursor
//   startCapture()   screencast frames + timestamps for the edit
//
// The action log is the contract between "what happened" and "what the video
// shows": every entry carries the target's box in CSS pixels and the epoch ms
// it happened, so the cursor overlay can be placed exactly.

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

export const CDP_PORT = process.env.DEMO_CDP_PORT || '9222'
export const VITE_PORT = process.env.DEMO_VITE_PORT || '5273'
export const DEMO_ROOT = process.env.DEMO_ROOT || 'E:/LamDemo'

/**
 * The demo layout: the window's own fullscreen viewport.
 *
 * On this 2K display the browser reports ~1375x773 CSS pixels at pixel ratio
 * 1.85, and frames come out around 2544x1431 — plenty for a 1080p master with
 * room for camera push-ins.
 *
 * Two constraints shaped this:
 *  * the window must fit the physical screen, because synthetic input that
 *    falls outside the visible desktop area is silently dropped;
 *  * the layout must not be emulated larger than that visible area, for the
 *    same reason — an emulated viewport renders beyond it but cannot be
 *    clicked.  So the window sizes the layout, and nothing overrides it.
 */
export const DEMO_LAYOUT = {
  width: Number(process.env.DEMO_LAYOUT_WIDTH || 0),
  height: Number(process.env.DEMO_LAYOUT_HEIGHT || 0),
  dsf: Number(process.env.DEMO_LAYOUT_DSF || 0),
}

export async function applyDemoLayout(context, page, layout = DEMO_LAYOUT) {
  if (!layout.width || !layout.height) {
    // Natural fullscreen layout: report it and leave it alone.
    await sleep(400)
    return page.evaluate(() => ({
      width: window.innerWidth,
      height: window.innerHeight,
      dpr: window.devicePixelRatio,
    }))
  }
  const cdp = await context.newCDPSession(page)
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: layout.width,
    height: layout.height,
    deviceScaleFactor: layout.dsf || 1,
    mobile: false,
  })
  await cdp.detach()
  await sleep(500)
  return page.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
    dpr: window.devicePixelRatio,
  }))
}

/**
 * The window must be foreground: synthetic pointer input is delivered through
 * the OS input path, so a covering window silently swallows clicks.  Beats
 * fail loudly here instead of filming a window that ignores them.
 */
export async function assertForeground(page, { attempts = 3 } = {}) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const focused = await page.evaluate(() => document.hasFocus()).catch(() => false)
    if (focused) return true
    await activateDemoWindow()
    await sleep(700)
  }
  const focused = await page.evaluate(() => document.hasFocus()).catch(() => false)
  if (!focused) {
    throw new Error(
      'the demo window is not in the foreground; synthetic clicks would be swallowed',
    )
  }
  return true
}

/** Raise and focus the demo window through env/window.ps1. */
export async function activateDemoWindow() {
  runWindowScript(['-Activate'])
}

/** Size the window so the whole layout sits inside the physical screen. */
export async function sizeDemoWindow({ width, height, x = 0, y = 0 } = {}) {
  // 2K panel at the desktop's scale factor; see DEMO_LAYOUT above.
  const targetWidth = width || Number(process.env.DEMO_WINDOW_W || 2560)
  const targetHeight = height || Number(process.env.DEMO_WINDOW_H || 1440)
  runWindowScript([
    '-Width',
    String(targetWidth),
    '-Height',
    String(targetHeight),
    '-X',
    String(x),
    '-Y',
    String(y),
  ])
}

function runWindowScript(args) {
  const script = path.join(
    path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')),
    '..',
    'env',
    'window.ps1',
  )
  spawnSync('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, ...args], {
    stdio: 'ignore',
    timeout: 60000,
  })
}

export function takeDir(take) {
  return process.env.DEMO_TAKE_DIR || path.join(DEMO_ROOT, 'takes', take)
}

export function appendJsonl(file, payload) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.appendFileSync(file, JSON.stringify(payload) + '\n', 'utf8')
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** Attach to the demo instance's WebView2 over CDP. */
export async function connectSunday({ cdpPort = CDP_PORT, urlPart = VITE_PORT } = {}) {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${cdpPort}`, {
    timeout: 30000,
  })
  let context = browser.contexts()[0]
  if (!context) throw new Error('CDP exposed no browser context')
  let page = context.pages().find((candidate) => (candidate.url() || '').includes(urlPart))
  if (!page) {
    const deadline = Date.now() + 20000
    while (!page && Date.now() < deadline) {
      await sleep(500)
      page = context.pages().find((candidate) => (candidate.url() || '').includes(urlPart))
    }
  }
  if (!page) page = context.pages()[0]
  if (!page) throw new Error('no page found in the Sunday window')
  await page.waitForLoadState('domcontentloaded').catch(() => {})
  return { browser, context, page }
}

/**
 * Interactive actor. Every action waits for its target, records the target box
 * and timestamp, then performs the action — so a failing beat fails loudly
 * instead of producing footage of a half-driven window.
 */
export function createActor(page, { logFile } = {}) {
  const events = []
  const emit = (event) => {
    events.push(event)
    if (logFile) appendJsonl(logFile, event)
    return event
  }

  const locatorOf = (target, options = {}) => {
    if (typeof target === 'string') {
      const locator = page.locator(target)
      return options.index === undefined ? locator.first() : locator.nth(options.index)
    }
    return target
  }

  const boxOf = async (target, options = {}) => {
    const locator = locatorOf(target, options)
    await locator.waitFor({ state: 'visible', timeout: options.timeout ?? 20000 })
    const box = await locator.boundingBox()
    if (!box) throw new Error(`no bounding box for ${options.label || String(target)}`)
    return { box, locator }
  }

  return {
    events,
    page,

    /** Move only (used to place the animated cursor without clicking). */
    async move(target, options = {}) {
      const { box } = await boxOf(target, options)
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      return emit({
        t: Date.now(),
        kind: 'move',
        label: options.label || null,
        box,
      })
    },

    async click(target, options = {}) {
      const { box, locator } = await boxOf(target, options)
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await sleep(options.settleMs ?? 120)
      await locator.click({ timeout: options.timeout ?? 20000 })
      return emit({
        t: Date.now(),
        kind: 'click',
        label: options.label || null,
        box,
      })
    },

    /**
     * Click without the preliminary mouse move.
     *
     * Menus that reposition themselves as the pointer travels (the composer's
     * model/thinking menu does) are unreliable under a move-then-click: the
     * panel moves after the move and the click lands on empty space.  The
     * video draws its own cursor from the action log, so the real pointer
     * never needs to travel.
     */
    async clickDirect(target, options = {}) {
      const locator = locatorOf(target, options)
      await locator.waitFor({ state: 'visible', timeout: options.timeout ?? 20000 })
      const box = await locator.boundingBox()
      await locator.click({ timeout: options.timeout ?? 20000 })
      return emit({
        t: Date.now(),
        kind: 'click',
        label: options.label || null,
        box: box || undefined,
      })
    },

    /**
     * Type with a visible per-character delay so the video shows the input.
     *
     * Newlines must go in as Shift+Enter: a bare Enter submits in this
     * composer, so typing a multi-line prompt otherwise fires it off as
     * several queued messages and the model only ever sees the first line.
     */
    async type(target, text, options = {}) {
      const { box, locator } = await boxOf(target, options)
      const delay = options.delay ?? 45
      await locator.click()
      await locator.fill('')
      const lines = String(text).split('\n')
      for (let index = 0; index < lines.length; index += 1) {
        if (index > 0) {
          await page.keyboard.press('Shift+Enter')
          await sleep(Math.min(delay * 2, 120))
        }
        if (lines[index]) {
          await locator.type(lines[index], { delay, timeout: options.timeout ?? 120000 })
        }
      }
      return emit({
        t: Date.now(),
        kind: 'type',
        label: options.label || null,
        box,
        chars: [...text].length,
        text,
      })
    },

    async fill(target, text, options = {}) {
      const { box, locator } = await boxOf(target, options)
      await locator.fill(text, { timeout: options.timeout ?? 20000 })
      return emit({
        t: Date.now(),
        kind: 'fill',
        label: options.label || null,
        box,
        text,
      })
    },

    async press(key, options = {}) {
      await page.keyboard.press(key)
      return emit({ t: Date.now(), kind: 'press', label: options.label || key, key })
    },

    async hover(target, options = {}) {
      const { box, locator } = await boxOf(target, options)
      await locator.hover()
      return emit({ t: Date.now(), kind: 'hover', label: options.label || null, box })
    },

    /** Escape hatch for composite gestures (drag, multi-step menus). */
    async act(label, fn, options = {}) {
      const started = Date.now()
      const result = await fn()
      return emit({ t: started, kind: 'act', label, note: options.note || null, ms: Date.now() - started, result: options.result ? result : undefined })
    },

    async waitFor(selector, options = {}) {
      const locator = options.index === undefined ? page.locator(selector).first() : page.locator(selector).nth(options.index)
      await locator.waitFor({ state: options.state || 'visible', timeout: options.timeout ?? 30000 })
      return locator
    },

    async count(selector) {
      return page.locator(selector).count()
    },

    async text(selector) {
      return page.locator(selector).first().innerText().catch(() => '')
    },

    async shoot(name, directory) {
      const target = path.join(directory, `${name}.png`)
      fs.mkdirSync(path.dirname(target), { recursive: true })
      await page.screenshot({ path: target })
      return target
    },
  }
}

// ---------------------------------------------------------------------------
// capture
// ---------------------------------------------------------------------------

/**
 * Record the window as screencast frames.
 *
 * `scale` raises the device pixel ratio via a metrics override, which yields
 * larger frames of the same layout — the source of truth for camera push-ins
 * that must stay sharp.
 */
export async function startCapture(context, page, options = {}) {
  const dir = options.dir
  if (!dir) throw new Error('startCapture needs a dir')
  const framesDir = path.join(dir, 'frames')
  fs.rmSync(framesDir, { recursive: true, force: true })
  fs.mkdirSync(framesDir, { recursive: true })

  const cdp = await context.newCDPSession(page)
  await cdp.send('Page.enable')

  const scale = options.scale ?? 1
  if (scale !== 1) {
    const viewport = page.viewportSize() || { width: 1440, height: 900 }
    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: viewport.width,
      height: viewport.height,
      deviceScaleFactor: scale,
      mobile: false,
    })
    await sleep(400)
  }

  const frames = []
  let size = { width: 0, height: 0 }
  const startedAt = Date.now()

  cdp.on('Page.screencastFrame', (frame) => {
    const index = frames.length
    const file = `f${String(index).padStart(6, '0')}.jpg`
    fs.writeFileSync(path.join(framesDir, file), Buffer.from(frame.data, 'base64'))
    size = {
      width: frame.metadata.deviceWidth || size.width,
      height: frame.metadata.deviceHeight || size.height,
    }
    frames.push({
      i: index,
      file,
      // Chromium reports seconds since epoch; normalise to ms for the edit.
      t: Math.round((frame.metadata.timestamp || Date.now() / 1000) * 1000),
    })
    cdp.send('Page.screencastFrameAck', { sessionId: frame.sessionId }).catch(() => {})
  })

  await cdp.send('Page.startScreencast', {
    format: options.format || 'jpeg',
    quality: options.quality ?? 92,
    maxWidth: options.maxWidth ?? 4096,
    maxHeight: options.maxHeight ?? 4096,
    everyNthFrame: options.everyNthFrame ?? 1,
  })

  return {
    dir,
    framesDir,
    startedAt,
    viewport: page.viewportSize(),
    get frames() {
      return frames
    },
    get size() {
      return size
    },
    async stop() {
      await cdp.send('Page.stopScreencast').catch(() => {})
      if (scale !== 1) {
        await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {})
      }
      const endedAt = Date.now()
      const meta = {
        startedAt,
        endedAt,
        durationMs: endedAt - startedAt,
        scale,
        size,
        viewport: page.viewportSize(),
        frameCount: frames.length,
        fps: frames.length / Math.max(1, (endedAt - startedAt) / 1000),
      }
      fs.writeFileSync(path.join(dir, 'capture-meta.json'), JSON.stringify(meta, null, 2))
      fs.writeFileSync(path.join(dir, 'frames.json'), JSON.stringify(frames))
      await cdp.detach().catch(() => {})
      return meta
    },
  }
}

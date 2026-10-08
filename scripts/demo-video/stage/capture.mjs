// Capture a stage scene: start the render stage, walk the timeline frame by
// frame, encode with ffmpeg.
//
//   node scripts/demo-video/stage/capture.mjs --scene first-look
//   node scripts/demo-video/stage/capture.mjs --scene first-look --fps 30 --crf 18
//   node scripts/demo-video/stage/capture.mjs --scene first-look --at 4.0,12.5 --out E:/LamDemo/stage
//
// The stage is the real product mounted headlessly, so this never touches the
// desktop application, its window or its data.

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const REPO = path.resolve(HERE, '../../..')

const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}
const has = (name) => args.includes(`--${name}`)

const SCENE = value('scene', 'first-look')
const PORT = Number(value('port', 5299))
const WIDTH = Number(value('width', 1920))
const HEIGHT = Number(value('height', 1080))
const SCALE = Number(value('scale', 1))
const FPS = Number(value('fps', 30))
const CRF = Number(value('crf', 18))
const FORMAT = value('format', 'jpeg')
const AUDIO = value('audio', '')
const OUT_ROOT = value('out', 'E:/LamDemo/stage')
const AT = value('at', '')
const CAPTIONS = value('captions', '1')
const THEME = value('theme', '')
const KEEP_FRAMES = has('keep-frames')

const outDir = path.join(OUT_ROOT, SCENE)
const framesDir = path.join(outDir, 'frames')

/* ------------------------------------------------- the stage's dependencies */
// The stage borrows core/ui's installed tree so the product's own copy of vue
// (and of every other package) is the only one in the graph.
function ensureDeps() {
  const link = path.join(HERE, 'node_modules')
  const target = path.join(REPO, 'core', 'ui', 'node_modules')
  if (fs.existsSync(link)) return
  if (!fs.existsSync(target)) {
    throw new Error(`core/ui dependencies are missing: run "cd core/ui && npm ci" first`)
  }
  fs.symlinkSync(target, link, 'junction')
  console.log(`  linked stage/node_modules -> core/ui/node_modules`)
}

/** The stage also needs playwright, which lives at the repo root. */
function viteBin() {
  const candidates = [
    path.join(HERE, 'node_modules', 'vite', 'bin', 'vite.js'),
    path.join(REPO, 'node_modules', 'vite', 'bin', 'vite.js'),
  ]
  const found = candidates.find((candidate) => fs.existsSync(candidate))
  if (!found) throw new Error('vite not found; run "cd core/ui && npm ci"')
  return found
}

async function waitForServer(url, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  throw new Error(`stage server did not come up at ${url}`)
}

async function main() {
  ensureDeps()
  fs.rmSync(framesDir, { recursive: true, force: true })
  fs.mkdirSync(framesDir, { recursive: true })

  const server = spawn(
    process.execPath,
    [viteBin(), '--config', path.join(HERE, 'vite.config.ts'), '--port', String(PORT), '--strictPort'],
    { cwd: HERE, stdio: ['ignore', 'pipe', 'pipe'] },
  )
  let serverLog = ''
  server.stdout.on('data', (chunk) => { serverLog += chunk.toString() })
  server.stderr.on('data', (chunk) => { serverLog += chunk.toString() })

  const stop = () => { try { server.kill() } catch { /* already gone */ } }
  process.on('exit', stop)
  process.on('SIGINT', () => { stop(); process.exit(130) })

  try {
    const base = `http://127.0.0.1:${PORT}/`
    await waitForServer(base)

    const browser = await chromium.launch({
      args: ['--force-color-profile=srgb', '--font-render-hinting=none', '--hide-scrollbars'],
    })
    const context = await browser.newContext({
      viewport: { width: WIDTH, height: HEIGHT },
      deviceScaleFactor: SCALE,
      locale: 'zh-CN',
      timezoneId: 'Asia/Shanghai',
      reducedMotion: 'reduce',
    })
    // fixed clock and seeded randomness: two runs must produce the same frames
    await context.addInitScript(() => {
      let seed = 0x2f6e2b1
      Math.random = () => {
        seed ^= seed << 13
        seed ^= seed >>> 17
        seed ^= seed << 5
        return ((seed >>> 0) / 4294967296)
      }
    })
    const page = await context.newPage()
    await page.clock.setFixedTime(new Date('2026-10-06T08:00:00'))

    const url = `${base}?scene=${encodeURIComponent(SCENE)}&captions=${CAPTIONS}${THEME ? `&theme=${THEME}` : ''}`
    await page.goto(url, { waitUntil: 'domcontentloaded' })
    await page.waitForFunction(
      () => window.__sceneReady === true || typeof window.__sceneError === 'string',
      null,
      { timeout: 90_000 },
    )
    const failure = await page.evaluate(() => window.__sceneError || '')
    if (failure) throw new Error(`stage reported: ${failure}`)
    await page.evaluate(() => document.fonts && document.fonts.ready)

    const meta = await page.evaluate(() => window.sceneMeta || {})
    const duration = Number(value('duration', meta.duration || 6))
    console.log(`stage ${SCENE}: ${WIDTH * SCALE}x${HEIGHT * SCALE} @${FPS}fps, ${duration}s`)

    const runFrame = async (seconds) => {
      await page.evaluate((t) => (window).renderFrame(t), seconds)
    }

    if (AT) {
      const times = AT.split(',').map(Number)
      const stillDir = path.join(outDir, 'stills')
      fs.mkdirSync(stillDir, { recursive: true })
      for (const seconds of times) {
        await runFrame(seconds)
        const file = path.join(stillDir, `${String(seconds).replace('.', '_')}s.${FORMAT}`)
        await page.screenshot({ path: file, type: FORMAT, ...(FORMAT === 'png' ? {} : { quality: 92 }) })
        console.log(`  -> ${file}`)
      }
    } else {
      const totalFrames = Math.round(duration * FPS)
      const started = Date.now()
      for (let frame = 0; frame < totalFrames; frame += 1) {
        await runFrame(frame / FPS)
        const file = path.join(framesDir, `f${String(frame).padStart(5, '0')}.${FORMAT}`)
        await page.screenshot({ path: file, type: FORMAT, ...(FORMAT === 'png' ? {} : { quality: 92 }) })
        if (frame % Math.max(1, Math.round(FPS)) === 0) {
          process.stdout.write(`\r  ${frame}/${totalFrames} frames`)
        }
      }
      process.stdout.write(`\r  ${totalFrames}/${totalFrames} frames\n`)
      await browser.close()

      const outFile = path.join(outDir, `${SCENE}.mp4`)
      const encodeArgs = [
        '-y', '-hide_banner', '-loglevel', 'error',
        '-framerate', String(FPS),
        '-i', path.join(framesDir, `f%05d.${FORMAT}`),
      ]
      if (AUDIO) encodeArgs.push('-i', AUDIO, '-c:a', 'aac', '-b:a', '192k', '-shortest')
      encodeArgs.push(
        '-c:v', 'libx264', '-crf', String(CRF), '-preset', 'medium',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', outFile,
      )
      const { spawnSync } = await import('node:child_process')
      const encode = spawnSync('ffmpeg', encodeArgs, { encoding: 'utf8' })
      if (encode.status !== 0) {
        console.error(encode.stderr?.slice(-2000) || 'ffmpeg failed')
        process.exit(1)
      }
      const size = fs.statSync(outFile).size / 1e6
      console.log(`  -> ${outFile} (${size.toFixed(2)}MB, ${((Date.now() - started) / 1000).toFixed(1)}s)`)
      if (!KEEP_FRAMES) fs.rmSync(framesDir, { recursive: true, force: true })
      browser.close()
    }
  } catch (error) {
    console.error('capture failed:', error.message)
    if (serverLog.trim()) console.error(serverLog.trim().split('\n').slice(-20).join('\n'))
    process.exitCode = 1
  } finally {
    stop()
  }
}

main()

// Frame-accurate renderer for code-driven motion graphics.
//
//   node scripts/demo-video/motion/render.mjs --scene opening --duration 6
//
// Each scene is an HTML page exposing window.renderFrame(seconds): the page
// holds a paused animation timeline and this renderer walks it frame by frame.
// Screenshots are therefore a pure function of time — no dropped frames, no
// timing jitter, identical output on every run — and the frame sequence is
// encoded with ffmpeg.
//
// Scenes must not rely on wall-clock animation (CSS transitions, rAF loops):
// anything that animates has to be driven by renderFrame.

import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}
const has = (name) => args.includes(`--${name}`)

const SCENE = value('scene', 'opening')
const WIDTH = Number(value('width', 1920))
const HEIGHT = Number(value('height', 1080))
const FPS = Number(value('fps', 60))
const SCALE = Number(value('scale', 1))
const DURATION = Number(value('duration', 0)) || 6
const FORMAT = value('format', 'png')
const OUT_ROOT = value('out', 'E:/LamDemo/motion')
const CRF = Number(value('crf', 16))
const AUDIO = value('audio', '')
const KEEP_FRAMES = has('keep-frames')
const PREVIEW = has('preview')

async function main() {
  const scenePath = path.join(HERE, 'scenes', `${SCENE}.html`)
  if (!fs.existsSync(scenePath)) throw new Error(`no scene at ${scenePath}`)

  const outDir = path.join(OUT_ROOT, SCENE)
  const framesDir = path.join(outDir, 'frames')
  fs.rmSync(framesDir, { recursive: true, force: true })
  fs.mkdirSync(framesDir, { recursive: true })

  const browser = await chromium.launch({ args: ['--force-color-profile=srgb', '--font-render-hinting=none'] })
  const page = await browser.newPage({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: SCALE,
  })
  await page.goto(`file://${scenePath.replace(/\\/g, '/')}`)
  await page.waitForFunction(() => window.__sceneReady === true, null, { timeout: 20000 })
  await page.evaluate(() => document.fonts && document.fonts.ready)

  const meta = await page.evaluate(() => window.sceneMeta || {})
  const duration = Number(value('duration', meta.duration || DURATION))
  const startAt = Number(value('start', 0))
  const totalFrames = Math.round(duration * FPS)
  console.log(
    `scene ${SCENE}: ${WIDTH * SCALE}x${HEIGHT * SCALE} @${FPS}fps, ` +
      `${totalFrames} frames (from ${startAt}s, length ${duration}s)`,
  )

  const started = Date.now()
  for (let frame = 0; frame < totalFrames; frame += 1) {
    const seconds = startAt + frame / FPS
    await page.evaluate((t) => window.renderFrame(t), seconds)
    const file = path.join(framesDir, `f${String(frame).padStart(5, '0')}.${FORMAT}`)
    await page.screenshot({ path: file, type: FORMAT, animations: 'disabled' })
    if (frame % Math.max(1, Math.round(FPS)) === 0) {
      process.stdout.write(`\r  ${frame}/${totalFrames} frames`)
    }
  }
  process.stdout.write(`\r  ${totalFrames}/${totalFrames} frames\n`)
  await browser.close()

  const name = PREVIEW ? `${SCENE}-preview.mp4` : `${SCENE}.mp4`
  const outFile = path.join(outDir, name)
  const crf = PREVIEW ? 23 : CRF
  const preset = PREVIEW ? 'veryfast' : 'medium'
  const audioArgs = AUDIO
    ? ['-i', AUDIO, '-c:a', 'aac', '-b:a', '192k', '-shortest']
    : []
  const encode = spawnSync(
    'ffmpeg',
    [
      '-y',
      '-hide_banner',
      '-loglevel',
      'error',
      '-framerate',
      String(FPS),
      '-i',
      path.join(framesDir, `f%05d.${FORMAT}`),
      ...audioArgs,
      '-c:v',
      'libx264',
      '-crf',
      String(crf),
      '-preset',
      preset,
      '-pix_fmt',
      'yuv420p',
      '-movflags',
      '+faststart',
      outFile,
    ],
    { encoding: 'utf8' },
  )
  if (encode.status !== 0) {
    console.error(encode.stderr?.slice(-2000) || 'ffmpeg failed')
    process.exit(1)
  }

  const size = fs.statSync(outFile).size / 1e6
  console.log(
    `  -> ${outFile} (${size.toFixed(2)}MB, ${((Date.now() - started) / 1000).toFixed(1)}s render)`,
  )
  if (!KEEP_FRAMES) fs.rmSync(framesDir, { recursive: true, force: true })
}

main().catch((error) => {
  console.error('render failed:', error)
  process.exit(1)
})

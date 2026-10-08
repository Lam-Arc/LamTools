// Review sheets: chop a finished video into tiled contact sheets.
//
//   node scripts/demo-video/motion/sheets.mjs --video <file.mp4> --out <dir>
//
// Default is the review convention used for this film: 3 frames per second,
// nine frames per sheet — i.e. one image covers exactly 3 seconds, laid out
// 3x3 in reading order.  That is dense enough to judge pacing and sparse
// enough to keep every frame legible.
//
// Options: --fps 3 --cols 3 --rows 3 --width 620 --from 0 --to 0

import fs from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'

const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}

const VIDEO = value('video', '')
const OUT = value('out', 'E:/LamDemo/review/sheets')
const FPS = Number(value('fps', 3))
const COLS = Number(value('cols', 3))
const ROWS = Number(value('rows', 3))
const WIDTH = Number(value('width', 620))
const FROM = Number(value('from', 0))
const TO = Number(value('to', 0))

if (!VIDEO) {
  console.error('用法: node scripts/demo-video/motion/sheets.mjs --video <mp4> --out <dir>')
  process.exit(1)
}

fs.mkdirSync(OUT, { recursive: true })
for (const file of fs.readdirSync(OUT)) {
  if (file.startsWith('sheet-') && file.endsWith('.png')) fs.rmSync(path.join(OUT, file))
}

const trim = []
if (FROM > 0) trim.push('-ss', String(FROM))
if (TO > FROM) trim.push('-t', String(TO - FROM))

const filter = `fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,tile=${COLS}x${ROWS}:padding=4:margin=4`
const result = spawnSync('ffmpeg', [
  '-y', '-hide_banner', '-loglevel', 'error',
  ...trim,
  '-i', VIDEO,
  '-vf', filter,
  '-fps_mode', 'passthrough',
  path.join(OUT, 'sheet-%03d.png'),
], { stdio: 'inherit' })

if (result.status !== 0) process.exit(result.status || 1)
const made = fs.readdirSync(OUT).filter((f) => f.startsWith('sheet-')).length
console.log(`${made} 张（每张 ${COLS * ROWS / FPS} 秒，${COLS}x${ROWS}，宽 ${WIDTH}）-> ${OUT}`)

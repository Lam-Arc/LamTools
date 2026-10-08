// Reads a rendered WAV back and prints its envelope against the beat grid, so a
// score can be checked without listening to it.
//
//   node scripts/demo-video/motion/score-check.mjs --in E:/LamDemo/motion/merged/merged.wav

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const T = require('./scenes/_timing.js')

const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}

const file = value('in', 'E:/LamDemo/motion/merged/merged.wav')
const step = Number(value('step', T.BEAT)) // one line per beat

const raw = fs.readFileSync(file)
if (raw.toString('ascii', 0, 4) !== 'RIFF' || raw.toString('ascii', 8, 12) !== 'WAVE') throw new Error('not a WAV')
let offset = 12
let fmt = null
let dataAt = 0
let dataLen = 0
while (offset < raw.length - 8) {
  const id = raw.toString('ascii', offset, offset + 4)
  const size = raw.readUInt32LE(offset + 4)
  if (id === 'fmt ') fmt = { channels: raw.readUInt16LE(offset + 10), rate: raw.readUInt32LE(offset + 12), bits: raw.readUInt16LE(offset + 22) }
  if (id === 'data') { dataAt = offset + 8; dataLen = size }
  offset += 8 + size + (size % 2)
}
const bytes = fmt.bits / 8
const frames = Math.floor(dataLen / (bytes * fmt.channels))
const dur = frames / fmt.rate

const cues = []
for (const [name, at] of [
  ['drop', T.drop],
  ['shift', T.shift],
  ['click', [T.clickAt]],
  ['claim', [T.claimAt]],
  ['line', [T.lineAt]],
  ['split', [T.splitAt]],
  ['build', Object.values(T.build)],
  ['enter', T.enter],
  ['done', T.done],
  ['row', T.row],
  ['report', [T.reportAt]],
  ['withdraw', [T.withdrawAt]],
]) for (const t of at) cues.push({ name, t })

const sample = (frame, ch) => raw.readInt16LE(dataAt + (frame * fmt.channels + ch) * bytes) / 32768

console.log(`${path.basename(file)}: ${dur.toFixed(2)}s, ${fmt.rate}Hz, ${fmt.channels}ch, ${fmt.bits}bit`)
console.log(`grid: ${T.BPM} BPM, ${step.toFixed(2)}s per line\n`)

const lines = Math.ceil(dur / step)
let overallPeak = 0
for (let i = 0; i < lines; i += 1) {
  const from = Math.round(i * step * fmt.rate)
  const to = Math.min(frames, Math.round((i + 1) * step * fmt.rate))
  let sum = 0
  let peak = 0
  for (let f = from; f < to; f += 1) {
    const v = (sample(f, 0) + (fmt.channels > 1 ? sample(f, 1) : 0)) / 2
    sum += v * v
    peak = Math.max(peak, Math.abs(v))
  }
  const rms = Math.sqrt(sum / Math.max(1, to - from))
  overallPeak = Math.max(overallPeak, peak)
  const db = 20 * Math.log10(Math.max(rms, 1e-9))
  const bar = '#'.repeat(Math.max(0, Math.round((db + 60) / 1.6)))
  const t = (i * step).toFixed(1).padStart(5)
  const beat = i % 4 === 0 ? '|' : ' '
  const here = cues.filter((c) => c.t >= i * step && c.t < (i + 1) * step).map((c) => c.name)
  console.log(`  ${t}s ${beat} ${db.toFixed(1).padStart(6)}dB ${bar.padEnd(38)} ${here.join(',')}`)
}
console.log(`\npeak ${(20 * Math.log10(overallPeak)).toFixed(1)} dBFS`)

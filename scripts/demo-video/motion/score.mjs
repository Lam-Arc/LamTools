// Code-synthesised score for the merged act — no samples, no dependencies.
//
//   node scripts/demo-video/motion/score.mjs
//   node scripts/demo-video/motion/score.mjs --out E:/LamDemo/motion/merged/merged.wav
//
// The cue times come from scenes/_timing.js, the same table the picture is cut
// against, so every hit lands on the beat the animation lands on. 100 BPM:
// one beat is 0.6s, one bar is 2.4s, the act is 16 bars.
//
// Layers: a slow pad that changes chord four times, a sub pulse under it, a
// soft ticking texture through the middle, and one cue sound per visual event
// (columns landing, the widths shifting, the click, the claim swell, the build
// taps, the three sub-agents' rising triad and their answering bells).

import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)

const HERE = path.dirname(fileURLToPath(import.meta.url))

const args = process.argv.slice(2)
const value = (name, fallback) => {
  const index = args.indexOf(`--${name}`)
  return index === -1 ? fallback : args[index + 1]
}

// 节拍表决定曲子跟谁走：默认是第 1 幕，成片用 --timing scenes/_timing-film.js
const T = require(path.resolve(HERE, value('timing', './scenes/_timing.js')))

const SR = 48000
const N = Math.round(T.TOTAL * SR)
const L = new Float32Array(N)
const R = new Float32Array(N)
const SEND = new Float32Array(N)

/* ---------------------------------------------------------------- helpers */
let seed = 0x2f6e2b1
function rnd() {
  seed ^= seed << 13
  seed ^= seed >>> 17
  seed ^= seed << 5
  return ((seed >>> 0) / 4294967296) * 2 - 1
}

function buf(dur, fill) {
  const out = new Float32Array(Math.max(1, Math.round(dur * SR)))
  if (fill) for (let i = 0; i < out.length; i += 1) out[i] = fill(i)
  return out
}

function biquad(type, f0, Q) {
  const f = Math.min(Math.max(f0, 20), SR * 0.45)
  const w0 = (2 * Math.PI * f) / SR
  const cs = Math.cos(w0)
  const sn = Math.sin(w0)
  const alpha = sn / (2 * Q)
  let b0, b1, b2
  const a0 = 1 + alpha
  const a1 = -2 * cs
  const a2 = 1 - alpha
  if (type === 'lp') { b0 = (1 - cs) / 2; b1 = 1 - cs; b2 = b0 }
  else if (type === 'hp') { b0 = (1 + cs) / 2; b1 = -(1 + cs); b2 = b0 }
  else { b0 = alpha; b1 = 0; b2 = -alpha }
  return { b0: b0 / a0, b1: b1 / a0, b2: b2 / a0, a1: a1 / a0, a2: a2 / a0 }
}

function filt(x, type, f0, Q = 0.7) {
  const c = biquad(type, f0, Q)
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0
  for (let i = 0; i < x.length; i += 1) {
    const x0 = x[i]
    const y0 = c.b0 * x0 + c.b1 * x1 + c.b2 * x2 - c.a1 * y1 - c.a2 * y2
    x2 = x1; x1 = x0; y2 = y1; y1 = y0
    x[i] = y0
  }
  return x
}

// coefficients refreshed every 128 samples: smooth enough for a sweep, cheap
function filtSweep(x, type, f0, f1, Q = 1) {
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0
  let c = biquad(type, f0, Q)
  for (let i = 0; i < x.length; i += 1) {
    if (i % 128 === 0) c = biquad(type, f0 + (f1 - f0) * (i / Math.max(1, x.length - 1)), Q)
    const x0 = x[i]
    const y0 = c.b0 * x0 + c.b1 * x1 + c.b2 * x2 - c.a1 * y1 - c.a2 * y2
    x2 = x1; x1 = x0; y2 = y1; y1 = y0
    x[i] = y0
  }
  return x
}

const smooth = (p) => p * p * (3 - 2 * p)

/* ------------------------------------------------------------- the room */
const COMB = [1215, 1293, 1390, 1476]
const ALLPASS = [605, 480]
function scale(n) { return Math.round((n * SR) / 44100) }

class Comb {
  constructor(size, feedback, damp) {
    this.buf = new Float32Array(scale(size))
    this.i = 0
    this.store = 0
    this.fb = feedback
    this.damp = damp
  }
  run(x) {
    const out = this.buf[this.i]
    this.store = out * (1 - this.damp) + this.store * this.damp
    this.buf[this.i] = x + this.store * this.fb
    this.i = (this.i + 1) % this.buf.length
    return out
  }
}

class Allpass {
  constructor(size, feedback) {
    this.buf = new Float32Array(scale(size))
    this.i = 0
    this.fb = feedback
  }
  run(x) {
    const b = this.buf[this.i]
    const out = -x + b
    this.buf[this.i] = x + b * this.fb
    this.i = (this.i + 1) % this.buf.length
    return out
  }
}

const combsL = COMB.map((s) => new Comb(s, 0.83, 0.22))
const combsR = COMB.map((s) => new Comb(s + 23, 0.83, 0.22))
const apL = ALLPASS.map((s) => new Allpass(s, 0.5))
const apR = ALLPASS.map((s) => new Allpass(s + 17, 0.5))

function reverb(wet = 0.9) {
  const dryL = Float32Array.from(L)
  const dryR = Float32Array.from(R)
  let last = 0
  for (let i = 0; i < N; i += 1) {
    const x = SEND[i] * 0.5
    let a = 0
    let b = 0
    for (const c of combsL) a += c.run(x)
    for (const c of combsR) b += c.run(x)
    a /= combsL.length
    b /= combsR.length
    for (const ap of apL) a = ap.run(a)
    for (const ap of apR) b = ap.run(b)
    L[i] = dryL[i] + a * wet
    R[i] = dryR[i] + b * wet
    last = Math.max(last, Math.abs(L[i]), Math.abs(R[i]))
  }
  return last
}

/* ------------------------------------------------------------ the mixer */
function mix(x, at, gain, pan = 0, send = 0.3) {
  const start = Math.round(at * SR)
  const gl = gain * Math.cos(((pan + 1) * Math.PI) / 4)
  const gr = gain * Math.sin(((pan + 1) * Math.PI) / 4)
  for (let i = 0; i < x.length; i += 1) {
    const j = start + i
    if (j < 0 || j >= N) continue
    const v = x[i]
    L[j] += v * gl
    R[j] += v * gr
    SEND[j] += v * send
  }
}

/* ------------------------------------------------------------ the voices */
function tone(freq, dur, { atk = 0.01, rel = 0.2, partials = [[1, 1]], amp = 1 } = {}) {
  const h = buf(dur)
  const relStart = Math.max(atk, dur - rel)
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    let env = 1
    if (t < atk) env = smooth(t / atk)
    else if (t > relStart) env = smooth(Math.max(0, (dur - t) / (dur - relStart)))
    let v = 0
    for (const [ratio, pa] of partials) v += Math.sin(2 * Math.PI * freq * ratio * t) * pa
    h[i] = v * env * amp
  }
  return h
}

// a soft pad note: two slightly detuned copies, three partials each
function padNote(freq, dur, amp) {
  const h = buf(dur)
  const atk = Math.min(1.7, dur * 0.35)
  const rel = Math.min(1.9, dur * 0.3)
  const relStart = dur - rel
  const parts = [[1, 1], [2, 0.42], [3, 0.18]]
  const det = [1, 1.0035]
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    let env = 1
    if (t < atk) env = smooth(t / atk)
    else if (t > relStart) env = smooth(Math.max(0, (dur - t) / rel))
    let v = 0
    for (const d of det) for (const [ratio, pa] of parts) v += Math.sin(2 * Math.PI * freq * ratio * d * t) * pa
    h[i] = v * env * amp
  }
  return h
}

function subNote(freq, dur, amp, decay = 0) {
  const h = buf(dur)
  const atk = 0.09
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    let env = t < atk ? smooth(t / atk) : Math.exp(-decay * (t - atk))
    if (t > dur - 1.2) env *= smooth(Math.max(0, (dur - t) / 1.2))
    h[i] = Math.sin(2 * Math.PI * freq * t) * env * amp
  }
  return h
}

function thud(amp) {
  const dur = 0.9
  const h = buf(dur)
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    const f = 48 + 130 * Math.exp(-t * 11)
    const env = Math.exp(-t * 7.5) * (1 - Math.exp(-t * 400))
    h[i] = Math.sin((2 * Math.PI * f * t) / (1 + t * 5)) * env * amp
  }
  const n = buf(0.3, (i) => rnd() * Math.exp(-(i / SR) * 26))
  filt(n, 'lp', 420, 0.6)
  for (let i = 0; i < n.length; i += 1) h[i] += n[i] * amp * 0.5
  return h
}

function whoosh(dur, up, amp) {
  const h = buf(dur)
  for (let i = 0; i < h.length; i += 1) h[i] = rnd()
  filtSweep(h, 'bp', up ? 320 : 2400, up ? 2600 : 300, 1.1)
  for (let i = 0; i < h.length; i += 1) {
    const p = i / (h.length - 1 || 1)
    h[i] *= Math.pow(Math.sin(Math.PI * p), 1.4) * amp
  }
  return h
}

function riser(dur, amp) {
  const h = buf(dur)
  for (let i = 0; i < h.length; i += 1) h[i] = rnd()
  filtSweep(h, 'bp', 400, 5200, 0.9)
  for (let i = 0; i < h.length; i += 1) {
    const p = i / (h.length - 1 || 1)
    h[i] *= Math.pow(p, 1.6) * amp
  }
  return h
}

function tick(amp) {
  const h = buf(0.06)
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    const env = Math.exp(-t * 90)
    h[i] = (rnd() * 0.8 + Math.sin(2 * Math.PI * 1650 * t) * 0.5) * env * amp
  }
  return filt(h, 'bp', 2400, 0.9)
}

function shaker(amp) {
  const h = buf(0.09)
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    h[i] = rnd() * Math.exp(-t * 55) * amp
  }
  return filt(h, 'hp', 5200, 0.7)
}

// marimba-ish: fundamental plus a strong fourth partial, short decay
function tap(freq, amp) {
  const h = buf(1.0)
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    const env = Math.exp(-t * 7) * (1 - Math.exp(-t * 300))
    h[i] = (Math.sin(2 * Math.PI * freq * t) + Math.sin(2 * Math.PI * freq * 3.9 * t) * 0.22) * env * amp
  }
  return h
}

function bell(freq, amp, dur = 1.6) {
  const h = buf(dur)
  const parts = [[1, 1], [2.0, 0.45], [2.76, 0.26], [5.4, 0.1]]
  for (let i = 0; i < h.length; i += 1) {
    const t = i / SR
    let v = 0
    for (const [ratio, pa] of parts) v += Math.sin(2 * Math.PI * freq * ratio * t) * pa * Math.exp(-t * (2.2 + ratio * 1.1))
    h[i] = v * (1 - Math.exp(-t * 500)) * amp
  }
  return h
}

/* ------------------------------------------------------------ the score */
// pad + sub: four chords of four bars
for (const chord of T.CHORDS) {
  const at = chord.at * T.BAR
  const dur = chord.bars * T.BAR
  for (const f of chord.tones) mix(padNote(f, dur + 1.2, 0.10 / chord.tones.length), at - 0.3, 1, 0, 0.55)
  for (let b = 0; b < chord.bars; b += 1) {
    const barAt = at + b * T.BAR
    mix(subNote(chord.root, 2.2, 0.13, 1.1), barAt, 1, 0, 0.12)
    // bars 9-12 lean forward: a second pulse on beat 3
    if (chord.name === 'G') mix(subNote(chord.root * 2, 1.1, 0.07, 1.6), barAt + 2 * T.BEAT, 1, 0, 0.1)
  }
}

// a soft ticking texture under the middle of the act
const tickFrom = T.tickFrom ?? 5 * T.BAR
const tickTo = T.tickTo ?? 12 * T.BAR
for (let b = 0; b < T.BARS; b += 1) {
  for (let e = 0; e < 2; e += 1) {
    const at = b * T.BAR + e * T.BEAT * 2
    if (at < tickFrom || at > tickTo) continue
    const fadeIn = Math.min(1, (at - tickFrom) / 2.4)
    const fadeOut = Math.min(1, (tickTo - at) / 2.4)
    mix(shaker(0.024 * fadeIn * fadeOut), at, 1, e === 0 ? -0.25 : 0.25, 0.25)
  }
}

// 第三段（游戏）很长：每拍给一点可数的律动，长段落里也有节拍
for (let b = 0; b < T.BARS; b += 1) {
  const barAt = b * T.BAR
  for (let e = 0; e < 4; e += 1) {
    const at = barAt + e * T.BEAT
    if (at < T.widenGame || at > T.endcard) continue
    mix(tick(0.1), at, 1, e % 2 ? 0.12 : -0.12, 0.15)
  }
}

// ---- the picture's cues ----
T.drop.forEach((at, i) => {
  mix(thud(0.5), at, 1, (i - 1) * 0.2, 0.22)
  mix(whoosh(0.5, false, 0.07), at - 0.45, 1, (i - 1) * 0.2, 0.3)
})
T.shift.forEach((at, i) => mix(whoosh(0.5, true, 0.085), at, 1, (i - 1) * 0.25, 0.35))
mix(tick(0.26), T.clickAt, 1, 0.1, 0.2)
mix(riser(1.8, 0.11), T.claimAt, 1, 0, 0.4)
mix(bell(440, 0.13, 2.4), T.lineAt, 1, 0, 0.45)
mix(tone(220, 2.2, { atk: 0.25, rel: 1.6, partials: [[1, 1], [2, 0.2]], amp: 0.09 }), T.lineAt, 1, 0, 0.4)

T.BUILD_MOTIF.forEach((f, i) => {
  const at = [T.build.tiles, T.build.ground, T.build.body, T.build.roof, T.build.stem][i]
  mix(tap(f, 0.19), at, 1, (i - 2) * 0.2, 0.3)
})
mix(whoosh(1.2, true, 0.05), T.build.sweep, 1, 0, 0.35)
mix(tone(130.81, 1.6, { atk: 0.02, rel: 1.2, partials: [[1, 1], [2, 0.3]], amp: 0.12 }), T.splitAt, 1, 0, 0.25)

// the three sub-agents: a rising triad, panned left / centre / right
T.enter.forEach((at, i) => {
  mix(tone(T.ARP[i], 1.5, { atk: 0.03, rel: 1.0, partials: [[1, 1], [2, 0.3], [3, 0.1]], amp: 0.17 }), at, 1, T.PANS[i], 0.4)
})
// their completion answers an octave up, one beat apart
T.done.forEach((at, i) => {
  mix(bell(T.ARP_UP[i], 0.12, 1.8), at, 1, T.PANS[i], 0.5)
})
mix(tone(110, 2.6, { atk: 0.4, rel: 1.8, partials: [[1, 1], [2, 0.25]], amp: 0.12 }), T.reportAt, 1, 0, 0.45)
mix(bell(880, 0.11, 2.2), T.reportAt + T.BEAT, 1, 0, 0.5)
mix(whoosh(1.4, false, 0.07), T.withdrawAt, 1, 0, 0.4)
mix(bell(1760, 0.06, 2.6), T.withdrawAt + T.BAR, 1, 0.1, 0.6)

// 成果一页页落地：轻得像翻页，左右交替，别抢戏
;(T.arrive || []).forEach((at, i) => {
  mix(tick(0.17), at, 1, i % 2 ? 0.2 : -0.2, 0.24)
})

/* --------------------------------------------------------- master + write */
const preReverbPeak = L.reduce((m, v) => Math.max(m, Math.abs(v)), 0)
const peak = reverb(0.85)

// soft clip, then normalise to -1 dBFS
const ceiling = 0.82
for (let i = 0; i < N; i += 1) {
  L[i] = Math.tanh(L[i] / ceiling) * ceiling
  R[i] = Math.tanh(R[i] / ceiling) * ceiling
}
let after = 0
for (let i = 0; i < N; i += 1) after = Math.max(after, Math.abs(L[i]), Math.abs(R[i]))
const norm = 0.89 / after

const fadeIn = Math.round(0.12 * SR)
const fadeOut = Math.round(1.1 * SR)
const out = Buffer.alloc(44 + N * 4)
out.write('RIFF', 0)
out.writeUInt32LE(36 + N * 4, 4)
out.write('WAVE', 8)
out.write('fmt ', 12)
out.writeUInt32LE(16, 16)
out.writeUInt16LE(1, 20)
out.writeUInt16LE(2, 22)
out.writeUInt32LE(SR, 24)
out.writeUInt32LE(SR * 4, 28)
out.writeUInt16LE(4, 32)
out.writeUInt16LE(16, 34)
out.write('data', 36)
out.writeUInt32LE(N * 4, 40)
for (let i = 0; i < N; i += 1) {
  let fade = 1
  if (i < fadeIn) fade = i / fadeIn
  else if (i > N - fadeOut) fade = Math.max(0, (N - i) / fadeOut)
  const l = Math.max(-1, Math.min(1, L[i] * norm * fade))
  const r = Math.max(-1, Math.min(1, R[i] * norm * fade))
  out.writeInt16LE(Math.round(l * 32767), 44 + i * 4)
  out.writeInt16LE(Math.round(r * 32767), 46 + i * 4)
}

const outFile = value('out', path.join('E:/LamDemo/motion/merged', 'merged.wav'))
fs.mkdirSync(path.dirname(outFile), { recursive: true })
fs.writeFileSync(outFile, out)

const db = (x) => (20 * Math.log10(Math.max(x, 1e-9))).toFixed(1)
console.log(`${T.TOTAL}s @ ${T.BPM} BPM (${T.BARS} bars), ${SR} Hz stereo`)
console.log(`  dry peak ${db(preReverbPeak)} dBFS -> wet peak ${db(peak)} dBFS -> normalised ${db(0.89)} dBFS`)
console.log(`  -> ${outFile} (${(out.length / 1e6).toFixed(1)}MB)`)

/* The vocabulary a stage scene is written in.
 *
 * Same shapes as the motion scenes (`scripts/demo-video/motion/scenes/_kit.js`)
 * so the two halves of the film can be cut against one timeline: 100 BPM, one
 * beat is 0.6s, one bar is 2.4s.
 */

export const BEAT = 0.6
export const BAR = BEAT * 4

export const clamp01 = (value: number) => (value < 0 ? 0 : value > 1 ? 1 : value)

export const lerp = (from: number, to: number, p: number) => from + (to - from) * p

/** How far `t` has travelled through [from, to], clamped to 0..1. */
export function seg(t: number, from: number, to: number): number {
  if (to <= from) return t >= to ? 1 : 0
  return clamp01((t - from) / (to - from))
}

export const ease = {
  linear: (p: number) => p,
  quadOut: (p: number) => 1 - (1 - p) * (1 - p),
  cubicOut: (p: number) => 1 - Math.pow(1 - p, 3),
  quintOut: (p: number) => 1 - Math.pow(1 - p, 5),
  expoOut: (p: number) => (p >= 1 ? 1 : 1 - Math.pow(2, -10 * p)),
  sineInOut: (p: number) => -(Math.cos(Math.PI * p) - 1) / 2,
  cubicInOut: (p: number) => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2),
  /** a small overshoot; good for something arriving */
  softBack: (p: number) => {
    const c = 1.70158
    const q = p - 1
    return 1 + (c + 1) * q * q * q + c * q * q
  },
}

/** 0..1 for the index-th item of a staggered group. */
export function stagger(
  t: number,
  index: number,
  options: { start: number; each: number; dur?: number },
): number {
  const from = options.start + index * options.each
  return ease.quintOut(seg(t, from, from + (options.dur ?? 0.5)))
}

/* --------------------------------------------------------------- text ---- */

/**
 * The characters of `text` that have been "typed" by time `t`.
 *
 * This is how streaming is rendered without any wall clock: the snapshot says
 * how much of the message exists, and the product draws that. Nothing in the
 * UI animates on its own.
 */
export function reveal(text: string, t: number, at: number, cps = 26): string {
  if (t <= at) return ''
  return text.slice(0, Math.max(0, Math.floor((t - at) * cps)))
}

/** True once `text` has been fully revealed. */
export function revealed(text: string, t: number, at: number, cps = 26): boolean {
  if (t <= at) return false
  return Math.floor((t - at) * cps) >= text.length
}

/** A number that eases from one value to another across a window of time. */
export function ramp(
  t: number,
  from: number,
  to: number,
  a: number,
  b: number,
  easing: (p: number) => number = ease.sineInOut,
): number {
  return lerp(a, b, easing(seg(t, from, to)))
}

/* ------------------------------------------------------------ cosmetics ---- */

export interface CursorState {
  x: number
  y: number
  /** 0..1 while the button is held */
  press?: number
  alpha?: number
}

export function cursorHtml(cursor: CursorState | null | undefined): string {
  if (!cursor) return ''
  const { x, y, press = 0, alpha = 1 } = cursor
  if (alpha <= 0.01) return ''
  return `<div class="cursor" style="left:${x.toFixed(1)}px;top:${y.toFixed(1)}px;opacity:${alpha.toFixed(3)};transform:scale(${(1 - press * 0.3).toFixed(3)})"></div>`
}

export function rippleHtml(
  x: number,
  y: number,
  radius: number,
  progress: number,
  alpha = 0.9,
): string {
  if (progress <= 0 || progress >= 1) return ''
  const scale = lerp(0.3, 3.2, ease.expoOut(progress))
  const fade = Math.sin(Math.PI * progress) * alpha
  return `<div class="ripple" style="left:${(x - radius).toFixed(1)}px;top:${(y - radius).toFixed(1)}px;width:${radius * 2}px;height:${radius * 2}px;opacity:${fade.toFixed(3)};transform:scale(${scale.toFixed(3)})"></div>`
}

/* ------------------------------------------------------------------ scene ---- */

export interface FrameRect {
  x: number
  y: number
  w: number
  h: number
  radius?: number
}

export interface Caption {
  title: string
  hint?: string
}

export interface SceneFrame {
  /** where the product window sits on the 1920x1080 stage, and how big it is */
  rect: FrameRect
  /** html drawn over the product: the cursor, a click ripple, marks */
  overlay?: string
  /** review aids; switched off for a clean render */
  caption?: Caption | null
}

export interface StageScene {
  id: string
  /** seconds; the picture is defined on [0, duration] */
  duration: number
  /** where the product window sits, and anything drawn over it */
  frame(t: number): SceneFrame
  /**
   * The product state at time t. `revision` must be stamped into the snapshot:
   * the product drops a snapshot whose revision is not newer than the one it
   * already holds.
   */
  data(t: number, revision: number): SceneData
}

export interface StageData {
  projects: unknown[]
  sessions: unknown[]
  threadId: string
  /** the full app-server snapshot the product would receive on the wire */
  snapshot: unknown
  /** what is sitting in the composer box, as if typed by hand */
  composerDraft?: string
  theme?: 'light' | 'dark'
}

/** Alias kept for readability at the call sites. */
export type SceneData = StageData

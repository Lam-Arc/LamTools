/**
 * flowLine — 渐变流光线条驱动（composer 运行态装饰线）
 *
 * 与 v-beam 同一约束：WebView2 下 CSS background-position 动画不触发重绘，
 * 只有每帧直接写内联样式才可靠。模块级共享单条 rAF 链，~20fps 节流
 * （每 3 帧写一次），无元素时自动停止。
 */
const els = new Set<HTMLElement>()
let raf = 0
let last = 0
let skip = 0
let pos = 0

const SPEED = 0.05 // %/ms：background-size 200%，一次循环 200/0.05 ≈ 4s

function tick(ts: number) {
  // 无条件重挂 rAF（条件挂载会在第一帧死锁——v-beam 同款教训）
  raf = requestAnimationFrame(tick)
  skip += 1
  if (skip % 3 !== 0) return
  if (last) pos = (pos + (ts - last) * SPEED) % 200
  last = ts
  for (const el of els) el.style.backgroundPositionX = `${pos}%`
}

export function startFlowLine(el: HTMLElement) {
  el.style.backgroundPositionX = '200%'
  els.add(el)
  if (els.size === 1 && !raf) {
    last = 0
    skip = 0
    raf = requestAnimationFrame(tick)
  }
}

export function stopFlowLine(el: HTMLElement) {
  els.delete(el)
  el.style.backgroundPositionX = ''
  if (els.size === 0 && raf) {
    cancelAnimationFrame(raf)
    raf = 0
  }
}

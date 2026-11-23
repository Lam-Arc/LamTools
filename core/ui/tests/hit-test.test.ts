import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HIT_TEST_PROBES, autoHitTestEnabled, createAutoHitTest, createHitTestReporter, describeElement, elementPath, fingerprintRows, hitTest, installHitTestShortcut, installStealProbe, logHitTest } from '../src/split/hitTest'

const read = (rel: string) => readFileSync(resolve(__dirname, rel), 'utf8')

afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); vi.useRealTimers() })

function place(html: string) {
  document.body.innerHTML = html
  // jsdom 没有布局：把每个元素的 rect 按 data-rect 显式给出来，按钮中心才好算。
  for (const element of Array.from(document.querySelectorAll<HTMLElement>('[data-rect]'))) {
    const [x, y, width, height] = (element.dataset.rect || '0,0,0,0').split(',').map(Number)
    element.getBoundingClientRect = () => ({ x, y, width, height, top: y, left: x, right: x + width, bottom: y + height, toJSON: () => ({}) }) as DOMRect
  }
}

describe('命中测试诊断：点击落在谁身上', () => {
  it('命中按钮自身时 hitSelf 为真，并带上 pointer-events / z-index', () => {
    place('<div class="titlebar"><div class="titlebar-right"><button data-rect="100,10,32,24">min</button></div></div>')
    const button = document.querySelector('button')!
    document.elementFromPoint = vi.fn(() => button) as never
    const [row] = hitTest([{ name: 'titlebar-min', selector: '.titlebar-right button' }])
    expect(row.hitSelf).toBe(true)
    expect(row.point).toEqual({ x: 116, y: 22 })
    expect(row.owner).toContain('button')
    expect(row.pointerEvents).toBe('auto')
  })

  it('被别的层盖住时 hitSelf 为假，并报出盖住它的元素与层级路径', () => {
    place([
      '<div class="titlebar"><div class="titlebar-right"><button data-rect="100,10,32,24">min</button></div></div>',
      '<div class="split-workspace" style="pointer-events:auto"><div class="split-fold-strip" data-rect="100,10,32,24"></div></div>',
    ].join(''))
    const strip = document.querySelector<HTMLElement>('.split-fold-strip')!
    document.elementFromPoint = vi.fn(() => strip) as never
    const [row] = hitTest([{ name: 'titlebar-min', selector: '.titlebar-right button' }])
    expect(row.hitSelf).toBe(false)
    expect(row.owner).toContain('split-fold-strip')
    expect(row.path.at(-1)).toContain('split-fold-strip')
    expect(row.pointerEvents).toBe('auto')
  })

  it('探针按钮不存在时如实报 found:false，不编造坐标', () => {
    place('<div></div>')
    const rows = hitTest()
    expect(rows).toHaveLength(HIT_TEST_PROBES.length)
    expect(rows.every(row => row.found === false && row.point === null && row.hitSelf === false)).toBe(true)
  })

  it('一次打四个点，每个点一行 [hit-test]', () => {
    place('<div class="titlebar-right"><button data-rect="0,0,10,10">a</button><button data-rect="0,12,10,10">b</button><button data-rect="0,24,10,10">c</button></div><button data-browser-more data-rect="0,40,10,10">more</button>')
    document.elementFromPoint = vi.fn(() => null) as never
    const log = vi.fn()
    const rows = logHitTest(document, log)
    expect(rows).toHaveLength(4)
    expect(log).toHaveBeenCalledTimes(4)
    expect(log.mock.calls[0][0]).toBe('[hit-test]')
  })

  it('快捷键只在 Ctrl+Alt+Shift+H 上触发一次', () => {
    place('<div class="titlebar-right"><button data-rect="0,0,10,10">a</button></div>')
    document.elementFromPoint = vi.fn(() => null) as never
    const log = vi.fn()
    const stop = installHitTestShortcut(document, log)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'h', ctrlKey: true, altKey: true, shiftKey: true }))
    expect(log).toHaveBeenCalled()
    const before = log.mock.calls.length
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'h', ctrlKey: true, altKey: true }))
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', ctrlKey: true, altKey: true, shiftKey: true }))
    expect(log.mock.calls.length).toBe(before)
    stop()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'h', ctrlKey: true, altKey: true, shiftKey: true }))
    expect(log.mock.calls.length).toBe(before)
  })

  it('元素描述与层级路径可读', () => {
    place('<div id="shell" class="workspace-shell"><div class="split-workspace"><button class="split-icon-button more">x</button></div></div>')
    const button = document.querySelector('button')!
    expect(describeElement(button)).toBe('button.split-icon-button.more')
    // elementPath 从上往下排（html → body → … → 被点的元素）：路径里必须能认出 shell。
    const path = elementPath(button)
    expect(path.some(step => step.includes('workspace-shell'))).toBe(true)
    expect(path.at(-1)).toContain('split-icon-button')
    expect(describeElement(null)).toBe('null')
  })
})

// user:“测试：给受影响的容器补 pointer-events 断言（能测的用 jsdom 断言类/样式）”+
// (这几条是本次 DOM 审计的结论固化：它们必须是 none，否则容器盒子会替页面吃点击)。
describe('全屏容器不吃点击（回归锁）', () => {
  const cases: Array<[string, RegExp]> = [
    ['../src/styles/layout.css', /\.core-toast-host\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/layout.css', /\.workspace-runtime-overlay\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/split-workspace.css', /\.split-workspace\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/split-workspace.css', /\.split-workspace--open::after\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/split-workspace.css', /\.split-fold-notice\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/split-workspace.css', /\.split-focus-hint\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/split-workspace.css', /\.split-resize-chip\s*\{[^}]*pointer-events:\s*none/],
    ['../src/styles/workspace-shell.css', /\.session-fusion\s*\{[^}]*pointer-events:\s*none/],
  ]
  for (const [file, pattern] of cases) {
    it(`${file.split('/').pop()} 的容器写了 pointer-events: none`, () => {
      expect(read(file)).toMatch(pattern)
    })
  }
})

// user:“日志只打一次关键行 + 变化时才打…按 name + owner + hitSelf 做指纹，变化才打；每次带一个自增 seq”
describe('自动取证：指纹去重与 seq', () => {
  const stand = () => place('<div class="titlebar-right"><button data-rect="0,0,10,10">a</button><button data-rect="0,12,10,10">b</button><button data-rect="0,24,10,10">c</button></div><button data-browser-more data-rect="0,40,10,10">more</button>')

  it('同一组命中结果重报不打印；换一个 owner 才打印，且 seq 自增', () => {
    stand()
    document.elementFromPoint = vi.fn(() => document.querySelector('button')) as never
    const log = vi.fn()
    const reporter = createHitTestReporter({ log, doc: document })
    const first = reporter.report('mount')
    expect(first.printed).toBe(true)
    expect(first.seq).toBe(1)
    expect(log).toHaveBeenCalledTimes(4)
    expect(log.mock.calls[0][1]).toMatchObject({ seq: 1, reason: 'mount' })
    // 同结果再来一次：不打
    expect(reporter.report('resize').printed).toBe(false)
    expect(log).toHaveBeenCalledTimes(4)
    // owner 变了：打，seq=2
    document.elementFromPoint = vi.fn(() => document.querySelector('.titlebar-right')) as never
    const third = reporter.report('layout')
    expect(third.printed).toBe(true)
    expect(third.seq).toBe(2)
    expect(log).toHaveBeenCalledTimes(8)
  })

  it('失败现场可以强制打印（force），不被去重吞掉', () => {
    stand()
    document.elementFromPoint = vi.fn(() => document.querySelector('button')) as never
    const log = vi.fn()
    const reporter = createHitTestReporter({ log, doc: document })
    reporter.report('mount')
    expect(reporter.report('more-menu-not-open', { force: true }).printed).toBe(true)
    expect(log).toHaveBeenCalledTimes(8)
  })

  it('指纹只由 name/owner/hitSelf 组成，坐标变化不算变化', () => {
    const row = (hitSelf: boolean, owner = 'button.a') => ({ name: 'x', found: true, point: { x: 1, y: 2 }, owner, path: [], hitSelf, pointerEvents: 'auto', zIndex: 'auto' })
    expect(fingerprintRows([row(true)])).toBe(fingerprintRows([{ ...row(true), point: { x: 99, y: 99 } }]))
    expect(fingerprintRows([row(true)])).not.toBe(fingerprintRows([row(false)]))
  })
})

describe('自动触发点：挂载 1 秒 + 去抖 + resize', () => {
  const stand = () => place('<div class="titlebar-right"><button data-rect="0,0,10,10">a</button></div>')

  it('挂载后自动报一次（dev 启动即有四条探针，无需用户操作）', () => {
    vi.useFakeTimers()
    stand()
    document.elementFromPoint = vi.fn(() => document.querySelector('button')) as never
    const log = vi.fn()
    const auto = createAutoHitTest({ log, doc: document, debounceMs: 200, mountDelayMs: 1000 })
    vi.advanceTimersByTime(999)
    expect(log).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(log).toHaveBeenCalledTimes(HIT_TEST_PROBES.length)
    auto.stop()
  })

  it('连续 nudge 只报一次（200ms 去抖合并）', () => {
    vi.useFakeTimers()
    stand()
    document.elementFromPoint = vi.fn(() => document.querySelector('button')) as never
    const log = vi.fn()
    const auto = createAutoHitTest({ log, doc: document, debounceMs: 200, mountDelayMs: 100000 })
    auto.nudge('layout'); auto.nudge('layout'); auto.nudge('surface')
    vi.advanceTimersByTime(200)
    expect(log).toHaveBeenCalledTimes(HIT_TEST_PROBES.length)
    auto.stop()
  })

  it('resize 走同一条去抖通道；stop 之后不再报', () => {
    vi.useFakeTimers()
    stand()
    document.elementFromPoint = vi.fn(() => document.querySelector('button')) as never
    const log = vi.fn()
    const auto = createAutoHitTest({ log, doc: document, debounceMs: 200, mountDelayMs: 100000 })
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(200)
    expect(log).toHaveBeenCalledTimes(HIT_TEST_PROBES.length)
    auto.stop()
    window.dispatchEvent(new Event('resize'))
    vi.advanceTimersByTime(200)
    expect(log).toHaveBeenCalledTimes(HIT_TEST_PROBES.length)
  })
})

describe('「更多」失败现场：点击被吃', () => {
  const stand = () => place([
    '<div class="split-content-toolbar"><button data-browser-more data-rect="100,100,28,24">more</button></div>',
    '<div class="split-fold-strip" data-rect="100,100,28,24"></div>',
  ].join(''))

  it('点击落在按钮矩形内、但事件目标是别人 → 当场报出 owner 与 path', () => {
    stand()
    const stolen: any[] = []
    const stop = installStealProbe({ selector: '[data-browser-more]', doc: document, onSteal: info => stolen.push(info) })
    const cover = document.querySelector('.split-fold-strip')!
    cover.dispatchEvent(new PointerEvent('pointerdown', { clientX: 110, clientY: 110, bubbles: true }))
    expect(stolen).toHaveLength(1)
    expect(stolen[0].owner).toContain('split-fold-strip')
    expect(stolen[0].path.at(-1)).toContain('split-fold-strip')
    expect(stolen[0].point).toEqual({ x: 110, y: 110 })
    stop()
  })

  it('点击真的落在按钮上时不误报；落在按钮矩形外也不报', () => {
    stand()
    const stolen: any[] = []
    const stop = installStealProbe({ selector: '[data-browser-more]', doc: document, onSteal: info => stolen.push(info) })
    document.querySelector('button')!.dispatchEvent(new PointerEvent('pointerdown', { clientX: 110, clientY: 110, bubbles: true }))
    document.body.dispatchEvent(new PointerEvent('pointerdown', { clientX: 5, clientY: 5, bubbles: true }))
    expect(stolen).toHaveLength(0)
    stop()
  })
})

// user:“自动触发只在 dev 生效”+(打包版一条日志都不打：开关只看 import.meta.env.DEV)。
describe('dev 开关', () => {
  it('只有 DEV 为真才启用自动取证', () => {
    expect(autoHitTestEnabled({ DEV: true })).toBe(true)
    expect(autoHitTestEnabled({ DEV: false })).toBe(false)
    expect(autoHitTestEnabled({})).toBe(false)
  })
})

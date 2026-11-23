/**
 * dev-only 命中测试诊断：**点击到底落在谁身上**。
 *
 * user:“加一条 dev-only 的命中测试诊断——在标题栏最大/最小按钮中心、页眉「更多」按钮中心各取坐标，
 * 用 document.elementFromPoint(x, y) 打一条 [hit-test] 日志（含命中的元素类名与层级路径），
 * 并支持用一个临时键盘快捷键触发一次（仅 dev）”+
 * (原生 webview 已经被 Rust 侧证明不重叠，那就只能是 DOM 里某层把点击吃掉了。
 *  这条诊断不做任何推断：它只回答“这个坐标上最上层的元素是谁、它的 pointer-events / z-index 是多少”。
 *  快捷键：Ctrl+Alt+Shift+H，只在开发版接线。)
 */

export interface HitProbe { name: string; selector: string }

/**
 * 要验的四个点：窗口三键 + 页眉「更多」。
 *
 * user:“把 name:"titlebar-min" | "titlebar-max" | "titlebar-close" 那几行的 owner、hitSelf、point、path 原样贴出来”+
 * (第一版探针用 `nth-last-of-type` 选 `.titlebar-right button`，实测命中的是 `.titlebar-sidebar-controls`
 *  里的置顶按钮（`button.pin-btn`）——同父同类型计数会跨进别的容器，选错人。窗口三键的真实结构是
 *  `div.window-controls > button.ctrl-btn`，这里按 `:nth-of-type` 精确锁定，顺序与 TitleBar 模板一致)。
 */
export const HIT_TEST_PROBES: HitProbe[] = [
  { name: 'titlebar-min', selector: '.window-controls > button.ctrl-btn:nth-of-type(1)' },
  { name: 'titlebar-max', selector: '.window-controls > button.ctrl-btn:nth-of-type(2)' },
  { name: 'titlebar-close', selector: '.window-controls > button.ctrl-btn:nth-of-type(3)' },
  { name: 'browser-more', selector: '[data-browser-more]' },
]

export const HIT_TEST_SHORTCUT = { key: 'h', ctrl: true, alt: true, shift: true } as const

function resolveDoc(doc: Document | null | undefined): Document | null {
  if (doc) return doc
  return typeof document === 'undefined' ? null : document
}

/** `div.foo.bar#id` —— 只留前四个类名，够认人又不刷屏。 */
export function describeElement(element: Element | null): string {
  if (!element) return 'null'
  const id = element.id ? `#${element.id}` : ''
  const classes = Array.from(element.classList).slice(0, 4).map(name => `.${name}`).join('')
  return `${element.tagName.toLowerCase()}${id}${classes}`
}

/** 从命中的元素往上数到 body：给出一条能直接照着查的层级路径。 */
export function elementPath(element: Element | null, limit = 8): string[] {
  const path: string[] = []
  let node: Element | null = element
  while (node && path.length < limit) {
    path.unshift(describeElement(node))
    node = node.parentElement
  }
  return path
}

export interface HitReport {
  name: string
  /** 探针按钮本身在不在。 */
  found: boolean
  /** 取的是按钮中心坐标（CSS px，视口坐标）。 */
  point: { x: number; y: number } | null
  /** 该坐标上最上层的元素。 */
  owner: string
  /** 命中元素的层级路径。 */
  path: string[]
  /** 命中的是不是按钮自己/它的子节点 —— 为 false 就说明点击被别人吃了。 */
  hitSelf: boolean
  pointerEvents: string
  zIndex: string
}

export function hitTest(probes: readonly HitProbe[] = HIT_TEST_PROBES, doc?: Document | null): HitReport[] {
  const host = resolveDoc(doc)
  if (!host) return []
  const empty = (name: string): HitReport => ({ name, found: false, point: null, owner: 'null', path: [], hitSelf: false, pointerEvents: '', zIndex: '' })
  return probes.map(probe => {
    const button = host.querySelector(probe.selector)
    if (!button) return empty(probe.name)
    const rect = button.getBoundingClientRect()
    const point = { x: Math.round(rect.x + rect.width / 2), y: Math.round(rect.y + rect.height / 2) }
    const target = typeof host.elementFromPoint === 'function' ? host.elementFromPoint(point.x, point.y) : null
    const style = target ? host.defaultView?.getComputedStyle(target) ?? null : null
    return {
      name: probe.name,
      found: true,
      point,
      owner: describeElement(target),
      path: elementPath(target),
      hitSelf: Boolean(target) && (target === button || button.contains(target as Node)),
      pointerEvents: style?.pointerEvents || '',
      zIndex: style?.zIndex || '',
    }
  })
}

/** 打一条 `[hit-test]`：一次四个点，每个点一行，字段完全一致，方便直接贴回来对比。 */
export function logHitTest(doc?: Document | null, log: (label: string, payload: unknown) => void = console.warn): HitReport[] {
  const report = hitTest(HIT_TEST_PROBES, doc)
  for (const row of report) log('[hit-test]', row)
  return report
}

/** 开发版接线：Ctrl+Alt+Shift+H 触发一次；返回解绑函数。 */
export function installHitTestShortcut(doc?: Document | null, log?: (label: string, payload: unknown) => void): () => void {
  const host = resolveDoc(doc)
  if (!host) return () => {}
  const onKey = (event: KeyboardEvent) => {
    if (!event.ctrlKey || !event.altKey || !event.shiftKey) return
    if (event.key.toLowerCase() !== HIT_TEST_SHORTCUT.key) return
    event.preventDefault()
    logHitTest(host, log)
  }
  host.addEventListener('keydown', onKey, true)
  return () => host.removeEventListener('keydown', onKey, true)
}

/** 指纹：同一组探针的命中结果没变就不重复打印。 */
export function fingerprintRows(rows: readonly HitReport[]): string {
  return rows.map(row => `${row.name}|${row.owner}|${row.hitSelf}`).join(' && ')
}

/** 开发版开关：只有 dev 才自动取证（打包版一条日志都不打）。 */
export function autoHitTestEnabled(env: { DEV?: boolean } | undefined = (import.meta as { env?: { DEV?: boolean } }).env): boolean {
  return Boolean(env?.DEV)
}

export interface HitTestReporter {
  /** reason 写进日志，方便把时间线对上；force=true 时不走去重（失败现场必须留痕）。 */
  report(reason: string, options?: { force?: boolean; doc?: Document | null }): { seq: number; printed: boolean; fingerprint: string }
  /** 当前指纹（测试与去重判断用）。 */
  fingerprint(doc?: Document | null): string
}

/**
 * user:“日志只打一次关键行 + 变化时才打…按 name + owner + hitSelf 做指纹，变化才打；每次带一个自增 seq”+
 * (dev 里布局一抖就会连着命中同一批元素，重复行没有信息量，还会把真正的变化淹掉)。
 */
export function createHitTestReporter(options: {
  log?: (label: string, payload: unknown) => void
  doc?: Document | null
} = {}): HitTestReporter {
  const log = options.log ?? console.warn
  let seq = 0
  let last = ''
  const fingerprint = (doc?: Document | null) => fingerprintRows(hitTest(HIT_TEST_PROBES, doc ?? options.doc))
  return {
    fingerprint,
    report(reason, reportOptions = {}) {
      const rows = hitTest(HIT_TEST_PROBES, reportOptions.doc ?? options.doc)
      const next = fingerprintRows(rows)
      if (!reportOptions.force && next === last) return { seq, printed: false, fingerprint: next }
      last = next
      seq += 1
      for (const row of rows) log('[hit-test]', { seq, reason, ...row })
      return { seq, printed: true, fingerprint: next }
    },
  }
}

export interface AutoHitTest {
  /** 去抖后报一次（布局类触发都走这条）。 */
  nudge: (reason: string) => void
  /** 立刻报一次（失败现场用，不走去抖也不去重）。 */
  reportNow: (reason: string) => void
  stop: () => void
}

/**
 * user:“自动触发点（都加 200ms 去抖）：挂载后 1 秒；分屏开/合、主内容切换、聚焦全屏/浮窗切换之后；
 * 窗口 resize 结束；以及用户点「更多」但菜单没有打开时”+
 * (dev 跑起来不需要用户操作就能看到四条探针；之后只在结果变化时补一条)。
 */
export function createAutoHitTest(options: {
  doc?: Document | null
  log?: (label: string, payload: unknown) => void
  debounceMs?: number
  mountDelayMs?: number
} = {}): AutoHitTest {
  const host = resolveDoc(options.doc)
  const reporter = createHitTestReporter({ log: options.log, doc: host })
  const debounceMs = options.debounceMs ?? 200
  const mountDelayMs = options.mountDelayMs ?? 1000
  let timer: ReturnType<typeof setTimeout> | null = null
  let mountTimer: ReturnType<typeof setTimeout> | null = null
  let stopped = false
  const nudge = (reason: string) => {
    if (stopped || !host) return
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => { timer = null; reporter.report(reason) }, debounceMs)
  }
  const onResize = () => nudge('resize')
  host?.defaultView?.addEventListener('resize', onResize)
  if (host) mountTimer = setTimeout(() => { mountTimer = null; reporter.report('mount') }, mountDelayMs)
  return {
    nudge,
    reportNow(reason) { if (!stopped) reporter.report(reason, { force: true }) },
    stop() {
      stopped = true
      if (timer) clearTimeout(timer)
      if (mountTimer) clearTimeout(mountTimer)
      timer = null; mountTimer = null
      host?.defaultView?.removeEventListener('resize', onResize)
    },
  }
}

/**
 * user:“用户点「更多」但菜单没有打开时（这是最关键的失败现场）”+
 * (如果点击被别人吃掉，`toggleMoreMenu` 根本不会执行，任何组件内的自检都无从触发；
 *  所以这里在 pointerdown 捕获阶段比对坐标：落点在这枚按钮的矩形内、但事件目标不是它 →
 *  就是有人压在按钮上，当场把 elementFromPoint 的 owner 与层级路径抓下来)。
 */
export interface StealInfo {
  selector: string
  point: { x: number; y: number }
  owner: string
  path: string[]
  pointerEvents: string
  zIndex: string
}

export function installStealProbe(options: {
  selector: string
  onSteal: (info: StealInfo) => void
  doc?: Document | null
}): () => void {
  const host = resolveDoc(options.doc)
  if (!host) return () => {}
  const onPointerDown = (event: Event) => {
    const button = host.querySelector(options.selector)
    if (!button) return
    const rect = button.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const source = event as PointerEvent
    const x = Math.round(source.clientX ?? 0)
    const y = Math.round(source.clientY ?? 0)
    if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) return
    const target = source.target instanceof Element ? source.target : null
    if (target && (target === button || button.contains(target))) return
    const style = target ? host.defaultView?.getComputedStyle(target) ?? null : null
    options.onSteal({
      selector: options.selector,
      point: { x, y },
      owner: describeElement(target),
      path: elementPath(target),
      pointerEvents: style?.pointerEvents || '',
      zIndex: style?.zIndex || '',
    })
  }
  host.addEventListener('pointerdown', onPointerDown, true)
  return () => host.removeEventListener('pointerdown', onPointerDown, true)
}

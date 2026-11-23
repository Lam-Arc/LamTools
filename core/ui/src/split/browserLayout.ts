/**
 * 原生 webview 落点的不变量：**网页矩形必须完全落在所属 pane 的内容区内**。
 *
 * user:“落点矩形必须满足不变量：完全落在所属 pane 的内容区内（不含标签栏、不含页眉、不与标题栏相交）”+
 * (原生 webview 是独立层，画在 DOM 之上：它一旦超出内容区，超出多少就吃掉多少点击。
 *  超出到页眉 → 「更多」点不动；超出到标题栏 → 最大化/最小化点不动。两条症状是同一个越界。
 *  所以判定不能写成“再减一点”，而要写成一条可以单测证伪的包含关系。
 *
 * 说明：这里只用 CSS px 做几何判断。物理像素换算仍然只有一处 —— split/native.ts::boundsArgs（乘 dpr），
 * 本文件不参与运行时换算，只在诊断/单测里复算同一个乘法来验证“物理矩形也包含在内”。
 */

export interface SplitRect { x: number; y: number; width: number; height: number }

/** pane 的内容区：pane 矩形扣掉它自己的标签栏（标签栏不是内容，也不许被网页盖住）。 */
export function paneContentRect(pane: SplitRect, tabBarHeight: number): SplitRect {
  const trim = Math.max(0, tabBarHeight)
  return {
    x: pane.x,
    y: pane.y + trim,
    width: Math.max(0, pane.width),
    height: Math.max(0, pane.height - trim),
  }
}

const EPSILON = 0.5

/** 内层是否完全落在外层之内（容忍半个像素的取整误差）。 */
export function containsRect(outer: SplitRect, inner: SplitRect): boolean {
  return inner.x >= outer.x - EPSILON
    && inner.y >= outer.y - EPSILON
    && inner.x + inner.width <= outer.x + outer.width + EPSILON
    && inner.y + inner.height <= outer.y + outer.height + EPSILON
}

/** 越界了多少（超过半个像素才算，返回四个方向的超出量，便于日志定位）。 */
export function rectOverflow(outer: SplitRect, inner: SplitRect): { top: number; left: number; right: number; bottom: number } {
  return {
    top: Math.max(0, outer.y - inner.y),
    left: Math.max(0, outer.x - inner.x),
    right: Math.max(0, (inner.x + inner.width) - (outer.x + outer.width)),
    bottom: Math.max(0, (inner.y + inner.height) - (outer.y + outer.height)),
  }
}

/**
 * user:“若根因是主槽位把 rect 放大到全窗口，就修那条取值路径，不要用「再减一点」的方式打补丁”+
 * (所以这里是**求交**：超出内容区的部分一律不算，交集为空就退化成 1×1 并不可见。
 *  它不是“减一点”，而是把不变量本身当成取值的定义——上游算错多少都会被这条收住)。
 */
export function fitRectToContent(host: SplitRect | null, content: SplitRect | null): { rect: SplitRect; clamped: boolean } | null {
  if (!host || !content) return null
  const left = Math.max(host.x, content.x)
  const top = Math.max(host.y, content.y)
  const right = Math.min(host.x + host.width, content.x + content.width)
  const bottom = Math.min(host.y + host.height, content.y + content.height)
  const width = Math.max(0, right - left)
  const height = Math.max(0, bottom - top)
  const clamped = !containsRect(content, host)
  // 交集为空：这块屏现在没有地方画网页，交给 resolveBrowserBounds 判成“不可见”。
  if (width < 1 || height < 1) return { rect: { x: Math.round(left), y: Math.round(top), width: 0, height: 0 }, clamped: true }
  return { rect: { x: left, y: top, width, height }, clamped }
}

/** 与 native.ts::boundsArgs 同一个乘法（仅用于诊断/单测复算，运行时不经过这里）。 */
export function toPhysical(rect: SplitRect, dpr: number): SplitRect {
  const factor = dpr || 1
  const edge = (value: number) => Math.round(value * factor)
  // user:“1.5/1.85 缩放也要成立”+(两条矩形共享的那条边必须用同一个取整方式，
  //  否则各自 round 会把 1px 的误差变成“越界”。这里按边取整，包含关系在物理空间里与 CSS 空间一致)。
  const x = edge(rect.x)
  const y = edge(rect.y)
  return {
    x,
    y,
    width: Math.max(1, edge(rect.x + rect.width) - x),
    height: Math.max(1, edge(rect.y + rect.height) - y),
  }
}

/**
 * user:“落点不变量：网页矩形必须完全落在 pane 的内容区内”+(V2-B：
 * `clampToHost` 是唯一收敛点——越界就求交并报 overflow，调用方据此记录/报警；
 * `assertInsideHost` 供单测与诊断断言，不改变输入。)
 */
export function clampToHost(contentRect: SplitRect, host: SplitRect): { rect: SplitRect; overflow: { top: number; left: number; right: number; bottom: number } | null } {
  if (containsRect(host, contentRect)) return { rect: contentRect, overflow: null }
  const left = Math.max(host.x, contentRect.x)
  const top = Math.max(host.y, contentRect.y)
  const right = Math.min(host.x + host.width, contentRect.x + contentRect.width)
  const bottom = Math.min(host.y + host.height, contentRect.y + contentRect.height)
  const width = Math.max(0, right - left)
  const height = Math.max(0, bottom - top)
  // 交集为空：这块屏没有地方画网页（上层按 width/height < 1 判成不可见）。
  const rect = width < 1 || height < 1
    ? { x: Math.round(left), y: Math.round(top), width: 0, height: 0 }
    : { x: left, y: top, width, height }
  return { rect, overflow: rectOverflow(host, contentRect) }
}

/** 严格包含（容半个像素取整误差）：给断言/诊断用，不做任何修正。 */
export function assertInsideHost(contentRect: SplitRect, host: SplitRect): boolean {
  return containsRect(host, contentRect)
}

/**
 * user:“dev-only 节流日志（1 秒/pane，字段 pane/rect/host/overflow/dpr）”+
 * (真机上布局每帧都在抖，不节流会把日志淹掉；同一 pane 1 秒最多一条，
 *  并带上被折掉的 count。生产构建（非 DEV）完全静默。)
 */
export function createRectDiagnostics(windowMs = 1000) {
  const throttle = createLogThrottle(windowMs)
  return function report(input: { pane: string; rect: SplitRect; host: SplitRect; dpr: number }): void {
    if (!import.meta.env.DEV) return
    const gate = throttle(input.pane)
    if (!gate.log) return
    const inside = assertInsideHost(input.rect, input.host)
    console.info('[webview-rect]', JSON.stringify({
      pane: input.pane,
      rect: input.rect,
      host: input.host,
      overflow: inside ? null : rectOverflow(input.host, input.rect),
      dpr: input.dpr,
      count: gate.count,
    }))
  }
}

export interface RectCheck {
  ok: boolean
  /** 越界了哪几条边（CSS px）。 */
  overflow: { top: number; left: number; right: number; bottom: number }
  /** 物理像素下复算一次：containment 必须在物理空间里也成立。 */
  physicalOk: boolean
}

/** 一条可用于日志/断言的整体判定。 */
export function checkBrowserRect(browser: SplitRect, content: SplitRect, dpr = 1): RectCheck {
  return {
    ok: containsRect(content, browser),
    overflow: rectOverflow(content, browser),
    physicalOk: containsRect(toPhysical(content, dpr), toPhysical(browser, dpr)),
  }
}

/**
 * user:“不变量日志别只在 dev 打一次…改成按 trace/按 pane 节流（同一 pane 1 秒最多 1 条，并带 count）”+
 * (布局抖动时这条会连发几十行，真机上抓日志会被它淹掉。内容不变，只是把一秒内被折掉的次数带出来)。
 */
export function createLogThrottle(windowMs = 1000) {
  const seen = new Map<string, { at: number; count: number }>()
  return function shouldLog(key: string, now = Date.now()): { log: boolean; count: number } {
    const entry = seen.get(key)
    if (entry && now - entry.at < windowMs) {
      entry.count += 1
      return { log: false, count: entry.count }
    }
    const carried = entry?.count ?? 0
    seen.set(key, { at: now, count: 0 })
    return { log: true, count: carried + 1 }
  }
}

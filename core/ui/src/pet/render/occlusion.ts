/**
 * 局部遮挡：把真实窗口矩形从覆盖层里"挖掉"。
 *
 * user:“研究并实现尽可能可靠的局部遮挡或裁剪方案，使桌宠能够自然地出现在窗口
 * 前方、后方及边缘”+
 * (单窗口做不到逐像素 Z 序混合，但可以在置顶模式下按真实窗口几何把宠物那一片
 *  裁掉，视觉上就是"被窗口挡住"，而卡片、气泡、Ping 轮盘仍留在窗口之上。)
 *
 * 这里只产出遮罩描述，不碰 DOM：坐标换算与矩形裁剪都能单测。
 */

export interface ScreenRect {
  x: number
  y: number
  width: number
  height: number
}

export interface Rect {
  x: number
  y: number
  width: number
  height: number
}

function intersect(region: Rect, rect: Rect): Rect | null {
  const left = Math.max(region.x, rect.x)
  const top = Math.max(region.y, rect.y)
  const right = Math.min(region.x + region.width, rect.x + rect.width)
  const bottom = Math.min(region.y + region.height, rect.y + rect.height)
  if (right - left < 2 || bottom - top < 2) return null
  return { x: left, y: top, width: right - left, height: bottom - top }
}

/**
 * 需要挖掉的洞（已裁剪到覆盖层内、转成相对坐标）。
 * 完全覆盖整块区域的洞会被单独标记：那种情况下整层都该隐藏。
 */
export function occlusionHoles(
  region: Rect,
  windows: ScreenRect[],
  overlay: { x: number; y: number; width: number; height: number },
): { holes: Rect[]; coversAll: boolean } {
  const holes: Rect[] = []
  let coveredArea = 0
  for (const window of windows) {
    const clamped = intersect(region, window)
    if (!clamped) continue
    coveredArea += clamped.width * clamped.height
    holes.push({
      x: clamped.x - region.x,
      y: clamped.y - region.y,
      width: clamped.width,
      height: clamped.height,
    })
  }
  void overlay
  return {
    holes,
    coversAll: coveredArea >= region.width * region.height * 0.995,
  }
}

/**
 * 生成可直接用于 CSS `mask-image` 的内联 SVG。
 *
 * 用 SVG 的 evenodd 挖洞，而不是 CSS `clip-path: path()`：后者不接受
 * fill-rule 参数，polygon 又表达不了"带洞"的区域。SVG 遮罩在 Chromium 里
 * 稳定，且能按 viewBox 自动缩放到元素尺寸。
 */
export function maskSvgUrl(region: Rect, windows: ScreenRect[]): string {
  const { holes, coversAll } = occlusionHoles(region, windows, {
    x: region.x,
    y: region.y,
    width: region.width,
    height: region.height,
  })
  const width = Math.max(1, Math.round(region.width))
  const height = Math.max(1, Math.round(region.height))
  if (holes.length === 0) return ''
  if (coversAll) {
    // 全被挡住：给一张全黑遮罩，等价于整层隐藏。
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><rect width="${width}" height="${height}" fill="#000"/></svg>`
    return toDataUrl(svg)
  }
  const holePaths = holes
    .map(hole => `M${round(hole.x)} ${round(hole.y)}h${round(hole.width)}v${round(hole.height)}h${round(-hole.width)}Z`)
    .join('')
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><path fill="#fff" fill-rule="evenodd" d="M0 0h${width}v${height}h${round(-width)}Z${holePaths}"/></svg>`
  return toDataUrl(svg)
}

function round(value: number): number {
  return Math.round(value * 100) / 100
}

function toDataUrl(svg: string): string {
  // 只转义会破坏 CSS url() 的字符，保持可读性方便排查。
  const encoded = svg
    .replace(/"/g, "'")
    .replace(/#/g, '%23')
    .replace(/</g, '%3C')
    .replace(/>/g, '%3E')
    .replace(/\s+/g, ' ')
  return `data:image/svg+xml;charset=utf-8,${encoded}`
}

/**
 * 覆盖层里哪些矩形需要参与遮挡计算。
 * 只裁剪宠物画布：卡片、气泡、轮盘必须继续显示在窗口之上。
 */
export function shouldMaskPets(zMode: string, holesCount: number): boolean {
  return zMode === 'clip' && holesCount > 0
}

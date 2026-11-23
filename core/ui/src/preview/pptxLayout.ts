/**
 * PPTX 版式解析：把一份演示文稿读成可以按比例画出来的幻灯片模型。
 *
 * user:“这要求每个客户端都要有LibreOffice吗？”+
 * (不。转换器只能当“可选增强”，不能成为正常预览的前提。这里自己读 OOXML：
 *  幻灯片里的占位符没有坐标与字号，得顺着 版式 → 母版 → 主题 继承出来，
 *  再把位置、旋转、形状、填充、文字、图片、表格整理成可直接绘制的数据。
 *  渲染层只做绝对定位与按宽度等比缩放，不再需要任何外部程序。)
 *
 * 覆盖范围（预览够用）：占位符继承、位置/尺寸/旋转、常见预设形状、纯色与渐变填充、
 * 描边、多段多 run 文字（字号/粗斜体/下划线/颜色/字体/对齐/级别/项目符号/行距/段距）、
 * 背景、图片、表格、组合。
 */
export interface PptxTextRun {
  text: string
  size?: number
  bold?: boolean
  italic?: boolean
  underline?: boolean
  color?: string
  font?: string
}

export interface PptxParagraph {
  runs: PptxTextRun[]
  align: 'left' | 'center' | 'right' | 'justify'
  level: number
  bullet: string
  size?: number
  color?: string
  /** 段落左边距与首行缩进，单位 pt（负数 = 悬挂缩进，项目符号就落在左边距上）。 */
  marginLeft: number
  indent: number
  spaceBefore: number
  spaceAfter: number
  lineHeight?: number
}

export interface PptxTextBody {
  paragraphs: PptxParagraph[]
  anchor: 'top' | 'middle' | 'bottom'
  inset: { top: number; right: number; bottom: number; left: number }
  wrap: boolean
}

export interface PptxTableCell {
  text?: PptxTextBody
  gridSpan: number
  fill?: string
}

export interface PptxTable {
  columns: number[]
  rows: { height: number; cells: PptxTableCell[] }[]
}

export interface PptxShape {
  kind: 'shape' | 'text' | 'image' | 'table'
  key: string
  name?: string
  x: number
  y: number
  w: number
  h: number
  rotation?: number
  geometry?: string
  fill?: string
  gradient?: string
  line?: { color: string; width: number }
  text?: PptxTextBody
  image?: { url: string }
  table?: PptxTable
}

export interface PptxSlide {
  index: number
  title: string
  background?: string
  shapes: PptxShape[]
}

export interface PptxDeck {
  width: number
  height: number
  slides: PptxSlide[]
}

const EMU_PER_PT = 12700
const DEFAULT_INSET = { left: 91440, top: 45720, right: 91440, bottom: 45720 }
const EMU_PER_PX = 9525

type XmlElement = Element

/** OOXML 的元素名带前缀（p:/a:/r:），比较时统一去掉，避免到处写两种写法。 */
function tag(node: Element): string {
  return node.tagName.replace(/^[^:]+:/, '')
}

function parseXml(bytes: Uint8Array | undefined): Document | null {
  if (!bytes) return null
  const text = new TextDecoder('utf-8').decode(bytes)
  const document_ = new DOMParser().parseFromString(text, 'application/xml')
  return document_.documentElement?.nodeName === 'parsererror' ? null : document_
}

const kids = (node: Element | null | undefined, name: string): Element[] =>
  node ? Array.from(node.children).filter(child => tag(child) === name) : []

const kid = (node: Element | null | undefined, name: string): Element | null =>
  node ? Array.from(node.children).find(child => tag(child) === name) ?? null : null

const attr = (node: Element | null | undefined, name: string): string => node?.getAttribute(name) ?? ''

const num = (node: Element | null | undefined, name: string, fallback = 0): number => {
  const raw = node?.getAttribute(name)
  if (raw == null || raw === '') return fallback
  const value = Number(raw)
  return Number.isFinite(value) ? value : fallback
}

/** 按标签名找后代（不带前缀，内部改用 localName 匹配）。 */
function descendants(node: Element | null | undefined, name: string): Element[] {
  if (!node) return []
  return Array.from(node.getElementsByTagName('*')).filter(child => tag(child) === name)
}

function firstDescendant(node: Element | null | undefined, name: string): Element | null {
  return descendants(node, name)[0] ?? null
}

const emuToPoints = (emu: number): number => emu / EMU_PER_PT

function hexToRgb(hex: string): [number, number, number] {
  const value = hex.replace('#', '')
  const full = value.length === 3 ? value.split('').map(char => char + char).join('') : value.padEnd(6, '0')
  return [parseInt(full.slice(0, 2), 16) || 0, parseInt(full.slice(2, 4), 16) || 0, parseInt(full.slice(4, 6), 16) || 0]
}

function rgbToHex([red, green, blue]: [number, number, number]): string {
  const clamp = (value: number) => Math.max(0, Math.min(255, Math.round(value)))
  return '#' + [red, green, blue].map(value => clamp(value).toString(16).padStart(2, '0')).join('')
}

/** PowerPoint 的 lumMod/lumOff 作用在 HSL 明度上，不是 RGB 加法。 */
function shiftLightness(hex: string, mod: number, off: number): string {
  const [r255, g255, b255] = hexToRgb(hex)
  const red = r255 / 255, green = g255 / 255, blue = b255 / 255
  const max = Math.max(red, green, blue), min = Math.min(red, green, blue)
  const delta = max - min
  const lightness = Math.max(0, Math.min(1, ((max + min) / 2) * mod + off))
  const saturation = delta === 0 ? 0 : delta / (1 - Math.abs(2 * ((max + min) / 2) - 1))
  if (delta === 0) {
    const level = Math.round(lightness * 255)
    return rgbToHex([level, level, level])
  }
  let hue = max === red ? ((green - blue) / delta) % 6 : max === green ? (blue - red) / delta + 2 : (red - green) / delta + 4
  hue = ((hue * 60) % 360 + 360) % 360
  const chroma = (1 - Math.abs(2 * lightness - 1)) * saturation
  const x = chroma * (1 - Math.abs(((hue / 60) % 2) - 1))
  const m = lightness - chroma / 2
  const [r, g, b] = hue < 60 ? [chroma, x, 0]
    : hue < 120 ? [x, chroma, 0]
      : hue < 180 ? [0, chroma, x]
        : hue < 240 ? [0, x, chroma]
          : hue < 300 ? [x, 0, chroma]
            : [chroma, 0, x]
  return rgbToHex([(r + m) * 255, (g + m) * 255, (b + m) * 255])
}

function toRgba(hex: string, alpha: number): string {
  const [red, green, blue] = hexToRgb(hex)
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`
}

type ThemeColors = Record<string, string>

/** 颜色解析：srgbClr / sysClr / schemeClr / prstClr，再套 lumMod、lumOff、alpha。 */
function colorOf(node: Element | null, theme: ThemeColors): string | undefined {
  const colorNode = node ? Array.from(node.children).find(child => /Clr$/.test(tag(child))) : null
  if (!colorNode) return undefined
  const kind = tag(colorNode)
  let base: string | undefined
  if (kind === 'srgbClr') base = '#' + (colorNode.getAttribute('val') || '000000')
  else if (kind === 'sysClr') base = '#' + (colorNode.getAttribute('lastClr') || '000000')
  else if (kind === 'schemeClr') base = theme[colorNode.getAttribute('val') || ''] || '#000000'
  else if (kind === 'prstClr') base = colorNode.getAttribute('val') || '#000000'
  if (!base || !/^#[0-9a-f]{3,6}$/i.test(base)) return undefined
  if (base.length === 4) base = '#' + base.slice(1).split('').map(char => char + char).join('')
  const mod = Number(kid(colorNode, 'lumMod')?.getAttribute('val') || NaN) / 100000
  const off = Number(kid(colorNode, 'lumOff')?.getAttribute('val') || NaN) / 100000
  const alpha = Number(kid(colorNode, 'alpha')?.getAttribute('val') || NaN) / 100000
  if (Number.isFinite(mod) || Number.isFinite(off)) base = shiftLightness(base, Number.isFinite(mod) ? mod : 1, Number.isFinite(off) ? off : 0)
  if (Number.isFinite(alpha) && alpha < 1) return toRgba(base, Math.max(0, Math.min(1, alpha)))
  return base
}

function readTheme(document_: Document | null): { colors: ThemeColors; major: string; minor: string } {
  const colors: ThemeColors = {
    dk1: '#000000', lt1: '#ffffff', dk2: '#44546a', lt2: '#e7e6e6',
    accent1: '#4472c4', accent2: '#ed7d31', accent3: '#a5a5a5', accent4: '#ffc000',
    accent5: '#5b9bd5', accent6: '#70ad47', hlink: '#0563c1', folHlink: '#954f72',
  }
  let major = 'Calibri Light'
  let minor = 'Calibri'
  const scheme = document_ ? firstDescendant(document_.documentElement, 'clrScheme') : null
  for (const entry of scheme ? Array.from(scheme.children) : []) {
    const value = colorOf(entry, colors)
    if (value && /^#[0-9a-f]{6}$/i.test(value)) colors[tag(entry)] = value
  }
  // tx1/bg1/tx2/bg2 是主题色的别名。
  colors.tx1 = colors.dk1
  colors.bg1 = colors.lt1
  colors.tx2 = colors.dk2
  colors.bg2 = colors.lt2
  const fonts = document_ ? firstDescendant(document_.documentElement, 'fontScheme') : null
  const majorLatin = firstDescendant(firstDescendant(fonts, 'majorFont'), 'latin')
  const minorLatin = firstDescendant(firstDescendant(fonts, 'minorFont'), 'latin')
  if (majorLatin?.getAttribute('typeface')) major = majorLatin.getAttribute('typeface') as string
  if (minorLatin?.getAttribute('typeface')) minor = minorLatin.getAttribute('typeface') as string
  return { colors, major, minor }
}

interface ParagraphStyle {
  size?: number
  color?: string
  bold?: boolean
  align?: PptxParagraph['align']
  bullet?: string
  font?: string
  marginLeft?: number
  indent?: number
}

function readLevelStyle(node: Element | null): ParagraphStyle {
  const style: ParagraphStyle = {}
  if (!node) return style
  const align = attr(node, 'algn')
  if (align === 'ctr') style.align = 'center'
  else if (align === 'r') style.align = 'right'
  else if (align === 'just') style.align = 'justify'
  else if (align === 'l') style.align = 'left'
  if (/^\d+$/.test(node.getAttribute('marL') || '')) style.marginLeft = num(node, 'marL') / EMU_PER_PT
  if (node.getAttribute('indent') != null) style.indent = num(node, 'indent') / EMU_PER_PT
  const bulletChar = kid(node, 'buChar')
  if (bulletChar) style.bullet = attr(bulletChar, 'char') || '•'
  else if (kid(node, 'buAutoNum')) style.bullet = '•'
  else if (kid(node, 'buNone')) style.bullet = ''
  const defaultRun = kid(node, 'defRPr')
  if (defaultRun) {
    const size = num(defaultRun, 'sz', 0)
    if (size) style.size = size / 100
    if (defaultRun.getAttribute('b') === '1') style.bold = true
    const color = colorOf(kid(defaultRun, 'solidFill'), {})
    if (color) style.color = color
    const latin = kid(defaultRun, 'latin')
    if (latin?.getAttribute('typeface')) style.font = latin.getAttribute('typeface') as string
  }
  return style
}

/**
 * 段落默认值要逐字段合并：版式通常只写字号，项目符号和左边距在母版里，
 * 整份替换会把母版的 bullets 与 marL 弄丢（表现为项目符号贴在最左边、没有悬挂缩进）。
 */
function mergeLevels(...lists: ParagraphStyle[][]): ParagraphStyle[] {
  const merged: ParagraphStyle[] = []
  for (let level = 0; level < 9; level += 1) merged[level] = {}
  for (const list of lists) {
    for (let level = 0; level < 9; level += 1) {
      const style = list[level]
      if (!style) continue
      for (const [key, value] of Object.entries(style)) {
        if (value !== undefined) (merged[level] as Record<string, unknown>)[key] = value
      }
    }
  }
  return merged
}

function levelStyles(container: Element | null): ParagraphStyle[] {
  if (!container) return []
  const listStyle = kid(container, 'lstStyle')
  const source = listStyle ?? container
  const styles: ParagraphStyle[] = []
  for (let level = 0; level < 9; level += 1) styles[level] = readLevelStyle(kid(source, `lvl${level + 1}pPr`))
  return styles
}

/** 文字块；levels 是继承来的默认段落样式（版式占位符 → 母版 txStyles）。 */
function readTextBody(
  body: Element | null,
  levels: ParagraphStyle[],
  defaultColor: string,
  defaultFont: string,
  fallbackAnchor: PptxTextBody['anchor'] = 'top',
): PptxTextBody | undefined {
  if (!body) return undefined
  const bodyProps = kid(body, 'bodyPr')
  const anchorRaw = attr(bodyProps, 'anchor')
  const own = levelStyles(body)
  const paragraphs: PptxParagraph[] = []
  for (const paragraph of kids(body, 'p')) {
    const props = kid(paragraph, 'pPr')
    const level = num(props, 'lvl', 0)
    const style = { ...(levels[level] || {}), ...Object.fromEntries(Object.entries(own[level] || {}).filter(([, value]) => value !== undefined)) }
    const runs: PptxTextRun[] = []
    const push = (node: Element) => {
      const runProps = kid(node, 'rPr')
      const size = num(runProps, 'sz', 0)
      const color = colorOf(kid(runProps, 'solidFill'), {})
      const latin = kid(runProps, 'latin')
      runs.push({
        text: kid(node, 't')?.textContent || '',
        size: size ? size / 100 : style.size,
        bold: runProps?.getAttribute('b') === '1' ? true : (runProps?.getAttribute('b') === '0' ? false : style.bold),
        italic: runProps?.getAttribute('i') === '1',
        underline: runProps?.getAttribute('u') === 'sng',
        color: color || style.color || defaultColor,
        font: latin?.getAttribute('typeface') || style.font || defaultFont,
      })
    }
    for (const node of Array.from(paragraph.children)) {
      const kind = tag(node)
      if (kind === 'r' || kind === 'fld') push(node)
      else if (kind === 'br') runs.push({ text: '\n' })
    }
    const text = runs.map(run => run.text).join('')
    if (!text.trim() && !paragraph.children.length) continue

    const bulletNode = props ? kid(props, 'buChar') : null
    const bullet = props?.getElementsByTagName('*')
    const hasBulletNone = props ? Array.from(props.children).some(child => tag(child) === 'buNone') : false
    const bulletChar = bulletNode ? (attr(bulletNode, 'char') || '•') : ''
    const resolvedBullet = hasBulletNone ? '' : (bulletChar || style.bullet || '')
    void bullet

    const alignAttr = attr(props, 'algn')
    paragraphs.push({
      runs: runs.length ? runs : [{ text: '', size: style.size, color: style.color || defaultColor }],
      align: (alignAttr === 'ctr' ? 'center' : alignAttr === 'r' ? 'right' : alignAttr === 'just' ? 'justify' : alignAttr === 'l' ? 'left' : style.align) || 'left',
      level,
      bullet: resolvedBullet,
      size: style.size,
      color: style.color || defaultColor,
      marginLeft: style.marginLeft || 0,
      indent: style.indent ?? 0,
      spaceBefore: num(firstDescendant(kid(props, 'spcBef'), 'spcPts'), 'val', 0) / 100,
      spaceAfter: num(firstDescendant(kid(props, 'spcAft'), 'spcPts'), 'val', 0) / 100,
      lineHeight: num(firstDescendant(kid(props, 'lnSpc'), 'spcPct'), 'val', 0) / 100000 || undefined,
    })
  }
  if (!paragraphs.length) return undefined
  return {
    paragraphs,
    anchor: anchorRaw === 'ctr' ? 'middle' : anchorRaw === 'b' ? 'bottom' : anchorRaw === 't' ? 'top' : fallbackAnchor,
    inset: {
      left: num(bodyProps, 'lIns', DEFAULT_INSET.left),
      top: num(bodyProps, 'tIns', DEFAULT_INSET.top),
      right: num(bodyProps, 'rIns', DEFAULT_INSET.right),
      bottom: num(bodyProps, 'bIns', DEFAULT_INSET.bottom),
    },
    wrap: attr(bodyProps, 'wrap') !== 'none',
  }
}

interface Placeholder {
  geometry?: { x: number; y: number; w: number; h: number; rotation: number }
  levels: ParagraphStyle[]
  /** 垂直锚点（t/ctr/b）：幻灯片里通常不写，由版式占位符继承下来。 */
  anchor?: 'top' | 'middle' | 'bottom'
}

const placeholderKey = (type: string, idx: string) => `${type}|${idx}`

/**
 * 幻灯片里的占位符只写 `idx`（或连 idx 都没有），坐标和字号在版式/母版里。
 * 匹配顺序：精确 (type,idx) → 同 type → 同 idx 的 body/obj → 同 idx 的任意占位符。
 */
function findPlaceholder(map: Map<string, Placeholder>, type: string, idx: string): Placeholder | undefined {
  const direct = [
    placeholderKey(type, idx), placeholderKey(type, ''),
    placeholderKey('body', idx), placeholderKey('obj', idx),
    placeholderKey('body', ''), placeholderKey('obj', ''),
    placeholderKey('subTitle', idx), placeholderKey('subTitle', ''),
  ]
  for (const key of direct) {
    const hit = map.get(key)
    if (hit?.geometry) return hit
  }
  for (const [key, value] of map) if (value.geometry && key.endsWith('|' + idx)) return value
  return undefined
}

function readPlaceholders(container: Element | null): Map<string, Placeholder> {
  const map = new Map<string, Placeholder>()
  const tree = container ? descendants(container, 'spTree')[0] : null
  for (const shape of tree ? kids(tree, 'sp') : []) {
    const ph = descendants(shape, 'ph')[0]
    if (!ph) continue
    const type = attr(ph, 'type') || 'obj'
    const idx = attr(ph, 'idx') || ''
    const transform = kid(kid(shape, 'spPr'), 'xfrm')
    const offset = kid(transform, 'off')
    const extent = kid(transform, 'ext')
    const bodyProps = kid(kid(shape, 'txBody'), 'bodyPr')
    const anchorRaw = attr(bodyProps, 'anchor')
    map.set(placeholderKey(type, idx), {
      geometry: transform
        ? { x: num(offset, 'x'), y: num(offset, 'y'), w: num(extent, 'cx'), h: num(extent, 'cy'), rotation: num(transform, 'rot') / 60000 }
        : undefined,
      levels: levelStyles(kid(shape, 'txBody')),
      anchor: anchorRaw === 'ctr' ? 'middle' : anchorRaw === 'b' ? 'bottom' : anchorRaw === 't' ? 'top' : undefined,
    })
  }
  return map
}

function readMasterStyles(master: Element | null): { title: ParagraphStyle[]; body: ParagraphStyle[]; other: ParagraphStyle[] } {
  const styles = master ? descendants(master, 'txStyles')[0] : null
  const read = (name: string) => levelStyles(styles ? (descendants(styles, name)[0] ?? null) : null)
  return { title: read('titleStyle'), body: read('bodyStyle'), other: read('otherStyle') }
}

function relsOf(files: Record<string, Uint8Array>, part: string): Map<string, string> {
  const relsPath = part.replace(/([^/]+)$/, '_rels/$1.rels')
  const document_ = parseXml(files[relsPath])
  const map = new Map<string, string>()
  if (!document_) return map
  for (const relationship of descendants(document_.documentElement, 'Relationship')) {
    const id = relationship.getAttribute('Id') || ''
    const target = relationship.getAttribute('Target') || ''
    if (!id || !target) continue
    const base = part.replace(/[^/]+$/, '')
    map.set(id, target.startsWith('/') ? target.slice(1) : new URL(target, 'https://x/' + base).pathname.slice(1))
  }
  return map
}

function mimeFor(path: string): string {
  const extension = path.split('.').pop()?.toLowerCase() || ''
  return ({
    png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
    bmp: 'image/bmp', webp: 'image/webp', svg: 'image/svg+xml', ico: 'image/x-icon',
  } as Record<string, string>)[extension] || 'application/octet-stream'
}

function base64(bytes: Uint8Array): string {
  let out = ''
  const chunk = 0x8000
  for (let index = 0; index < bytes.length; index += chunk) {
    out += String.fromCharCode(...bytes.subarray(index, index + chunk))
  }
  return btoa(out)
}

function mediaUrl(files: Record<string, Uint8Array>, path: string): string | undefined {
  const bytes = files[path]
  return bytes ? `data:${mimeFor(path)};base64,${base64(bytes)}` : undefined
}

function gradientCss(gradient: Element, theme: ThemeColors): string {
  const stops = kids(kid(gradient, 'gsLst'), 'gs').map((stop) => {
    const position = Math.max(0, Math.min(100, num(stop, 'pos', 0) / 1000))
    return `${colorOf(stop, theme) || '#ffffff'} ${position}%`
  })
  if (!stops.length) return '#ffffff'
  const angle = num(kid(gradient, 'lin'), 'ang', 0) / 60000
  return `linear-gradient(${Math.round(angle + 90)}deg, ${stops.join(', ')})`
}

function backgroundOf(cSlide: Element | null, theme: ThemeColors): string | undefined {
  const background = kid(cSlide, 'bg')
  if (!background) return undefined
  const props = kid(background, 'bgPr')
  if (props) {
    const solid = kid(props, 'solidFill')
    if (solid) return colorOf(solid, theme)
    const gradient = kid(props, 'gradFill')
    if (gradient) return gradientCss(gradient, theme)
  }
  const reference = kid(background, 'bgRef')
  if (reference) return colorOf(kid(reference, 'schemeClr'), theme)
  return undefined
}

function fillOf(properties: Element | null, theme: ThemeColors): string | undefined {
  if (!properties) return undefined
  const solid = kid(properties, 'solidFill')
  if (solid) return colorOf(solid, theme)
  const gradient = kid(properties, 'gradFill')
  if (gradient) return gradientCss(gradient, theme)
  return undefined
}

function lineOf(properties: Element | null, theme: ThemeColors): { color: string; width: number } | undefined {
  const line = properties ? kid(properties, 'ln') : null
  if (!line || kid(line, 'noFill')) return undefined
  const color = colorOf(kid(line, 'solidFill'), theme)
  if (!color) return undefined
  return { color, width: num(line, 'w', 12700) }
}

type Mapper = (x: number, y: number, w: number, h: number) => { x: number; y: number; w: number; h: number }

/** 组合（grpSp）把子坐标按 chOff/chExt 映射到自己的 off/ext。 */
function groupTransform(group: Element): Mapper | null {
  const transform = kid(kid(group, 'grpSpPr'), 'xfrm')
  if (!transform) return null
  const offset = kid(transform, 'off'), extent = kid(transform, 'ext')
  const childOffset = kid(transform, 'chOff'), childExtent = kid(transform, 'chExt')
  if (!childOffset || !childExtent) return null
  const ox = num(offset, 'x'), oy = num(offset, 'y')
  const ex = num(extent, 'cx') || num(childExtent, 'cx')
  const ey = num(extent, 'cy') || num(childExtent, 'cy')
  const cx = num(childOffset, 'x'), cy = num(childOffset, 'y')
  const cw = num(childExtent, 'cx') || ex
  const ch = num(childExtent, 'cy') || ey
  const sx = cw ? ex / cw : 1
  const sy = ch ? ey / ch : 1
  return (x, y, w, h) => ({ x: ox + (x - cx) * sx, y: oy + (y - cy) * sy, w: w * sx, h: h * sy })
}

interface SlideContext {
  theme: ThemeColors
  minorFont: string
  layoutPlaceholders: Map<string, Placeholder>
  masterPlaceholders: Map<string, Placeholder>
  masterStyles: { title: ParagraphStyle[]; body: ParagraphStyle[]; other: ParagraphStyle[] }
  rels: Map<string, string>
  files: Record<string, Uint8Array>
}

let shapeSeq = 0

function readShapes(tree: Element | null, context: SlideContext, apply: Mapper | null): PptxShape[] {
  const shapes: PptxShape[] = []
  for (const node of tree ? Array.from(tree.children) : []) {
    const kind = tag(node)
    if (kind === 'grpSp') {
      const own = groupTransform(node)
      const mapper: Mapper | null = own
        ? (x, y, w, h) => {
          const inner = own(x, y, w, h)
          return apply ? apply(inner.x, inner.y, inner.w, inner.h) : inner
        }
        : apply
      shapes.push(...readShapes(node, context, mapper))
      continue
    }
    if (kind === 'sp') {
      const ph = descendants(node, 'ph')[0]
      const type = ph ? (attr(ph, 'type') || 'obj') : ''
      const idx = ph ? (attr(ph, 'idx') || '') : ''
      const layoutMatch = ph ? findPlaceholder(context.layoutPlaceholders, type, idx) : undefined
      const masterMatch = ph ? findPlaceholder(context.masterPlaceholders, type, idx) : undefined
      const transform = kid(kid(node, 'spPr'), 'xfrm')
      const offset = kid(transform, 'off'), extent = kid(transform, 'ext')
      const geometry = transform
        ? { x: num(offset, 'x'), y: num(offset, 'y'), w: num(extent, 'cx'), h: num(extent, 'cy'), rotation: num(transform, 'rot') / 60000 }
        : layoutMatch?.geometry || masterMatch?.geometry
      if (!geometry || !geometry.w || !geometry.h) continue
      const mapped = apply ? apply(geometry.x, geometry.y, geometry.w, geometry.h) : geometry
      const isTitle = type === 'title' || type === 'ctrTitle'
      // 占位符的正文默认值来自 bodyStyle；otherStyle 是“普通文本框”的默认值（18pt），
      // 混进占位符会把 32pt 正文压成 18pt，项目符号与左边距也会被覆盖。
      const levels = ph
        ? (isTitle
          ? mergeLevels(context.masterStyles.title, masterMatch?.levels || [], layoutMatch?.levels || [])
          : mergeLevels(context.masterStyles.body, masterMatch?.levels || [], layoutMatch?.levels || []))
        : mergeLevels(context.masterStyles.other)
      const properties = kid(node, 'spPr')
      const text = readTextBody(
        kid(node, 'txBody'),
        levels,
        context.theme.tx1 || '#000000',
        context.minorFont,
        layoutMatch?.anchor || masterMatch?.anchor || 'top',
      )
      shapes.push({
        kind: text ? 'text' : 'shape',
        key: `sp-${(shapeSeq += 1)}`,
        name: attr(descendants(node, 'cNvPr')[0], 'name'),
        ...mapped,
        rotation: geometry.rotation || undefined,
        geometry: attr(kid(properties, 'prstGeom'), 'prst') || 'rect',
        fill: fillOf(properties, context.theme),
        line: lineOf(properties, context.theme),
        text,
      })
      continue
    }
    if (kind === 'pic') {
      const transform = kid(kid(node, 'spPr'), 'xfrm')
      const offset = kid(transform, 'off'), extent = kid(transform, 'ext')
      const embed = kid(kid(node, 'blipFill'), 'blip')
      const target = context.rels.get(attr(embed, 'r:embed'))
      const url = target ? mediaUrl(context.files, target) : undefined
      if (!url) continue
      const geometry = { x: num(offset, 'x'), y: num(offset, 'y'), w: num(extent, 'cx'), h: num(extent, 'cy') }
      const mapped = apply ? apply(geometry.x, geometry.y, geometry.w, geometry.h) : geometry
      shapes.push({
        kind: 'image',
        key: `pic-${(shapeSeq += 1)}`,
        name: attr(descendants(node, 'cNvPr')[0], 'name'),
        ...mapped,
        rotation: num(transform, 'rot') / 60000 || undefined,
        image: { url },
      })
      continue
    }
    if (kind === 'graphicFrame') {
      const tableNode = descendants(node, 'tbl')[0]
      if (!tableNode) continue
      const transform = kid(node, 'xfrm')
      const offset = kid(transform, 'off'), extent = kid(transform, 'ext')
      const columns = kids(kid(tableNode, 'tblGrid'), 'gridCol').map(column => num(column, 'w'))
      const rows = kids(tableNode, 'tr').map((row) => ({
        height: num(row, 'h'),
        cells: kids(row, 'tc').map((cell) => ({
          text: readTextBody(kid(cell, 'txBody'), [], '#000000', context.minorFont),
          gridSpan: num(cell, 'gridSpan', 1),
          fill: fillOf(kid(cell, 'tcPr'), context.theme),
        })),
      }))
      const geometry = { x: num(offset, 'x'), y: num(offset, 'y'), w: num(extent, 'cx'), h: num(extent, 'cy') }
      const mapped = apply ? apply(geometry.x, geometry.y, geometry.w, geometry.h) : geometry
      shapes.push({
        kind: 'table',
        key: `tbl-${(shapeSeq += 1)}`,
        name: attr(descendants(node, 'cNvPr')[0], 'name'),
        ...mapped,
        table: { columns: columns.length ? columns : [mapped.w], rows },
      })
    }
  }
  return shapes
}

function shapeText(shape: PptxShape): string {
  return (shape.text?.paragraphs || []).map(paragraph => paragraph.runs.map(run => run.text).join('')).join(' ').replace(/\s+/g, ' ').trim()
}

export function parsePptxLayout(files: Record<string, Uint8Array>): PptxDeck {
  const presentation = parseXml(files['ppt/presentation.xml'])
  const size = presentation ? descendants(presentation.documentElement, 'sldSz')[0] : null
  const width = num(size, 'cx', 9144000)
  const height = num(size, 'cy', 6858000)
  const theme = readTheme(parseXml(files['ppt/theme/theme1.xml']))
  const master = parseXml(files['ppt/slideMasters/slideMaster1.xml'])?.documentElement ?? null
  const masterPlaceholders = readPlaceholders(master)
  const masterStyles = readMasterStyles(master)

  const slideNames = Object.keys(files)
    .filter(path => /^ppt\/slides\/slide\d+\.xml$/.test(path))
    .sort((left, right) => Number(left.match(/(\d+)\.xml$/)![1]) - Number(right.match(/(\d+)\.xml$/)![1]))

  const slides: PptxSlide[] = []
  for (const [index, slidePath] of slideNames.entries()) {
    const document_ = parseXml(files[slidePath])
    if (!document_) continue
    const rels = relsOf(files, slidePath)
    const layoutPath = Array.from(rels.values()).find(path => path.startsWith('ppt/slideLayouts/slideLayout'))
    const layout = parseXml(layoutPath ? files[layoutPath] : undefined)?.documentElement ?? null
    const tree = descendants(document_.documentElement, 'spTree')[0] ?? null
    shapeSeq = 0
    const shapes = readShapes(tree, {
      theme: theme.colors,
      minorFont: theme.minor,
      layoutPlaceholders: readPlaceholders(layout),
      masterPlaceholders,
      masterStyles,
      rels,
      files,
    }, null)
    const titleShape = shapes.find(shape => shape.kind === 'text' && shapeText(shape))
    slides.push({
      index: index + 1,
      title: (titleShape ? shapeText(titleShape) : '').slice(0, 80) || `第 ${index + 1} 页`,
      background: backgroundOf(descendants(document_.documentElement, 'cSld')[0] ?? null, theme.colors)
        || backgroundOf(layout ? descendants(layout, 'cSld')[0] ?? null : null, theme.colors)
        || '#ffffff',
      shapes,
    })
  }
  return { width, height, slides }
}

/** 以容器宽度为基准的长度（渲染层用 cqw 单位，面板变宽变窄都等比）。 */
export function lengthCqw(points: number, deckWidthEmu: number): string {
  const widthPt = emuToPoints(deckWidthEmu)
  if (!widthPt) return '0cqw'
  return `${((points / widthPt) * 100).toFixed(4)}cqw`
}

export const emuToCqw = (emu: number, deckWidthEmu: number): string => lengthCqw(emuToPoints(emu), deckWidthEmu)
export const emuToPx = (emu: number): number => emu / EMU_PER_PX
export { emuToPoints }

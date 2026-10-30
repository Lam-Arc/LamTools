import type {
  StudioAnchorEdge,
  StudioAsset,
  StudioBackground,
  StudioDimension,
  StudioDocument,
  StudioNodeStyle,
} from './schema.ts'
import { LAYOUT_VARIABLES } from './schema.ts'
import { findUiEntry } from '@/uiRegistry/index.ts'

/**
 * 把主题文档编译成覆盖样式。
 *
 * user:“可视化主题与布局编辑器”+
 * (编辑器写文档，运行端只加载编译后的样式；文档不执行任何脚本。
 *  选择器用双属性提高权重，保证覆盖压过组件自带的作用域样式。)
 */

export interface CompileOptions {
  /** 素材标识到可访问地址的映射；缺省时只保留自定义属性引用。 */
  assetUrl?: (assetId: string) => string | null
  /** 编译产物的作用域前缀，默认挂到文档根。 */
  rootSelector?: string
}

function escapeAttribute(value: string): string {
  return value.replace(/["\\]/g, '\\$&')
}

/** 双属性选择器：0,2,0 权重，与作用域样式打平后靠后加载取胜。 */
export function selectorFor(id: string): string {
  const safe = escapeAttribute(id)
  return `[data-ui-id="${safe}"][data-ui-id]`
}

/** 模板选择器：同一条规则命中所有实例。 */
export function templateSelectorFor(id: string): string {
  const safe = escapeAttribute(id)
  return `[data-ui-template="${safe}"][data-ui-template]`
}

/** 实例选择器：同一权重但排在模板之后，因此实例覆盖模板。 */
export function instanceSelectorFor(key: string): string {
  const safe = escapeAttribute(key)
  return `[data-ui-instance="${safe}"][data-ui-instance]`
}

function dimensionValue(dimension: StudioDimension | undefined): string | null {
  if (!dimension) return null
  switch (dimension.mode) {
    case 'fixed':
    case 'relative':
    case 'ratio':
      return dimension.value === undefined ? null : `${dimension.value}${dimension.mode === 'relative' || dimension.mode === 'ratio' ? '%' : 'px'}`
    case 'fill':
      return '100%'
    case 'hug':
      return 'auto'
    case 'stretch':
      return 'auto'
    default:
      return null
  }
}

/** 底色声明值：令牌 → var(--theme-*)；'transparent' 显式透明；否则十六进制。 */
function backgroundBaseColor(background: StudioBackground): string | null {
  if (background.colorToken) {
    return background.colorToken === 'transparent' ? 'transparent' : `var(--theme-${background.colorToken})`
  }
  if (background.color === 'transparent') return 'transparent'
  return background.color ?? null
}

function backgroundDeclarations(background: StudioBackground, assets: StudioAsset[] = []): string[] {
  const declarations: string[] = []
  const baseColor = backgroundBaseColor(background)
  // user:“一个样式最开始是什么颜色，就应该让它显示为什么颜色。除非我单独去设置，
  //  不然我上完图再把图撤了，就会发生突变”+
  // (只输出用户真正设置过的层：颜色有值才写底色；有素材引用才写图片；
  //  都没有就一条背景声明都不写，组件原生外观原样保留，撤图不会突变。)
  if (baseColor) declarations.push(`background-color: ${baseColor}`)
  // user:“我不是说过图像不被容器裁切吗”+
  // (允许溢出=组件本体不再裁切并成为定位宿主；图片改由 ::before 按原始尺寸外绘。
  //  九宫格依赖 border-image，仍走原路径。)
  const overlay = background.assetRef
    && background.overflow === 'local-visible'
    && background.fit !== 'nineSlice'
  if (overlay) {
    declarations.push('overflow: visible', 'isolation: isolate')
    if (background.overflowHost === 'relative') declarations.push('position: relative')
  }
  if (background.assetRef && !overlay) {
    const assetRef = escapeAttribute(background.assetRef)
    const fit = background.fit ?? 'cover'
    if (fit === 'nineSlice' && background.slice) {
      const { top, right, bottom, left } = background.slice
      declarations.push(
        `border-image-source: var(--ui-asset-${assetRef})`,
        `border-image-slice: ${top} ${right} ${bottom} ${left} fill`,
        'border-image-width: 1',
        'border-style: solid',
        'border-color: transparent',
      )
    } else {
      declarations.push(`background-image: var(--ui-asset-${assetRef})`)
      // user:“添加的图像应该可以裁切、位移、缩放等等”+(位置=焦点百分比，缩放=相对原始尺寸的倍数)
      const asset = assets.find((item) => item.id === background.assetRef)
      const scale = background.scale ?? 1
      if (fit === 'tile') {
        const tileSize = scale !== 1 && asset && asset.width > 0 && asset.height > 0
          ? `${Math.round(asset.width * scale)}px ${Math.round(asset.height * scale)}px`
          : 'auto'
        declarations.push('background-repeat: repeat', `background-size: ${tileSize}`)
      } else if (fit === 'stretch') {
        declarations.push(`background-size: ${Math.round(scale * 100)}% ${Math.round(scale * 100)}%`, 'background-repeat: no-repeat')
      } else if (scale !== 1 && asset && asset.width > 0) {
        declarations.push(`background-size: ${Math.round(asset.width * scale)}px auto`, 'background-repeat: no-repeat')
      } else {
        const size: Record<string, [string, string]> = {
          fixed: ['auto', 'no-repeat'],
          contain: ['contain', 'no-repeat'],
          cover: ['cover', 'no-repeat'],
          nineSlice: ['100% 100%', 'no-repeat'],
        }
        const [backgroundSize, repeat] = size[fit] ?? ['cover', 'no-repeat']
        declarations.push(`background-size: ${backgroundSize}`, `background-repeat: ${repeat}`)
      }
      declarations.push(`background-position: ${background.positionX ?? 50}% ${background.positionY ?? 50}%`)
    }
  } else if (background.stops && background.stops.length > 0) {
    const stops = background.stops
      .slice()
      .sort((left, right) => left.position - right.position)
      .map((stop) => `${stop.color} ${stop.position}%`)
      .join(', ')
    declarations.push(`background-image: linear-gradient(${background.angle ?? 180}deg, ${stops})`)
  } else if (baseColor) {
    // 用户显式选了底色：明确压过组件原生背景图，避免两层颜色叠在一起。
    declarations.push('background-image: none')
  }
  if (background.opacity !== undefined) {
    declarations.push(`--ui-bg-opacity: ${background.opacity}`)
  }
  if (background.overflow) {
    // 溢出交给独立装饰层处理，这里只登记意图，不直接改 overflow。
    declarations.push(`--ui-bg-overflow: ${background.overflow}`)
  }
  return declarations
}

function styleDeclarations(style: StudioNodeStyle, assets: StudioAsset[] = [], positioned = false): string[] {
  const declarations: string[] = []
  // user:“子容器应当是相对于父容器的某一个边或者某几个边，设定距离，兜底距离不得小于 0”+
  // (方案 §4.4：锚点编译成相对目标边的绝对边距；距离值恒为非负，由校验保证)
  if (style.anchors && style.anchors.length > 0) {
    declarations.push('position: absolute')
    const EDGE_DECLARATIONS: Record<StudioAnchorEdge, (offset: number) => string> = {
      left: (offset) => `left: ${offset}px`,
      right: (offset) => `right: ${offset}px`,
      top: (offset) => `top: ${offset}px`,
      bottom: (offset) => `bottom: ${offset}px`,
      centerX: (offset) => `left: calc(50% + ${offset}px)`,
      centerY: (offset) => `top: calc(50% + ${offset}px)`,
    }
    for (const anchor of style.anchors) {
      declarations.push((EDGE_DECLARATIONS[anchor.edge] ?? EDGE_DECLARATIONS.left)(Math.max(0, anchor.offset)))
    }
  }
  if (style.offset && (style.offset.x !== 0 || style.offset.y !== 0)) {
    // 独立的 translate 属性与组件已有的 transform 叠加，不会互相覆盖。
    declarations.push(`translate: ${style.offset.x}px ${style.offset.y}px`)
  }
  if (style.size) {
    const width = dimensionValue(style.size.width)
    const height = dimensionValue(style.size.height)
    if (width) declarations.push(`width: ${width}`)
    if (height) declarations.push(`height: ${height}`)
    if (style.size.width?.min !== undefined) declarations.push(`min-width: ${style.size.width.min}px`)
    if (style.size.width?.max !== undefined) declarations.push(`max-width: ${style.size.width.max}px`)
    if (style.size.height?.min !== undefined) declarations.push(`min-height: ${style.size.height.min}px`)
    if (style.size.height?.max !== undefined) declarations.push(`max-height: ${style.size.height.max}px`)
  }
  if (style.spacing) {
    // user:“那个间距是干啥的？为什么我调了半天也没有反应呢？”+
    // (margin 模式交给子项外边距规则，gap 模式才写容器 gap；未设置按 gap。)
    if (style.spacing.gap !== undefined && style.spacing.mode !== 'margin') {
      declarations.push(`gap: ${style.spacing.gap}px`)
    }
    // user:“它应该是相对原版做了什么调整……比如 X+1 Y-2”+
    // (变长列表每项在自身实际高度上叠加的增量，不写绝对高度)
    if (style.spacing.blockExtra !== undefined && style.spacing.blockExtra !== 0) {
      declarations.push(`margin-block-end: ${style.spacing.blockExtra}px`)
    }
    if (style.spacing.padding) declarations.push(`padding: ${style.spacing.padding.map((item) => `${item}px`).join(' ')}`)
  }
  if (style.radius !== undefined) {
    const radius = Array.isArray(style.radius)
      ? style.radius.map((item) => `${item}px`).join(' ')
      : `${style.radius}px`
    declarations.push(`border-radius: ${radius}`)
  }
  if (style.border) {
    declarations.push(`border: ${style.border.width}px solid ${style.border.color}`)
  }
  if (style.color) declarations.push(`color: ${style.color}`)
  if (style.background) declarations.push(...backgroundDeclarations(style.background, assets))
  if (style.opacity !== undefined) declarations.push(`opacity: ${style.opacity}`)
  if (style.layer !== undefined) {
    // user:“Z-index 从 1~9999 一直分层，100 个 z 为一层”+(层值就是真实 z-index，直接参与堆叠)
    // 未自带定位的元素补 position: relative，否则 z-index 对普通块级子元素不生效。
    if (!positioned) declarations.push('position: relative')
    declarations.push(`z-index: ${Math.round(style.layer)}`)
  }
  if (style.visibility === false) declarations.push('display: none')
  if (style.text) {
    if (style.text.size !== undefined) declarations.push(`font-size: ${style.text.size}px`)
    if (style.text.lineHeight !== undefined) declarations.push(`line-height: ${style.text.lineHeight}`)
    if (style.text.letterSpacing !== undefined) declarations.push(`letter-spacing: ${style.text.letterSpacing}px`)
    if (style.text.align) declarations.push(`text-align: ${style.text.align}`)
  }
  return declarations
}

/**
 * 一条节点样式编译出的全部规则：主规则 + 间距外边距规则 + 背景外绘伪元素。
 * user:“那个间距是干啥的？……我不是说过图像不被容器裁切吗”+
 * (间距在块级容器上走子项外边距；允许溢出时图片用 ::before 按原始尺寸外绘。)
 */
// 自带定位的外壳容器不需要再补 position: relative（补了会覆盖 fixed/absolute）。
const KNOWN_POSITIONED = new Set([
  'shell.root', 'shell.main', 'shell.titlebar', 'shell.app-rail',
  'shell.left-drawer', 'shell.right-drawer', 'shell.split',
])

function rulesFor(selector: string, style: StudioNodeStyle, assets: StudioAsset[], id?: string): string[] {
  const rules: string[] = []
  const declarations = styleDeclarations(style, assets, Boolean(id && KNOWN_POSITIONED.has(id)))
  if (declarations.length > 0) rules.push(`${selector} { ${declarations.join('; ')} }`)
  if (style.spacing?.gap !== undefined && style.spacing.mode === 'margin') {
    rules.push(`${selector} > * + * { margin-block-start: ${style.spacing.gap}px }`)
  }
  const background = style.background
  if (background?.assetRef && background.overflow === 'local-visible' && background.fit !== 'nineSlice') {
    const asset = assets.find((item) => item.id === background.assetRef)
    const size = asset && asset.width > 0 && asset.height > 0
      ? `width: ${asset.width}px; height: ${asset.height}px`
      : 'inset: 0'
    // 外绘图层的图片同样遵守位置与缩放设置。
    const scale = background.scale ?? 1
    rules.push(
      `${selector}::before { content: ""; position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); ${size}; background-image: var(--ui-asset-${escapeAttribute(background.assetRef)}); background-size: ${Math.round(scale * 100)}% ${Math.round(scale * 100)}%; background-position: ${background.positionX ?? 50}% ${background.positionY ?? 50}%; background-repeat: no-repeat; pointer-events: none; z-index: -1 }`,
    )
  }
  return rules
}

function assetVariables(document: StudioDocument, options: CompileOptions): string[] {
  const resolve = options.assetUrl
  if (!resolve) return []
  const variables: string[] = []
  for (const asset of document.assets) {
    const url = resolve(asset.id)
    if (!url) continue
    variables.push(`--ui-asset-${escapeAttribute(asset.id)}: url("${url.replace(/"/g, '\\"')}")`)
  }
  return variables.length > 0 ? [`:root { ${variables.join('; ')} }`] : []
}

export function compileStudioDocument(document: StudioDocument, options: CompileOptions = {}): string {
  const blocks: string[] = []
  // user:“把布局规则变量给统一”+(布局几何变量写到根上，整条布局链一起跟随)
  const layoutVariables = Object.entries(document.variables || {})
    .filter(([name]) => LAYOUT_VARIABLES.includes(name as never))
  if (layoutVariables.length > 0) {
    blocks.push(`:root { ${layoutVariables.map(([name, value]) => `${name}: ${value}`).join('; ')} }`)
  }
  const root = options.rootSelector
  const rootBlock = root ? [`${root} { ${assetVariables(document, options).join('')} }`] : assetVariables(document, options)
  blocks.push(...rootBlock)

  // 锚定子节点的父容器必须成为定位宿主；已经自带定位的外壳/抽屉不再覆盖。
  const ANCHOR_HOST_SKIP = new Set([
    'shell.root', 'shell.main', 'shell.titlebar', 'shell.app-rail',
    'shell.left-drawer', 'shell.right-drawer', 'shell.split',
  ])
  const anchorHosts = new Set<string>()
  const considerAnchorHost = (id: string, style: StudioNodeStyle | undefined) => {
    if (!style?.anchors || style.anchors.length === 0) return
    const parent = findUiEntry(id)?.parent
    if (parent && !ANCHOR_HOST_SKIP.has(parent)) anchorHosts.add(parent)
  }
  for (const [id, style] of Object.entries(document.nodes)) considerAnchorHost(id, style)
  for (const [id, style] of Object.entries(document.templates || {})) considerAnchorHost(id, style)
  for (const host of anchorHosts) {
    const selector = findUiEntry(host)?.kind === 'template' ? templateSelectorFor(host) : selectorFor(host)
    blocks.push(`${selector} { position: relative }`)
  }

  for (const id of Object.keys(document.nodes).sort()) {
    blocks.push(...rulesFor(selectorFor(id), document.nodes[id], document.assets, id))
  }

  for (const id of Object.keys(document.templates || {}).sort()) {
    blocks.push(...rulesFor(templateSelectorFor(id), (document.templates || {})[id], document.assets, id))
  }

  for (const key of Object.keys(document.instances || {}).sort()) {
    const entry = (document.instances || {})[key]
    if (!entry) continue
    blocks.push(...rulesFor(instanceSelectorFor(key), entry.style, document.assets))
  }

  for (const breakpoint of document.breakpoints) {
    const body: string[] = []
    for (const id of Object.keys(breakpoint.nodes).sort()) {
      body.push(...rulesFor(selectorFor(id), breakpoint.nodes[id], document.assets, id))
    }
    if (body.length === 0) continue
    const condition = breakpoint.minWidth !== undefined && breakpoint.maxWidth !== undefined
      ? `(min-width: ${breakpoint.minWidth}px) and (max-width: ${breakpoint.maxWidth}px)`
      : breakpoint.minWidth !== undefined
        ? `(min-width: ${breakpoint.minWidth}px)`
        : breakpoint.maxWidth !== undefined
          ? `(max-width: ${breakpoint.maxWidth}px)`
          : null
    if (!condition) continue
    blocks.push(`@media ${condition} { ${body.join(' ')} }`)
  }

  return blocks.join('\n')
}

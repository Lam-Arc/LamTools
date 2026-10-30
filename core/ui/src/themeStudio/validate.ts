import { findUiEntry } from '@/uiRegistry/index.ts'
import type { UiEditableProperty, UiRegistryEntry } from '@/uiRegistry/types.ts'
import {
  LAYOUT_VARIABLES,
  STUDIO_COLOR_TOKENS,
  THEME_STUDIO_SCHEMA_VERSION,
  type StudioBreakpoint,
  type StudioNodeStyle,
} from './schema.ts'

/**
 * 校验主题文档。
 *
 * user:“主题编辑器”+(主题损坏时必须能检出并拒绝发布，不能把坏配置写进运行界面。
 *  校验先于渲染，错误要能指出是哪个元素、哪个属性。)
 */

export interface StudioIssue {
  path: string
  message: string
}

export interface StudioValidationResult {
  ok: boolean
  errors: StudioIssue[]
  warnings: StudioIssue[]
}

/** 样式字段到注册表属性类别的映射。 */
const STYLE_KEYS: Record<keyof StudioNodeStyle, UiEditableProperty> = {
  offset: 'position',
  anchors: 'position',
  size: 'size',
  spacing: 'spacing',
  radius: 'radius',
  border: 'border',
  color: 'color',
  background: 'background',
  text: 'text',
  opacity: 'opacity',
  layer: 'layer',
  visibility: 'visibility',
}

const SIZE_MODES = new Set(['fixed', 'hug', 'fill', 'relative', 'ratio', 'stretch'])
const BACKGROUND_TYPES = new Set(['solid', 'gradient', 'asset'])
const BACKGROUND_FITS = new Set(['fixed', 'contain', 'cover', 'stretch', 'nineSlice', 'tile'])
const BACKGROUND_OVERFLOWS = new Set(['clipped', 'local-visible', 'decoration-portal'])
const TEXT_ALIGNS = new Set(['left', 'center', 'right'])
const ANCHOR_EDGES = new Set(['left', 'right', 'top', 'bottom', 'centerX', 'centerY'])
const HEX_COLOR = /^#[0-9a-f]{3,8}$/i

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function checkHexColor(value: unknown, path: string, errors: StudioIssue[]): void {
  if (typeof value !== 'string' || !HEX_COLOR.test(value)) {
    errors.push({ path, message: '颜色必须是十六进制值' })
  }
}

function checkDimension(value: unknown, path: string, errors: StudioIssue[]): void {
  if (!value || typeof value !== 'object') {
    errors.push({ path, message: '尺寸必须是对象' })
    return
  }
  const dimension = value as Record<string, unknown>
  if (typeof dimension.mode !== 'string' || !SIZE_MODES.has(dimension.mode)) {
    errors.push({ path, message: `尺寸模式无效：${String(dimension.mode)}` })
  }
  if (dimension.value !== undefined && !isFiniteNumber(dimension.value)) {
    errors.push({ path: `${path}.value`, message: '尺寸数值必须是有限数字' })
  }
  if (dimension.min !== undefined && dimension.max !== undefined
    && isFiniteNumber(dimension.min) && isFiniteNumber(dimension.max)
    && dimension.min > dimension.max) {
    errors.push({ path, message: '最小尺寸不能大于最大尺寸' })
  }
}

function checkBackground(
  value: unknown,
  path: string,
  assetIds: Set<string>,
  errors: StudioIssue[],
): void {
  if (!value || typeof value !== 'object') {
    errors.push({ path, message: '背景必须是对象' })
    return
  }
  const background = value as Record<string, unknown>
  if (typeof background.type !== 'string' || !BACKGROUND_TYPES.has(background.type)) {
    errors.push({ path, message: `背景类型无效：${String(background.type)}` })
  }
  if (background.color !== undefined && background.color !== 'transparent') {
    checkHexColor(background.color, `${path}.color`, errors)
  }
  if (background.colorToken !== undefined
    && !STUDIO_COLOR_TOKENS.includes(background.colorToken as never)) {
    // 令牌只接受白名单，签名固定编译成 var(--theme-*)，不给任意 CSS 留口子。
    errors.push({ path: `${path}.colorToken`, message: '背景颜色令牌无效' })
  }
  if (background.opacity !== undefined
    && (!isFiniteNumber(background.opacity) || background.opacity < 0 || background.opacity > 1)) {
    errors.push({ path: `${path}.opacity`, message: '背景透明度必须在 0 到 1 之间' })
  }
  if (background.fit !== undefined && !BACKGROUND_FITS.has(String(background.fit))) {
    errors.push({ path: `${path}.fit`, message: `背景适配方式无效：${String(background.fit)}` })
  }
  if (background.overflow !== undefined && !BACKGROUND_OVERFLOWS.has(String(background.overflow))) {
    errors.push({ path: `${path}.overflow`, message: `背景溢出方式无效：${String(background.overflow)}` })
  }
  if (background.overflowHost !== undefined && background.overflowHost !== 'relative') {
    errors.push({ path: `${path}.overflowHost`, message: '背景外绘宿主标记无效' })
  }
  if (Array.isArray(background.stops)) {
    background.stops.forEach((stop, index) => {
      if (!stop || typeof stop !== 'object') {
        errors.push({ path: `${path}.stops[${index}]`, message: '渐变节点必须是对象' })
        return
      }
      const node = stop as Record<string, unknown>
      checkHexColor(node.color, `${path}.stops[${index}].color`, errors)
      if (!isFiniteNumber(node.position) || node.position < 0 || node.position > 100) {
        errors.push({ path: `${path}.stops[${index}].position`, message: '渐变位置必须在 0 到 100 之间' })
      }
    })
  }
  if (background.slice !== undefined) {
    const slice = background.slice as Record<string, unknown>
    for (const key of ['top', 'right', 'bottom', 'left'] as const) {
      const value = slice[key]
      if (!isFiniteNumber(value) || value < 0 || value > 1000) {
        errors.push({ path: `${path}.slice.${key}`, message: '切片数值必须在 0 到 1000 之间' })
      }
    }
  }
  if (background.positionX !== undefined && (!isFiniteNumber(background.positionX) || background.positionX < 0 || background.positionX > 100)) {
    errors.push({ path: `${path}.positionX`, message: '背景横向位置必须在 0 到 100 之间' })
  }
  if (background.positionY !== undefined && (!isFiniteNumber(background.positionY) || background.positionY < 0 || background.positionY > 100)) {
    errors.push({ path: `${path}.positionY`, message: '背景纵向位置必须在 0 到 100 之间' })
  }
  if (background.scale !== undefined && (!isFiniteNumber(background.scale) || background.scale < 0.1 || background.scale > 4)) {
    errors.push({ path: `${path}.scale`, message: '背景缩放必须在 0.1 到 4 之间' })
  }
  if (background.assetRef !== undefined) {
    if (typeof background.assetRef !== 'string' || !assetIds.has(background.assetRef)) {
      errors.push({ path: `${path}.assetRef`, message: `素材未登记：${String(background.assetRef)}` })
    }
  }
  if (background.type === 'asset' && !background.assetRef) {
    errors.push({ path: `${path}.assetRef`, message: '素材背景必须指定素材标识' })
  }
}

function allowedProperties(entry: UiRegistryEntry): Set<UiEditableProperty> {
  return new Set(entry.properties)
}

function checkNodeStyle(
  id: string,
  style: unknown,
  path: string,
  assetIds: Set<string>,
  errors: StudioIssue[],
  seen: Set<string>,
): void {
  const entry = findUiEntry(id)
  if (!entry) {
    errors.push({ path, message: `元素未登记：${id}` })
    return
  }
  if (!style || typeof style !== 'object') {
    errors.push({ path, message: '节点样式必须是对象' })
    return
  }
  if (seen.has(id)) {
    errors.push({ path, message: `同一作用域内重复覆盖：${id}` })
    return
  }
  seen.add(id)

  const record = style as Record<string, unknown>
  const allowed = allowedProperties(entry)
  for (const key of Object.keys(record)) {
    if (!(key in STYLE_KEYS)) {
      errors.push({ path: `${path}.${key}`, message: `未知样式字段：${key}` })
      continue
    }
    const category = STYLE_KEYS[key as keyof StudioNodeStyle]
    if (!allowed.has(category)) {
      errors.push({ path: `${path}.${key}`, message: `${entry.label} 不允许修改 ${key}` })
    }
  }

  if (entry.protection === 'protected' && Object.keys(record).length > 0) {
    errors.push({ path, message: `${entry.label} 是受保护元素，不能覆盖样式` })
  }

  if (record.offset !== undefined && record.offset !== null) {
    const offset = record.offset as Record<string, unknown>
    for (const axis of ['x', 'y'] as const) {
      const value = offset[axis]
      if (!isFiniteNumber(value) || Math.abs(value) > 4000) {
        errors.push({ path: `${path}.offset.${axis}`, message: '位移必须是 -4000 到 4000 之间的数字' })
      }
    }
  }
  // user:“子容器应当是相对于父容器的某一个边或者某几个边，设定距离，兜底距离不得小于 0”+
  // (方案 §4.4/§4.6：边锚点单轴最多一条、目标必须是同级且同父、偏移量非负；环形依赖在文档级检测)
  if (record.anchors !== undefined) {
    if (!Array.isArray(record.anchors)) {
      errors.push({ path: `${path}.anchors`, message: '锚点必须是数组' })
    } else if (record.anchors.length > 2) {
      errors.push({ path: `${path}.anchors`, message: '单轴最多一个锚点，最多两条' })
    } else {
      const axes = new Set<string>()
      const horizontalEdges = new Set(['left', 'right', 'centerX'])
      record.anchors.forEach((anchor, index) => {
        const anchorPath = `${path}.anchors[${index}]`
        if (!anchor || typeof anchor !== 'object') {
          errors.push({ path: anchorPath, message: '锚点必须是对象' })
          return
        }
        const item = anchor as Record<string, unknown>
        if (item.target !== 'parent' && item.target !== 'sibling') {
          errors.push({ path: `${anchorPath}.target`, message: '锚点目标只能是父容器或同级元素' })
        }
        if (typeof item.edge !== 'string' || !ANCHOR_EDGES.has(item.edge)) {
          errors.push({ path: `${anchorPath}.edge`, message: `锚点边无效：${String(item.edge)}` })
        } else {
          const axis = horizontalEdges.has(item.edge) ? 'x' : 'y'
          if (axes.has(axis)) {
            errors.push({ path: anchorPath, message: '同一轴只能有一个锚点（左/右/水平中心 或 上/下/垂直中心）' })
          }
          axes.add(axis)
        }
        if (!isFiniteNumber(item.offset) || item.offset < 0 || item.offset > 4000) {
          errors.push({ path: `${anchorPath}.offset`, message: '锚点距离必须在 0 到 4000 之间' })
        }
        if (item.target === 'sibling') {
          const siblingId = typeof item.siblingId === 'string' ? item.siblingId : ''
          const sibling = siblingId ? findUiEntry(siblingId) : undefined
          if (!sibling) {
            errors.push({ path: `${anchorPath}.siblingId`, message: `同级锚点必须指向已登记元素：${siblingId || '（空）'}` })
          } else if (siblingId === id) {
            errors.push({ path: `${anchorPath}.siblingId`, message: '锚点不能指向自己' })
          } else if (sibling.parent !== entry.parent) {
            errors.push({ path: `${anchorPath}.siblingId`, message: '同级锚点必须与当前元素拥有同一个父容器' })
          }
        }
      })
    }
  }
  if (record.size !== undefined && record.size !== null) {
    const size = record.size as Record<string, unknown>
    if (size.width !== undefined) checkDimension(size.width, `${path}.size.width`, errors)
    if (size.height !== undefined) checkDimension(size.height, `${path}.size.height`, errors)
  }
  if (record.spacing !== undefined && record.spacing !== null) {
    const spacing = record.spacing as Record<string, unknown>
    if (spacing.gap !== undefined && (!isFiniteNumber(spacing.gap) || spacing.gap < 0)) {
      errors.push({ path: `${path}.spacing.gap`, message: '间距必须是非负数字' })
    }
    if (spacing.mode !== undefined && spacing.mode !== 'gap' && spacing.mode !== 'margin') {
      errors.push({ path: `${path}.spacing.mode`, message: '间距模式只能是 gap 或 margin' })
    }
    if (spacing.blockExtra !== undefined
      && (!isFiniteNumber(spacing.blockExtra) || spacing.blockExtra < -200 || spacing.blockExtra > 200)) {
      errors.push({ path: `${path}.spacing.blockExtra`, message: '高度增量必须在 -200 到 200 之间' })
    }
    if (Array.isArray(spacing.padding)) {
      if (spacing.padding.length !== 4 || spacing.padding.some((item) => !isFiniteNumber(item) || item < 0)) {
        errors.push({ path: `${path}.spacing.padding`, message: '内边距需要四个非负数字' })
      }
    }
  }
  if (record.radius !== undefined) {
    const radius = record.radius
    if (Array.isArray(radius)) {
      if (radius.length !== 4 || radius.some((item) => !isFiniteNumber(item) || item < 0)) {
        errors.push({ path: `${path}.radius`, message: '圆角需要四个非负数字' })
      }
    } else if (!isFiniteNumber(radius) || radius < 0) {
      errors.push({ path: `${path}.radius`, message: '圆角必须是非负数字' })
    }
  }
  if (record.border !== undefined && record.border !== null) {
    const border = record.border as Record<string, unknown>
    if (!isFiniteNumber(border.width) || border.width < 0) {
      errors.push({ path: `${path}.border.width`, message: '描边宽度必须是非负数字' })
    }
    checkHexColor(border.color, `${path}.border.color`, errors)
  }
  if (record.color !== undefined) checkHexColor(record.color, `${path}.color`, errors)
  if (record.background !== undefined) checkBackground(record.background, `${path}.background`, assetIds, errors)
  if (record.opacity !== undefined
    && (!isFiniteNumber(record.opacity) || record.opacity < 0 || record.opacity > 1)) {
    errors.push({ path: `${path}.opacity`, message: '透明度必须在 0 到 1 之间' })
  }
  if (record.layer !== undefined && (!isFiniteNumber(record.layer) || record.layer < 0 || record.layer > 9999)) {
    errors.push({ path: `${path}.layer`, message: '层级（z）必须在 0 到 9999 之间：每 100 个 z 为一层' })
  }
  if (record.visibility !== undefined && typeof record.visibility !== 'boolean') {
    errors.push({ path: `${path}.visibility`, message: '可见性必须是布尔值' })
  }
  if (record.text !== undefined && record.text !== null) {
    const text = record.text as Record<string, unknown>
    if (text.size !== undefined && (!isFiniteNumber(text.size) || text.size <= 0)) {
      errors.push({ path: `${path}.text.size`, message: '字号必须是正数' })
    }
    if (text.lineHeight !== undefined && (!isFiniteNumber(text.lineHeight) || text.lineHeight <= 0)) {
      errors.push({ path: `${path}.text.lineHeight`, message: '行高必须是正数' })
    }
    if (text.letterSpacing !== undefined && !isFiniteNumber(text.letterSpacing)) {
      errors.push({ path: `${path}.text.letterSpacing`, message: '字间距必须是数字' })
    }
    if (text.align !== undefined && !TEXT_ALIGNS.has(String(text.align))) {
      errors.push({ path: `${path}.text.align`, message: `对齐方式无效：${String(text.align)}` })
    }
  }
}

function checkBreakpoint(
  breakpoint: unknown,
  index: number,
  assetIds: Set<string>,
  errors: StudioIssue[],
): void {
  const path = `breakpoints[${index}]`
  if (!breakpoint || typeof breakpoint !== 'object') {
    errors.push({ path, message: '断点必须是对象' })
    return
  }
  const item = breakpoint as Partial<StudioBreakpoint>
  if (typeof item.id !== 'string' || !item.id.trim()) {
    errors.push({ path: `${path}.id`, message: '断点需要标识' })
  }
  if (item.minWidth !== undefined && !isFiniteNumber(item.minWidth)) {
    errors.push({ path: `${path}.minWidth`, message: '断点宽度必须是数字' })
  }
  if (item.maxWidth !== undefined && !isFiniteNumber(item.maxWidth)) {
    errors.push({ path: `${path}.maxWidth`, message: '断点宽度必须是数字' })
  }
  if (isFiniteNumber(item.minWidth) && isFiniteNumber(item.maxWidth) && item.minWidth > item.maxWidth) {
    errors.push({ path, message: '断点最小宽度不能大于最大宽度' })
  }
  if (item.nodes && typeof item.nodes === 'object') {
    const seen = new Set<string>()
    for (const [id, style] of Object.entries(item.nodes)) {
      checkNodeStyle(id, style, `${path}.nodes.${id}`, assetIds, errors, seen)
    }
  }
}

export function validateStudioDocument(raw: unknown): StudioValidationResult {
  const errors: StudioIssue[] = []
  const warnings: StudioIssue[] = []

  if (!raw || typeof raw !== 'object') {
    return { ok: false, errors: [{ path: '', message: '主题文档必须是对象' }], warnings }
  }
  const document = raw as Record<string, unknown>

  if (document.schemaVersion !== THEME_STUDIO_SCHEMA_VERSION) {
    errors.push({
      path: 'schemaVersion',
      message: `版本不支持：${String(document.schemaVersion)}，当前为 ${THEME_STUDIO_SCHEMA_VERSION}`,
    })
  }
  if (typeof document.themeId !== 'string' || !document.themeId.trim()) {
    errors.push({ path: 'themeId', message: '主题标识不能为空' })
  }

  // user:“把布局规则变量给统一……不要再有写死的值和无法被改变的值”+
  // (布局变量只接受白名单内的名字与 px 数值，杜绝任意 CSS 注入。)
  if (document.variables !== undefined && document.variables !== null) {
    if (typeof document.variables !== 'object' || Array.isArray(document.variables)) {
      errors.push({ path: 'variables', message: '布局变量必须是对象' })
    } else {
      for (const [name, value] of Object.entries(document.variables as Record<string, unknown>)) {
        if (!LAYOUT_VARIABLES.includes(name as never)) {
          errors.push({ path: `variables.${name}`, message: `未登记的布局变量：${name}` })
          continue
        }
        if (typeof value !== 'string' || !/^\d+(\.\d+)?px$/.test(value)) {
          errors.push({ path: `variables.${name}`, message: '布局变量必须是 px 数值（如 320px）' })
          continue
        }
        const numeric = Number.parseFloat(value)
        if (!isFiniteNumber(numeric) || numeric < 0 || numeric > 4000) {
          errors.push({ path: `variables.${name}`, message: '布局变量必须在 0 到 4000px 之间' })
        }
      }
    }
  }

  const assetIds = new Set<string>()
  if (Array.isArray(document.assets)) {
    document.assets.forEach((asset, index) => {
      const path = `assets[${index}]`
      if (!asset || typeof asset !== 'object') {
        errors.push({ path, message: '素材条目必须是对象' })
        return
      }
      const item = asset as Record<string, unknown>
      if (typeof item.id !== 'string' || !item.id.trim()) {
        errors.push({ path: `${path}.id`, message: '素材需要标识' })
      } else if (!/^[A-Za-z0-9_-]+$/.test(item.id)) {
        // 素材 id 会拼进 CSS 自定义属性名与选择器（--ui-asset-*），只允许安全字符，防止注入任意 CSS。
        errors.push({ path: `${path}.id`, message: '素材标识只能包含字母、数字、下划线和连字符' })
      } else if (assetIds.has(item.id)) {
        errors.push({ path: `${path}.id`, message: `素材标识重复：${item.id}` })
      } else {
        assetIds.add(item.id)
      }
      if (typeof item.sha256 !== 'string' || !/^[0-9a-f]{64}$/i.test(item.sha256)) {
        errors.push({ path: `${path}.sha256`, message: '素材需要 64 位十六进制摘要' })
      }
      if (typeof item.mime !== 'string' || !item.mime.trim()) {
        errors.push({ path: `${path}.mime`, message: '素材需要类型' })
      }
      if (!isFiniteNumber(item.width) || item.width <= 0 || !isFiniteNumber(item.height) || item.height <= 0) {
        errors.push({ path, message: '素材尺寸必须是正数' })
      }
      if (item.url !== undefined) {
        if (typeof item.url !== 'string' || !item.url.startsWith('data:image/')) {
          errors.push({ path: `${path}.url`, message: '素材地址必须是图片 data URL' })
        } else if (item.url.length > 2_000_000) {
          errors.push({ path: `${path}.url`, message: '素材过大，单张不能超过约 2MB' })
        } else {
          // SVG 素材只作为 CSS image 渲染（不执行脚本），导入链路仍拒绝带脚本的文档（防御纵深）。
          const urlLower = item.url.toLowerCase()
          if (urlLower.startsWith('data:image/svg') && (urlLower.includes('<script') || urlLower.includes('%3cscript'))) {
            errors.push({ path: `${path}.url`, message: 'SVG 素材不允许包含脚本' })
          }
        }
      }
    })
  }

  if (document.nodes && typeof document.nodes === 'object') {
    const seen = new Set<string>()
    for (const [id, style] of Object.entries(document.nodes as Record<string, unknown>)) {
      checkNodeStyle(id, style, `nodes.${id}`, assetIds, errors, seen)
    }
  }

  if (document.templates !== undefined) {
    if (!document.templates || typeof document.templates !== 'object') {
      errors.push({ path: 'templates', message: '模板覆盖必须是对象' })
    } else {
      for (const [id, style] of Object.entries(document.templates as Record<string, unknown>)) {
        const entry = findUiEntry(id)
        if (!entry || entry.kind !== 'template') {
          errors.push({ path: `templates.${id}`, message: `模板未登记：${id}` })
          continue
        }
        const seen = new Set<string>()
        checkNodeStyle(id, style, `templates.${id}`, assetIds, errors, seen)
      }
    }
  }

  // user:“不允许环形依赖”+(方案 §4.6：同级锚点不允许成环，文档级检查)
  {
    const anchorEdges = new Map<string, string[]>()
    const collect = (id: string, style: unknown) => {
      const anchors = (style as { anchors?: unknown })?.anchors
      if (!Array.isArray(anchors)) return
      const targets = anchors
        .filter((anchor) => anchor && typeof anchor === 'object'
          && (anchor as { target?: unknown }).target === 'sibling'
          && typeof (anchor as { siblingId?: unknown }).siblingId === 'string')
        .map((anchor) => (anchor as { siblingId: string }).siblingId)
      if (targets.length > 0) anchorEdges.set(id, targets)
    }
    for (const [id, style] of Object.entries((document.nodes || {}) as Record<string, unknown>)) collect(id, style)
    for (const [id, style] of Object.entries((document.templates || {}) as Record<string, unknown>)) collect(id, style)
    const visiting = new Set<string>()
    const done = new Set<string>()
    const cyclic = (id: string): boolean => {
      if (done.has(id)) return false
      if (visiting.has(id)) return true
      visiting.add(id)
      for (const target of anchorEdges.get(id) || []) {
        if (cyclic(target)) return true
      }
      visiting.delete(id)
      done.add(id)
      return false
    }
    for (const id of anchorEdges.keys()) {
      if (cyclic(id)) {
        errors.push({ path: 'anchors', message: '锚点存在环形依赖' })
        break
      }
    }
  }

  if (document.instances !== undefined) {
    if (!document.instances || typeof document.instances !== 'object') {
      errors.push({ path: 'instances', message: '实例覆盖必须是对象' })
    } else {
      for (const [key, value] of Object.entries(document.instances as Record<string, unknown>)) {
        const path = `instances.${key}`
        if (!key.trim()) {
          errors.push({ path, message: '实例标识不能为空' })
          continue
        }
        if (!value || typeof value !== 'object') {
          errors.push({ path, message: '实例覆盖必须是对象' })
          continue
        }
        const entry = value as Record<string, unknown>
        const template = typeof entry.templateId === 'string' ? findUiEntry(entry.templateId) : undefined
        if (!template || template.kind !== 'template') {
          errors.push({ path: `${path}.templateId`, message: `实例必须指向已登记模板：${String(entry.templateId)}` })
          continue
        }
        const seen = new Set<string>()
        checkNodeStyle(template.id, entry.style, `${path}.style`, assetIds, errors, seen)
      }
    }
  }

  if (Array.isArray(document.breakpoints)) {
    document.breakpoints.forEach((breakpoint, index) => checkBreakpoint(breakpoint, index, assetIds, errors))
  }

  if (document.updatedAt !== undefined && typeof document.updatedAt !== 'string') {
    warnings.push({ path: 'updatedAt', message: '更新时间不是字符串，将按当前时间处理' })
  }

  return { ok: errors.length === 0, errors, warnings }
}

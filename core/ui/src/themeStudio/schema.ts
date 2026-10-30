/**
 * 主题文档模型（v1）。
 *
 * user:“可视化主题与布局编辑器”+
 * (编辑器保存的是声明式的布局与外观规则，不是整屏绝对坐标；文档必须带版本，
 *  能被校验、能迁移，并且只引用注册表里登记过的元素。)
 */

export const THEME_STUDIO_SCHEMA_VERSION = 1

/** 尺寸模式：固定、内容适配、填满、相对父级、等比、拉伸。 */
export type StudioSizeMode = 'fixed' | 'hug' | 'fill' | 'relative' | 'ratio' | 'stretch'

export interface StudioDimension {
  mode: StudioSizeMode
  /** fixed / relative / ratio 时的数值；hug / fill / stretch 可省略。 */
  value?: number
  min?: number
  max?: number
}

export interface StudioSize {
  width?: StudioDimension
  height?: StudioDimension
}

export interface StudioSpacing {
  gap?: number
  /**
   * user:“它这个东西应该是相对原版做了什么调整，不能把它做成一个绝对的数值，而是比如说 X+1 Y-2”+
   * (变长列表里每项的高度调整是相对增量：在自身实际高度后面叠加 N 像素，
   *  不写绝对高度、不把内容压平；负值等于收紧。)
   */
  blockExtra?: number
  /**
   * user:“那个间距是干啥的？为什么我调了半天也没有反应呢？”+
   * (gap 只对 flex/grid 生效；块级容器改用子项外边距（margin-block-start），
   *  保证“间距”在两类容器上都有实际效果。未设置时按 gap 编译。)
   */
  mode?: 'gap' | 'margin'
  /** 上、右、下、左。 */
  padding?: [number, number, number, number]
}

export type StudioBackgroundFit = 'fixed' | 'contain' | 'cover' | 'stretch' | 'nineSlice' | 'tile'

/**
 * user:“有些样式背景颜色不是纯色而是透明，而且那个背景色除了可直接选色，也应该和主题 token 关联上”+
 * (背景颜色可以是自定义色、透明，或绑定主题令牌：令牌编译成 var(--theme-*)，
 *  跟随主题预设自动变化；白名单限定可绑令牌，杜绝借字段注入任意 CSS。)
 */
export const STUDIO_COLOR_TOKENS = [
  'transparent',
  'main-background',
  'main-soft-background',
  'backdrop-background',
  'composer-background',
  'control-background',
] as const

export type StudioColorToken = typeof STUDIO_COLOR_TOKENS[number]

/**
 * user:“把布局规则变量给统一……不要再有写死的值和无法被改变的值”+
 * (布局几何全部收敛到这几条变量：编辑器改尺寸写变量，主区域/输入栏等
 *  由变量派生的位置自动跟随，不再出现元素改了而布局不动的情况。)
 */
export const LAYOUT_VARIABLES = [
  '--layout-sidebar-width',
  '--layout-right-drawer-width',
  '--layout-rail-width',
  '--layout-titlebar-height',
  '--layout-composer-height',
  '--layout-bottom-inset',
  // user:“我认为主区和分屏本质是一个容器”+(分屏主面板宽度也是内容区的几何，同属布局变量)
  '--layout-split-primary-width',
] as const

export type StudioLayoutVariable = typeof LAYOUT_VARIABLES[number]

/** 背景溢出策略：裁剪、本地外绘、独立装饰层。 */
export type StudioBackgroundOverflow = 'clipped' | 'local-visible' | 'decoration-portal'

export interface StudioGradientStop {
  color: string
  position: number
}

export interface StudioBackground {
  type: 'solid' | 'gradient' | 'asset'
  /** 自定义底色（十六进制），或 'transparent' 表示显式透明。 */
  color?: string
  /** 绑定主题令牌；设置后优先于 color，编译成 var(--theme-*)，跟随主题预设变化。 */
  colorToken?: StudioColorToken
  stops?: StudioGradientStop[]
  angle?: number
  /** 素材标识，只允许引用 assets 表里登记过的条目。 */
  assetRef?: string
  fit?: StudioBackgroundFit
  /**
   * user:“添加的图像应该可以裁切、位移、缩放等等”+
   * (位置=背景焦点百分比（默认 50/50 居中）；缩放=相对原始尺寸的倍数，
   *  裁切交给 fit（cover/contain/九宫格），三者互不干扰。)
   */
  positionX?: number
  positionY?: number
  scale?: number
  overflow?: StudioBackgroundOverflow
  /**
   * user:“我不是说过图像不被容器裁切吗”+
   * (本地外绘需要元素成为定位宿主；编辑器在开启溢出时探测元素的 computed position，
   *  原本是 static 才记下这个标记，编译时补 position: relative，绝不覆盖已有定位。)
   */
  overflowHost?: 'relative'
  /** 背景自身透明度，与组件整体透明度分开。 */
  opacity?: number
  /** 九宫格切片，单位像素；fit 为 nineSlice 时生效。 */
  slice?: { top: number; right: number; bottom: number; left: number }
}

export interface StudioText {
  size?: number
  lineHeight?: number
  letterSpacing?: number
  align?: 'left' | 'center' | 'right'
}

export type StudioAnchorEdge = 'left' | 'right' | 'top' | 'bottom' | 'centerX' | 'centerY'

/**
 * user:“子容器应当是相对于父容器的某一个边或者某几个边，设定距离，而在兜底呢，就是距离不得小于 0”+
 * (方案 §4.4：锚点明确引用目标对象的边/中心线，不能只存“相距某某 px”；
 *  单轴最多一个锚点，避免过约束与环形依赖，偏移量不得为负。)
 */
export interface StudioNodeAnchor {
  target: 'parent' | 'sibling'
  /** target='sibling' 时的同级节点标识。 */
  siblingId?: string
  edge: StudioAnchorEdge
  /** 与目标边/中心线的距离，逻辑 px，兜底不得小于 0。 */
  offset: number
}

export interface StudioNodeStyle {
  /** 相对自身布局位置的位移；用独立的 translate 表达，不参与布局流，也不覆盖组件已有的 transform。 */
  offset?: { x: number; y: number }
  /** 边锚点：相对父容器（或同级）的边距定位，按方案 §4.4 建模。 */
  anchors?: StudioNodeAnchor[]
  size?: StudioSize
  spacing?: StudioSpacing
  radius?: number | [number, number, number, number]
  border?: { width: number; color: string }
  color?: string
  background?: StudioBackground
  text?: StudioText
  opacity?: number
  /**
   * user:“我想的是 Z-index 从 1~9999 一直分层，然后 100 个 z 为一层，上限约 100 层……
   *  这个图层应该像 PS 一样可单独编辑，显隐/锁定等”+
   * (层 = 100 个 z 一段：第 N 层占 (N-1)*100+1 ~ N*100；层内 100 个位置防止同容器打架。
   *  显隐/锁定是编辑器会话状态，不进主题文档、不影响发布。)
   */
  layer?: number
  visibility?: boolean
}

export interface StudioBreakpoint {
  id: string
  /** 生效区间；两端都可省略表示不限。 */
  minWidth?: number
  maxWidth?: number
  nodes: Record<string, StudioNodeStyle>
}

export interface StudioAsset {
  id: string
  sha256: string
  mime: string
  width: number
  height: number
  /** 内嵌地址（data URL）。运行端通过 assetUrl 回调解析，不做网络请求。 */
  url?: string
}

export interface StudioDocument {
  schemaVersion: number
  themeId: string
  /** 以注册表标识为键，只允许登记过的元素。 */
  nodes: Record<string, StudioNodeStyle>
  /** 布局几何变量覆盖（白名单 + 像素值），编译成 :root 变量，驱动整条布局链。 */
  variables?: Partial<Record<StudioLayoutVariable, string>>
  /** 模板覆盖：改一处，所有同类节点一起变。 */
  templates?: Record<string, StudioNodeStyle>
  /** 实例覆盖：以业务编号为键，只改这一条消息或这一个会话。 */
  instances?: Record<string, { templateId: string; style: StudioNodeStyle }>
  breakpoints: StudioBreakpoint[]
  assets: StudioAsset[]
  updatedAt: string
}

/** 建一份空文档；没有覆盖时界面按默认样式运行。 */
export function createEmptyStudioDocument(themeId: string, now = new Date()): StudioDocument {
  return {
    schemaVersion: THEME_STUDIO_SCHEMA_VERSION,
    themeId,
    nodes: {},
    templates: {},
    instances: {},
    breakpoints: [],
    assets: [],
    updatedAt: now.toISOString(),
  }
}

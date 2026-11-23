// user:“favicon 进标签栏”+(浏览器组件只负责上报，标签栏从共享 store 取图)。
import { forgetBrowserTabIcon, setBrowserTabIcon } from '@/split/browserIcons'
import { errorCode } from '@/split/browserErrorText'
import { invoke } from '@tauri-apps/api/core'
import { listen, type UnlistenFn } from '@tauri-apps/api/event'

export interface SplitFileEntry { name: string; path: string; directory: boolean }
export function hasSplitNative(): boolean { return typeof window !== 'undefined' && Boolean((window as unknown as Record<string, unknown>).__TAURI_INTERNALS__) }
export async function splitNative<T>(command: string, args: Record<string, unknown>): Promise<T> {
  if (!hasSplitNative()) throw Error('此功能需要在桌面应用中使用')
  return invoke<T>(command, args)
}

// user:“label 由 Rust 分配，前端不能自定义”+(分屏标签 id 来自前端布局模型，浏览器标签 id 来自 Rust，映射只存在内存里；
// 重启后旧 id 全部作废，标签按 URL 重新创建，所以这份映射不写进 localStorage)。
// user:“什么 bug？”+(把映射挂在 globalThis 上，避免 Vite 热更新重载 native.ts 时清空已创建的原生标签映射而报「网页还没打开」)
const browserTabs: Map<string, string> =
  ((globalThis as Record<string, unknown>).__sundayBrowserTabs as Map<string, string> | undefined)
  ?? ((globalThis as Record<string, unknown>).__sundayBrowserTabs = new Map<string, string>())

function browserTab(id: string): string {
  const tab = browserTabs.get(id)
  if (!tab) throw Error('网页还没打开')
  return tab
}

function reverseTab(tab: string): string | undefined {
  for (const [splitId, browserId] of browserTabs) if (browserId === tab) return splitId
  return undefined
}

/** 原生标签是否已经有对应的分屏标签（收养之前先问一句，避免重复收养）。 */
export function splitTabForNative(tab: string): string | undefined {
  return reverseTab(tab)
}

/**
 * user:“第一次搜索建 agent-browser 分屏”+(Agent 从 Core 里开的标签没有前端映射：
 * 收养时必须由前端补上「分屏标签 id <-> 原生标签 id」，否则矩形同步、点击输入、
 * 状态事件全都对不上号)。
 */
export function bindBrowserTab(splitId: string, nativeTab: string): void {
  if (!splitId || !nativeTab) return
  browserTabs.set(splitId, nativeTab)
}

/**
 * user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
 * (这份映射是「分屏标签 → 原生标签」的唯一样本；原生侧说标签没了（tab_not_found）时，
 *  映射已经死了，必须丢掉。否则下一次 create 还会以为网页已经建好、只去同步一个不存在的矩形，
 *  于是一直失败、错误条一直挂着。这里只丢映射，不调 browser_close —— 标签本来就不在了)。
 */
export function forgetBrowserTab(id: string): void {
  if (!browserTabs.delete(id)) return
  forgetBrowserTabIcon(id)
}

/** `services.subscribe` 回调收到的统一事件形状。 */
export interface BrowserNativeEvent {
  /** 分屏标签 id（前端布局模型里的 id），不是 Rust 的 browser-* 标签。 */
  id: string
  url?: string
  loading?: boolean
  title?: string
  /** 站点图标（data URL 或绝对地址）；没有就是 null。 */
  favicon?: string | null
  canGoBack?: boolean
  canGoForward?: boolean
  zoom?: number
  crashed?: boolean
  /** 这个标签现在归谁：`agent` / `human`（用户动过就归人，写操作会被拒）。 */
  owner?: 'agent' | 'human'
  /** 网页申请新窗口（`target=_blank`）：要在同一个分屏里开新标签。 */
  openTab?: { url: string; opener?: string }
  find?: { matches: number; index: number; action?: string }
  fullscreen?: boolean
  error?: { code: string; message: string; retriable: boolean; host?: string }
  /** 网页发起的权限请求（Rust 已按拒绝处理，带 requestId 时等用户确认）。 */
  permission?: { host: string; kind: string; decision: 'allow' | 'deny'; scope?: string; requestId?: string; message: string }
  /** 站数据清理完成。 */
  siteData?: { host: string; kinds: string[]; cleared: boolean; message: string }
  /** 越权自检结果（网页里能不能摸到 Tauri IPC）。 */
  /** 下载状态变化（开始/完成/失败三态）。 */
  download?: { record: { id: string; tab: string; url: string; filename: string; path?: string | null; state: 'started' | 'finished' | 'failed'; needsApproval: boolean; startedAt: string; finishedAt?: string | null } }
  diagnostics?: { passed: boolean; checks: Array<{ name: string; passed: boolean; detail: string }>; message: string }
}

/**
 * user:“网页跑到分屏外面”+(坐标空间约定：**这里是 CSS px → 物理像素的唯一换算入口**。
 * 前端算矩形一律用 CSS px（`getBoundingClientRect()` 的原生单位），到这个命令边界上乘一次
 * `devicePixelRatio`；Rust 侧只认物理像素、用 `PhysicalPosition/PhysicalSize`，不再乘窗口
 * scale_factor。两套比例分开算过一次就够——以前前端传 CSS px 当逻辑像素，页面一旦有缩放
 * （实测 dpr=1.85、窗口 scale=1.25），落点就会偏 dpr/scale≈1.48 倍，表现为“跑到分屏外面”)。
 */
/**
 * user:“把「网页矩形」从组件量 DOM 改成布局算一次、直接下发”+(V2-B 契约层：
 * 入参是**布局算出的 contentRect（CSS px）**，本函数只做 CSS px × devicePixelRatio →
 * 物理像素、整数化、最小 1px。不再接受任何 DOM 测量值——组件里的
 * `getBoundingClientRect()` 取值路径在 V2-C 统一移除。)
 */
export interface WebviewRectInput {
  /** 分屏表面 id（对应布局模型里的 surface/pane id）。 */
  surfaceId: string
  /** 布局算出的内容区矩形，CSS px，相对主窗口视口。 */
  contentRect: { x: number; y: number; width: number; height: number }
  visible: boolean
}

export interface WebviewBoundsArgs {
  label: string
  x: number
  y: number
  width: number
  height: number
  visible: boolean
}

/**
 * user:“矩形契约（唯一来源）”+(物理像素 = round(CSS px × dpr)；宽高至少 1px，
 * 因为 WebView2 拒绝 0 尺寸。**任何地方都不许再乘第二次 dpr**。)
 */
export function webviewBoundsArgs(input: WebviewRectInput, dpr: number): WebviewBoundsArgs {
  const factor = Number.isFinite(dpr) && dpr > 0 ? dpr : 1
  const px = (value: number) => Math.round(value * factor)
  const rect = input.contentRect
  // user:“传递容器尺寸”+(先转换左右、上下边界，避免高 DPI 下起点和宽高各自取整造成尺寸偏差)。
  const x = px(rect.x)
  const y = px(rect.y)
  return {
    label: input.surfaceId,
    x,
    y,
    width: Math.max(1, px(rect.x + rect.width) - x),
    height: Math.max(1, px(rect.y + rect.height) - y),
    visible: input.visible,
  }
}

/**
 * @deprecated V2-C 移除：旧的「组件量 DOM 后传 options」形状。
 * 新代码一律用 {@link webviewBoundsArgs}（布局算好的 contentRect 直接传）。
 */
function boundsArgs(options: Record<string, unknown>) {
  // user:“V2-C1b：组件直接下发物理像素”+(带 physical 标记时不再乘 dpr，
  // 否则会和 webviewBoundsArgs 里的乘法叠成 dpr²。)
  if (options.physical === true) {
    return {
      x: Math.round(Number(options.x ?? 0)),
      y: Math.round(Number(options.y ?? 0)),
      width: Math.max(1, Math.round(Number(options.width ?? 1))),
      height: Math.max(1, Math.round(Number(options.height ?? 1))),
      visible: Boolean(options.visible ?? false),
      trace: options.trace === undefined || options.trace === null ? null : String(options.trace),
      isFloat: options.isFloat === undefined ? null : Boolean(options.isFloat),
      stackIndex: options.stackIndex == null ? null : Number(options.stackIndex),
      // user:“两个网页重叠”+(同组互斥的组名：'area:<分屏>' / 'surface:<浮窗>'，Rust 拿它收起同组的其它网页)。
      group: options.group === undefined || options.group === null ? null : String(options.group),
    }
  }
  const dpr = typeof window === 'undefined' ? 1 : (window.devicePixelRatio || 1)
  const converted = webviewBoundsArgs({
    surfaceId: String(options.surfaceId ?? ''),
    contentRect: {
      x: Number(options.x ?? 0),
      y: Number(options.y ?? 0),
      width: Number(options.width ?? 1),
      height: Number(options.height ?? 1),
    },
    visible: Boolean(options.visible ?? false),
  }, dpr)
  return {
    x: converted.x,
    y: converted.y,
    width: converted.width,
    height: converted.height,
    visible: converted.visible,
    trace: options.trace === undefined || options.trace === null ? null : String(options.trace),
    isFloat: options.isFloat === undefined ? null : Boolean(options.isFloat),
    stackIndex: options.stackIndex == null ? null : Number(options.stackIndex),
  }
}

type ReopenReply = { url: string; title: string }

// user:“导航 + 标签骨架”+(旧调用形状保持不变，内部换成 browser_* 新命令集；旧的单命令浏览器入口已删除)。
async function dispatchBrowserNative(id: string, action: string, options: Record<string, unknown> = {}): Promise<unknown> {
  switch (action) {
    case 'create': {
      // 已经有原生 webview 时，重复 create 等价于同步一次矩形。
      if (browserTabs.has(id)) return browserNative(id, 'bounds', options)
      const { tab } = await splitNative<{ tab: string }>('browser_open', { url: String(options.url ?? ''), profile: String(options.profile ?? 'normal') })
      browserTabs.set(id, tab)
      return splitNative<void>('browser_bounds', { tab, ...boundsArgs(options) })
    }
    case 'bounds':
      return splitNative<void>('browser_bounds', { tab: browserTab(id), ...boundsArgs(options) })
    // user:“迁移”+(透明主界面上的网页区域把鼠标/滚轮事件转发给 CompositionController)
    case 'input':
      return splitNative<void>('browser_input', {
        tab: browserTab(id),
        kind: Number(options.kind ?? 0),
        virtualKeys: Number(options.virtualKeys ?? 0),
        wheelDelta: Number(options.wheelDelta ?? 0),
        x: Math.round(Number(options.x ?? 0)),
        y: Math.round(Number(options.y ?? 0)),
      })
    // user:“遮挡的问题用冻结加模糊”+(让位前调用 Rust browser_screenshot 截一帧视口图做模糊底图)
    case 'screenshot':
      return splitNative<{ png?: string }>('browser_screenshot', { tab: browserTab(id), target: String(options.target ?? 'viewport') })
    case 'control':
      // user:“我怎么把页面交给agent？”+(用户动过页面后归人：这条就是「交回给 Agent」的宿主动作)。
      return splitNative<{ tab: string; owner: string }>('browser_control', {
        tab: browserTab(id),
        action: String(options.action ?? 'status'),
      })
    case 'activate':
      return splitNative<void>('browser_activate', { tab: browserTab(id) })
    case 'navigate':
      return splitNative<void>('browser_nav', {
        tab: browserTab(id),
        action: 'navigate',
        url: options.url === undefined ? null : String(options.url),
        query: options.query === undefined ? null : String(options.query),
      })
    case 'back':
    case 'forward':
    case 'reload':
    case 'stop':
      return splitNative<void>('browser_nav', { tab: browserTab(id), action })
    case 'state':
      return splitNative<BrowserNativeEvent>('browser_state', { tab: browserTab(id) })
    case 'find':
      return splitNative<void>('browser_find', {
        tab: browserTab(id),
        action: String(options.action ?? 'start'),
        query: options.query === undefined ? null : String(options.query),
        matchCase: Boolean(options.matchCase ?? false),
      })
    case 'zoom':
      return splitNative<{ zoom: number }>('browser_zoom', {
        tab: browserTab(id),
        action: String(options.action ?? 'set'),
        value: options.value === undefined ? null : Number(options.value),
      })
    case 'fullscreen':
      return splitNative<void>('browser_fullscreen', { tab: browserTab(id), on: Boolean(options.on) })
    case 'profiles':
      // user:“新标签旁的下拉：普通 / 临时”+(不可用时置灰，不静默建成共享会话)。
      return splitNative<{ profiles: Array<{ name: string; label: string; available: boolean; persistent: boolean; note: string }>; temporarySessionAvailable: boolean }>('browser_profiles', {})
    case 'permission':
      // user:“前端最小授权确认后回命令放行（仅本次/该站点）”+(授权表只由 Rust 写)。
      return splitNative<void>('browser_permission', {
        tab: browserTab(id),
        requestId: String(options.requestId ?? ''),
        decision: String(options.decision ?? 'deny'),
        scope: options.scope === undefined ? null : String(options.scope),
      })
    case 'clearSiteData':
      return splitNative<void>('browser_clear_site_data', {
        tab: browserTab(id),
        host: String(options.host ?? ''),
        kinds: Array.isArray(options.kinds) ? options.kinds.map(String) : null,
      })
    case 'certificate':
      return splitNative<void>('browser_certificate', {
        tab: browserTab(id),
        host: String(options.host ?? ''),
        action: String(options.action ?? 'continue'),
      })
    case 'downloads':
      return splitNative<Array<{ id: string; tab: string; url: string; filename: string; path?: string | null; state: 'started' | 'finished' | 'failed'; needsApproval: boolean; startedAt: string; finishedAt?: string | null }>>('browser_downloads', { tab: options.tab === undefined ? null : String(options.tab) })
    case 'download':
      // user:“危险后缀要审批才能打开”+(approve 只在用户二次确认后才为 true)。
      return splitNative<void>('browser_download', {
        id: String(options.id ?? ''),
        action: String(options.action ?? 'reveal'),
        approve: options.approve === undefined ? null : Boolean(options.approve),
      })
    case 'diagnostics':
      return splitNative<void>('browser_diagnostics', { tab: browserTab(id) })
    case 'reopen':
      return splitNative<ReopenReply>('browser_reopenClosed', {})
    case 'close': {
      const tab = browserTabs.get(id)
      // 还没创建过原生 webview 的标签（懒加载）关闭时是空操作。
      if (!tab) return
      forgetBrowserTab(id)
      return splitNative<void>('browser_close', { tab })
    }
    default:
      throw Error(`未知的浏览器操作：${action}`)
  }
}

/**
 * user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
 * (失败要留下可检索的一条日志：错误条只给人话，排查时需要知道是哪个动作、哪个标签、什么码；
 *  tab_not_found 同时说明映射已经失效，立刻丢掉，下一次 create 才会真的重开网页)。
 */
export async function browserNative(id: string, action: string, options: Record<string, unknown> = {}): Promise<unknown> {
  try {
    return await dispatchBrowserNative(id, action, options)
  } catch (cause) {
    if (errorCode(cause) === 'tab_not_found') forgetBrowserTab(id)
    const message = cause && typeof cause === 'object' && 'message' in cause ? String((cause as { message?: unknown }).message ?? '') : String(cause ?? '')
    console.warn('[browser-native]', JSON.stringify({ surface: id, action, code: errorCode(cause), message }))
    throw cause
  }
}

/** 订阅 Rust 侧的浏览器事件，并把 Rust 标签 id 翻译回分屏标签 id。 */
export async function subscribeBrowserEvents(callback: (event: BrowserNativeEvent) => void): Promise<UnlistenFn> {
  const off: UnlistenFn[] = []
  off.push(await listen<{ tab: string; url: string; title: string; favicon?: string | null; loading: boolean; canGoBack: boolean; canGoForward: boolean; zoom: number; crashed: boolean; owner?: string }>(
    'lamtools://browser-state',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      // user:“无 favicon 时用首字母占位”+(空值写回 store 会把旧图标清掉，避免显示上一个站点)。
      if (id) setBrowserTabIcon(id, payload.favicon ?? null)
      if (id) callback({ id, url: payload.url, title: payload.title, loading: payload.loading, canGoBack: payload.canGoBack, canGoForward: payload.canGoForward, zoom: payload.zoom, crashed: payload.crashed, owner: payload.owner === 'human' ? 'human' : 'agent' })
    },
  ))
  off.push(await listen<{ tab: string; url: string; opener?: string; userInitiated: boolean }>(
    'lamtools://browser-pending-tab',
    ({ payload }) => {
      // 新标签还没被前端认识；先把请求挂到 opener 所在的分屏标签上。
      const id = reverseTab(payload.opener ?? '') ?? reverseTab(payload.tab)
      if (id) callback({ id, openTab: { url: payload.url, opener: payload.opener } })
    },
  ))
  off.push(await listen<{ tab: string; matches: number; index: number; action?: string | null }>(
    'lamtools://browser-find',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, find: { matches: payload.matches, index: payload.index, action: payload.action ?? undefined } })
    },
  ))
  off.push(await listen<{ tab: string; fullscreen: boolean }>(
    'lamtools://browser-fullscreen',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, fullscreen: payload.fullscreen })
    },
  ))
  off.push(await listen<{ tab: string; code: string; message: string; retriable: boolean; host?: string | null }>(
    'lamtools://browser-error',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, error: { code: payload.code, message: payload.message, retriable: payload.retriable, host: payload.host ?? undefined } })
    },
  ))
  off.push(await listen<{ tab: string; host: string; kind: string; decision: 'allow' | 'deny'; scope?: string | null; requestId?: string | null; message: string }>(
    'lamtools://browser-permission',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, permission: { host: payload.host, kind: payload.kind, decision: payload.decision, scope: payload.scope ?? undefined, requestId: payload.requestId ?? undefined, message: payload.message } })
    },
  ))
  off.push(await listen<{ tab: string; host: string; kinds: string[]; cleared: boolean; message: string }>(
    'lamtools://browser-site-data',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, siteData: { host: payload.host, kinds: payload.kinds, cleared: payload.cleared, message: payload.message } })
    },
  ))
  off.push(await listen<{ tab: string; record: { id: string; tab: string; url: string; filename: string; path?: string | null; state: 'started' | 'finished' | 'failed'; needsApproval: boolean; startedAt: string; finishedAt?: string | null } }>(
    'lamtools://browser-download',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, download: { record: payload.record } })
    },
  ))
  off.push(await listen<{ tab: string; passed: boolean; checks: Array<{ name: string; passed: boolean; detail: string }>; message: string }>(
    'lamtools://browser-diagnostics',
    ({ payload }) => {
      const id = reverseTab(payload.tab)
      if (id) callback({ id, diagnostics: { passed: payload.passed, checks: payload.checks, message: payload.message } })
    },
  ))
  return () => { for (const stop of off) stop() }
}

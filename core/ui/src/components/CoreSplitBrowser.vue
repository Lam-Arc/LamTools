<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { UnlistenFn } from '@tauri-apps/api/event'
import { ArrowLeft, ArrowRight, ChevronDown, ChevronUp, ExternalLink, Globe, MoreHorizontal, PictureInPicture2, Plus, RotateCw, Search, Square, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { browserNative, forgetBrowserTab, hasSplitNative, subscribeBrowserEvents, webviewBoundsArgs, type BrowserNativeEvent } from '@/split/native'
import { hostBlockedByOverlay, obscuresHostNode } from '@/split/browserOverlay'
import { browserVisible, layoutPhaseOfController, serializeBounds, type BrowserLayoutPhase } from '@/split/browserVisibility'
// user:“落点矩形必须满足不变量：完全落在所属 pane 的内容区内（不含标签栏、不含页眉、不与标题栏相交）”+
// (原生 webview 画在 DOM 之上，越界多少就吃掉多少点击：越到页眉则「更多」点不动，越到标题栏则最大化/最小化点不动。
//  这里不是“再减一点”，而是把不变量当成取值的定义：与 pane 内容区求交，交集为空就退化为不可见)。
import { clampToHost, createLogThrottle, createRectDiagnostics, fitRectToContent, rectOverflow, type SplitRect } from '@/split/browserLayout'
import { WORKSPACE_AREA_RECT, WORKSPACE_COMPOSED_RECT } from './workspaceInjection'
import { addressText, BrowserAddressError, getStoredSearchEngine, resolveAddress } from '@/split/browserAddress'
// user:“地址栏下方出现 [object Object] 文本”+(原生失败对象只经过 errorText 变成一句话，
//  组件里任何地方都不许再写 String(错误)：那正是 [object Object] 的来源)。
import { errorCode, errorText } from '@/split/browserErrorText'
// user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
// (判定与重建节流在 browserRecovery：这里只把“标签丢了”变成一次自愈，而不是一条常驻红字)。
import { canRebuildLostTab, nativeTabLost } from '@/split/browserRecovery'
// user:“browser 首页 UI参考，核心仅为中间的输入栏，上方的网址栏和标签页，其余均为可选自定义组件或不实现”+
// (首页只在“这个标签没有可见网页”时出现；判据与问候语时段都在 browserHome，组件只负责画)。
import BrowserHomeView from './BrowserHomeView.vue'
import { browserHomeVisible } from '@/split/browserHome'
// user:“悬浮窗：可拖动、可缩放的小窗…原生 webview 没有圆角与阴影，所以浮窗外观要用 DOM 边框 + 内缩”+
// (形态与矩形的算术全在 surfaceModes：这里只把结论变成一次 CSS 定位和一次 browser_bounds)。
import { defaultFloatFrame, exclusiveSurfaceOwners, fitFloatFrame, moveFloatFrame, normalizeZoom, resizeFloatFrame, surfaceAvailability, zoomPercent, type SurfaceFrame, type SurfaceMode } from '@/workspace/surface'
// user:“会话三态：普通 / 临时”+(形态与权限提示的纯逻辑在 browserSession，组件只负责显示与触发)。
import { downloadApprovalText, downloadStateLabel, downloadSummary, permissionPromptTitle, permissionResultText, profileBadge, profileOptions, siteDataHost, siteDataKindsArg, type BrowserDownloadRecord, type BrowserProfileKind } from '@/split/browserSession'
import { openExternalUrl } from '@/helpers/openUrl'
import { t } from '@/i18n'
import { contextMenuState } from './context-menu/context-menu'
// user:“加一条 dev-only 的命中测试诊断…支持用一个临时键盘快捷键触发一次（仅 dev）”+(Ctrl+Alt+Shift+H)。
import { autoHitTestEnabled, createAutoHitTest, installHitTestShortcut, installStealProbe } from '@/split/hitTest'
// user:“把「有浮层」这件事统一登记，让网页无条件让位”+(登记表在 split/browserOverlays，判定仍只有 browserVisibility 一份)。
import { closeOverlay, openOverlay, overlayDepth } from '@/split/browserOverlays'
import type { SplitTab } from '@/workspace/types'
import type { WorkspaceController } from '@/workspace/types'

export interface SplitBrowserServices {
  available: () => boolean
  call: (id: string, action: string, options?: Record<string, unknown>) => Promise<unknown>
  subscribe: (callback: (event: BrowserNativeEvent) => void) => Promise<UnlistenFn>
  openExternal: (url: string) => Promise<void>
}
// user:“交互测试”“支持一下”+(可注入隔离浏览器服务；可选的 pane/controller 让浏览器自己能开新标签)。
const props = defineProps<{ tab: SplitTab; visible: boolean; services?: SplitBrowserServices; pane?: string; controller?: WorkspaceController }>()
// user:“快速精准高效的解决”+(导航和缩放写回同一份可恢复的标签记录)。
function updateTab(patch: Partial<Pick<SplitTab, 'resource' | 'title' | 'zoom'>>) {
  if (props.controller?.updateTabMetadata) props.controller.updateTabMetadata(props.tab.id, patch)
  else Object.assign(props.tab, patch)
}
const services: SplitBrowserServices = props.services ?? {
  available: hasSplitNative,
  call: browserNative,
  subscribe: subscribeBrowserEvents,
  openExternal: async url => { if (!await openExternalUrl(url)) throw new Error('无法打开默认浏览器') },
}
// user:“浏览器地址栏里显示出 [object Object]”+(地址栏只收字符串：标签上万一带着对象/数字，
// 输入框回落成空字符串，绝不把 String(对象) 的结果贴到地址栏里；标题同理)。
const address = ref(addressText(props.tab.resource)), host = ref<HTMLElement | null>(null), error = ref(''), retriable = ref(false)
// user:“我怎么把页面交给agent？有UI吗？”+(用户动过这个网页后它归人：页眉显示「交回给 Agent」，
// 点了就把控制权还给 Agent；不点也行，静默 45 秒会自动交还)。
const owner = ref<'agent' | 'human'>('agent')
// 静默 45 秒由宿主结算：到了再问一次状态，让按钮自己消失（不在前端复制一套计时规则）。
let ownerPollTimer: ReturnType<typeof setTimeout> | null = null
function scheduleOwnerPoll(): void {
  if (ownerPollTimer) clearTimeout(ownerPollTimer)
  ownerPollTimer = setTimeout(() => {
    ownerPollTimer = null
    void services.call(props.tab.id, 'control', { action: 'status' }).catch(() => {})
  }, 46_000)
}

async function handBackToAgent(): Promise<void> {
  try {
    await services.call(props.tab.id, 'control', { action: 'hand_to_agent' })
    owner.value = 'agent'
  } catch (e) {
    if (!recoverLostNativeTab(e)) error.value = errorText(e)
  }
}
/** user:“网页跑到分屏外面”+(诊断用自增序号：每条 [bounds-send] 都带唯一 trace，便于和 Rust 侧对齐)。 */
let syncSeq = 0
// user:“地址栏下方出现 [object Object] 文本”+(模板只读这两个派生标签：无论上游把字符串、Error 还是
//  Rust 的 {code,message} 对象塞进 error/notice，画出来的都只会是一句话)。
const errorLabel = computed(() => error.value ? errorText(error.value) : '')
const noticeLabel = computed(() => notice.value ? errorText(notice.value, '') : '')
const loading = ref(false), created = ref(false), title = ref(addressText(props.tab.title))
// user:“当浏览器标签没有地址（tab.resource 为空、尚未创建 webview）时，在 pane 内渲染一张首页而不是空白”+
// (判据只有“有没有活着的网页”：created=false 时原生 webview 根本不存在，首页不会被它盖住；
//  上次建失败也退回家首页，把原因一起说清，而不是留一张白屏)。
const homeFailed = ref(false), addressField = ref<HTMLInputElement | null>(null), homeRef = ref<InstanceType<typeof BrowserHomeView> | null>(null)
const homeVisible = computed(() => browserHomeVisible({ resource: addressText(props.tab.resource), created: created.value, failed: homeFailed.value }))
// user:“手动在地址栏里输入时，状态推送不能把它抹掉”+(浏览器事件很密：加载、标题、缩放每次推送都会带当前网址；
// 用户正在输入时只更新标签记录，通知栏里的文字不动，失焦后再回到页面真实地址，和常见浏览器一致)。
const editingAddress = ref(false)
function focusAddress() { editingAddress.value = true }
function blurAddress() { editingAddress.value = false; address.value = addressText(props.tab.resource) || address.value }
// user:“页面缩放…与 browser_zoom 已有命令对接，并与 pane 比例分开记忆”+
// (读数从标签自己的 zoom 起步：网页还没建起来时工具栏也不该骗人说自己 100%)。
const canBack = ref(false), canForward = ref(false), zoom = ref(normalizeZoom(props.tab.zoom ?? 1))
// user:“模式切换：工具栏一个模式按钮（分屏/全屏/悬浮）+ 快捷键；切模式不重新加载页面”+
// (形态记在标签上：切标签再切回来还是它；这里只改 CSS 与 bounds，webview 实例从头到尾是同一个)。
const surface = computed(() => props.tab.surface === 'float' ? 'float' : 'split')
// user:“不行，依旧不行，实际原因应该是层级关系原因，浮层反而被放在主内容下方了”+
// (V2 工作区里浮层状态存在 controller.floats 中，不一定写回 tab.surface；两处任一为 float 即判定为浮层)
const isFloatSurface = computed(() =>
  surface.value === 'float' || Boolean(props.controller?.floats?.value?.some(f => f.tab.id === props.tab.id)),
)
// user:“层级应为红>绿>黄”+(浏览器合成顺序沿用浮窗数组，分屏处于 0 层)。
const stackIndex = computed(() => (props.controller?.floatOrder?.value.indexOf(props.tab.id) ?? -1) + 1)
const registerComposedRect = inject(WORKSPACE_COMPOSED_RECT, null)
const composedVisible = ref(false)
onBeforeUnmount(() => registerComposedRect?.(props.tab.id, null))
onBeforeUnmount(() => { if (ownerPollTimer) clearTimeout(ownerPollTimer) })

// user:“页眉上要留的就是前进、返回、刷新、地址栏和一个『更多』”+(页眉只有一个菜单：原来形态/站点/会话三个下拉都收进它)。
const moreMenuOpen = ref(false)
// user:“迁移”+(DirectComposition 模式下菜单/弹出层直接压在活网页之上；但浮层拖动/缩放或分隔条拖拽时改用「冻结截图+模糊」以保持 120fps 跟手不掉帧)
const isComposed = computed(() => hasSplitNative())
const dragYield = computed(() => (
  created.value
  && !homeVisible.value
  && (
    visibilityPhase() === 'resizingDivider'
    || visibilityPhase() === 'draggingTab'
    || (isFloatSurface.value && props.controller?.interactionPhase?.value === 'floating')
  )
))
const overlayYield = computed(() => (
  dragYield.value
  || (
    !isComposed.value
    && created.value
    && !homeVisible.value
    && (overlayDepth() > 0 || contextMenuState.open)
  )
))
// user:“拖动/缩放时先隐藏网页、显示占位块，松手后提交 bounds”+(占位块与“正在挪窗”的读数都由它决定)。
const surfaceGesture = ref<'none' | 'move' | 'resize'>('none')
// user:“点击外部不关闭，只置顶/置底切换”+(置底 = 网页先让开、框留着；再点一下恢复，不会不见)。
const floatBehind = ref(false)
const zoomLabel = computed(() => zoomPercent(zoom.value))
const surfaceSupport = computed(() => surfaceAvailability(props.tab))
/**
 * 浮窗坐标用「分屏工作区本地坐标」，与分屏矩形同一套参照。
 * user:“悬浮窗：可拖动、可缩放的小窗，不打断当前布局”+
 * (不用 position:fixed：外壳上只要有一层 transform/backdrop-filter，fixed 的包含块就变了，
 *  框会和网页错位。工作区自己就是定位过的矩形，用本地坐标反而只有一套参照。
 *  拿不到工作区时退回视口尺寸，绝不返回 0)。
 */
function workspaceBox(): DOMRect | null {
  if (typeof document === 'undefined') return null
  return host.value?.closest('.split-workspace')?.getBoundingClientRect() ?? null
}
function floaterViewport() {
  const box = workspaceBox()
  if (box) return { width: Math.round(box.width), height: Math.round(box.height) }
  if (typeof window === 'undefined') return { width: 1280, height: 800 }
  return { width: window.innerWidth, height: window.innerHeight }
}
/** 输入框上沿（工作区本地坐标）：浮窗可以挪，但不许压住正在打字的地方。拿不到就返回 0（=不设限）。 */
function floatBottomLimit(): number {
  if (typeof document === 'undefined') return 0
  const box = workspaceBox()
  const composer = document.querySelector('.floating-composer')?.getBoundingClientRect()
  if (!box || !composer) return 0
  return Math.round(composer.top - box.top)
}
function currentFloatFrame(): SurfaceFrame {
  return fitFloatFrame(props.tab.surfaceFrame ?? defaultFloatFrame(floaterViewport()), floaterViewport(), floatBottomLimit())
}
// user:“诊断（仅 dev）”+(打包版不显示诊断入口：它验证的是「网页拿不到 Tauri 接口」这类开发期事实)。
const devBuild = Boolean(import.meta.env?.DEV)
const findOpen = ref(false), findQuery = ref(''), findMatches = ref(0), findIndex = ref(-1), findField = ref<HTMLInputElement | null>(null)

// user:“临时会话不可用时置灰而不是点了才报错”+(能力查询失败也不阻塞浏览，默认当作可用)。
const temporaryAvailable = ref(true)
const permissionRequest = ref<{ host: string; kind: string; requestId?: string; message: string } | null>(null)
// user:“证书错误要能继续访问，但必须显式确认”+(默认阻断，host 来自错误事件)。
const certificateHost = ref('')
const notice = ref('')
// user:“下载列表由 Rust 自维护，只做开始/完成/失败三态”+(没有字节进度，也不做暂停/继续)。
const downloads = ref<BrowserDownloadRecord[]>([])
const downloadsOpen = ref(false)
const approvePending = ref('')
const downloadSummaryLabel = computed(() => downloadSummary(downloads.value))

async function loadDownloads() {
  try {
    const list = await services.call(props.tab.id, 'downloads', {}) as BrowserDownloadRecord[] | undefined
    if (Array.isArray(list)) downloads.value = list
  } catch { /* 列表拿不到不影响继续浏览 */ }
}
function toggleDownloads() {
  moreMenuOpen.value = false
  downloadsOpen.value = !downloadsOpen.value
  if (downloadsOpen.value) void loadDownloads()
}
async function openDownload(record: BrowserDownloadRecord) {
  // user:“危险后缀要审批才能打开”+(第一次点击只给确认文案，第二次才真的打开)。
  if (record.needsApproval && approvePending.value !== record.id) {
    approvePending.value = record.id
    notice.value = downloadApprovalText(record)
    return
  }
  try {
    await services.call(props.tab.id, 'download', { id: record.id, action: 'open', approve: record.needsApproval })
    approvePending.value = ''
  } catch (e) { error.value = errorText(e) }
}
async function revealDownload(record: BrowserDownloadRecord) {
  try { await services.call(props.tab.id, 'download', { id: record.id, action: 'reveal' }) }
  catch (e) { error.value = errorText(e) }
}
const currentProfile = computed<BrowserProfileKind>(() => (props.tab.profile === 'incognito' ? 'incognito' : 'normal'))
const profileBadgeLabel = computed(() => profileBadge(props.tab.profile))

async function loadProfiles() {
  if (!services.available()) return
  try {
    const reply = await services.call(props.tab.id, 'profiles') as { temporarySessionAvailable?: boolean } | undefined
    temporaryAvailable.value = reply?.temporarySessionAvailable !== false
  } catch { /* 会话能力查询失败时保留默认入口，不阻塞页面 */ }
}
// user:“页眉上要留的就是前进、返回、刷新、地址栏和一个『更多』”+
// (「更多」是页眉里唯一的菜单；打开时顺便问一次会话能力——看不见的标签不会为此多发原生调用)。
function toggleMoreMenu() {
  moreMenuOpen.value = !moreMenuOpen.value
  if (moreMenuOpen.value) void loadProfiles()
  // user:“在 toggleMoreMenu 里判断「调用后下一帧 moreMenuOpen 仍为 false」→ 立刻打一条 [hit-test]”+
  // (这条抓的是“handler 跑了但菜单没留下”的另一半失败：例如别处的关闭逻辑把状态又收了回去)。
  if (devHit && moreMenuOpen.value) {
    void nextTick(() => { if (!moreMenuOpen.value) devHit.reportNow('more-menu-not-open') })
  }
}
// 菜单项一律转到原来那个动作函数：先收起菜单，再执行，不复制任何一份逻辑。
function runMenuItem(action: () => void | Promise<void>) {
  moreMenuOpen.value = false
  void action()
}
function newTabWithProfile(kind: BrowserProfileKind) {
  if (!props.controller || !props.pane) return
  moreMenuOpen.value = false
  if (kind === 'incognito' && !temporaryAvailable.value) { notice.value = '临时会话在本版本不可用'; return }
  const created = props.controller.add('browser', '', kind === 'incognito' ? '临时标签' : '浏览器', props.pane)
  // 会话形态跟着标签走：新建后写回布局模型，重启恢复时按它决定是否重建。
  const tab = created ? props.controller.state.panes[props.pane]?.tabs.find(item => item.id === created?.id) : undefined
  if (tab && kind === 'incognito') tab.profile = kind
}
async function decidePermission(decision: 'allow' | 'deny', scope: 'once' | 'site') {
  const request = permissionRequest.value
  if (!request?.requestId) return
  try {
    await services.call(props.tab.id, 'permission', { requestId: request.requestId, decision, scope })
    notice.value = permissionResultText(request, decision, scope)
  } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) } finally { permissionRequest.value = null }
}
async function clearSiteData() {
  moreMenuOpen.value = false
  const host = siteDataHost(address.value)
  if (!host) { error.value = '这个地址没有可清理的站点'; return }
  try { await services.call(props.tab.id, 'clearSiteData', { host, kinds: siteDataKindsArg() }) }
  catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
}
async function runDiagnostics() {
  moreMenuOpen.value = false
  try { await services.call(props.tab.id, 'diagnostics') } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
}
// user:“清除放行记忆”+(WebView2 的 ALWAYS_ALLOW 在本次会话内记住该主机，不声称会自动过期)。
const certificateHostReady = computed(() => Boolean(siteDataHost(address.value)))
async function forgetCertificateMemory() {
  moreMenuOpen.value = false
  const host = siteDataHost(address.value)
  if (!host) { error.value = '当前地址没有可清除的证书记忆'; return }
  try {
    await services.call(props.tab.id, 'certificate', { host, action: 'forget' })
    notice.value = `已清除证书放行记忆（${host}）；之后同样的证书错误会重新阻断`
  } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
}
async function continueCertificate() {
  if (!certificateHost.value) return
  try {
    await services.call(props.tab.id, 'certificate', { host: certificateHost.value, action: 'continue' })
    certificateHost.value = ''; error.value = ''
  } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
}
let resizeObserver: ResizeObserver | undefined, classObserver: MutationObserver | undefined, childObserver: MutationObserver | undefined, unlisten: UnlistenFn | undefined, disposed = false, creating = false
let eventListenerFailed = false
let listenerReady: Promise<void> = Promise.resolve()
let eventRevision = 0
let closing = false
// user:“确保视觉、功能和交互不退化”+(关闭期间完成的导航不能重复关闭或改写已退出的标签)。
async function closeOnce() { if (closing) return; closing = true; created.value = false; await services.call(props.tab.id, 'close') }
let syncing = false, needsSync = false, lastBounds = ''
// user:“两个网页重叠”+(记录上一次真的送达 Rust 的可见性：隐藏这一帧必须能绕过矩形去重，
//  否则“同一份矩形 + visible=false”会被当成没变化吞掉，过期网页就留在合成层上了)。
let lastSentVisible: boolean | null = null
// user:“分屏拖动手感不佳，卡顿/不跟手”+
// (重排手势期间网页已经让位：整段拖动只下发一次 hidden，松手再发最终矩形。
//  旧行为是每帧一次 IPC + 一次 DComp Commit，拖得越快、主线程越忙)。
let reflowYielded = false
// user:“输入地址之后回车无反应”+(创建/导航给一个明确期限，超时也要有话说，不能一直“正在打开”)。
const CREATE_DEADLINE_MS = 15000
// user:“回车之后网页不出现”+(native 侧只允许「活动标签」占据可见区域；一旦被 tab_inactive 拒掉，
//  这里先激活再重下一次，避免用户看到的是一张永远建不出来的空白) —— 每次失败只自救一次，不空转)。
let activationTried = false
let syncFrame = 0
function queueSync() { if (!syncFrame) syncFrame = requestAnimationFrame(() => { syncFrame = 0; void sync() }) }
// user:“浏览器地址栏里显示出 [object Object]”+(主机名只从字符串里取：拿到的不是字符串就当没有，
// 否则 `new URL(对象)` 失败后会把对象原样返回，模板一渲染又变成 `[object Object]`)。
function hostname(raw: unknown) { const text = addressText(raw); if (!text) return ''; try { return new URL(text).hostname } catch { return text } }

// user:“网页不能盖住菜单、浮层”+(可见性判定只有一个纯函数来源，这里只负责把现场状态喂进去)。
// user:“输入地址后网页区域无效/空白”+(宿主矩形只在这一处取：算可见性、算“有没有地方画网页”、
//  事后解释原因都读同一份，避免两个地方对同一块屏得出不同结论)。
// 宿主所属的内容区（分屏内容层 / 主槽位内容层）：这两者都已经扣掉了标签栏与页眉。
const invariantThrottle = createLogThrottle(1000)
function hostContentRect(): SplitRect | null {
  const element = host.value?.closest<HTMLElement>('.split-tab-content, .split-main-slot-content')
  if (!element) return null
  const rect = element.getBoundingClientRect()
  return { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
}
// user:“矩形唯一来源：引擎算出的 contentRect”+(V2-C1b：区域通过 WORKSPACE_AREA_RECT
// 提供 `(surfaceId) => { contentRect, hostRect }`；组件不再 getBoundingClientRect 求宿主。
// 没有区域注入时（展厅/旧外壳）才退回旧测量路径，保证组件单独挂载也能工作。)
const areaRectsQuery = inject(WORKSPACE_AREA_RECT, null)
const rectDiagnostics = createRectDiagnostics(1000)
function areaRects() { return areaRectsQuery?.(props.tab.id) ?? null }
watch(
  () => {
    const r = areaRects()?.contentRect
    return r ? `${r.x},${r.y},${r.width},${r.height}` : ''
  },
  () => {
    if (visibilityPhase() === 'floating') void sync()
    else queueSync()
  },
)

/**
 * 交互相位 → 可见性相位：浮窗手势是 floating（**不让位**，否则拖动时网页原地不动）。
 * user:“分屏拖动手感不佳，卡顿/不跟手”+(控制器拖分隔条的相位是 `resizingDivider`，
 *  旧映射只认 `resizing`，网页因此没让位、每帧追 IPC；现在统一走 layoutPhaseOfController)。
 */
function visibilityPhase(): BrowserLayoutPhase {
  if (surfaceGesture.value !== 'none') return 'floating'
  const phase = props.controller?.interactionPhase?.value
  if (phase && phase !== 'idle') return layoutPhaseOfController(phase)
  return ['split-is-dragging', 'split-is-resizing', 'split-is-pulling'].some(name => document.body.classList.contains(name)) ? 'resizingDivider' : 'idle'
}
function hostRect() {
  const fromArea = areaRects()
  const measured = host.value?.getBoundingClientRect()
  // user:“还有，上传给浏览器的尺寸，应该为实际窗口大小（原生体验）”+
  // (当宿主 DOM 已完成真实排版且落在工作区宿主盒内时，直接上传真实 .split-browser-host 尺寸，
  // 从而自动扣掉浮层边框、紧凑标签栏、页内查找条与下载条；未挂载或离屏时回退到引擎 contentRect)。
  if (fromArea) {
    const hb = fromArea.hostRect
    if (
      measured
      && measured.width > 0
      && measured.height > 0
      && measured.x >= hb.x - 2
      && measured.y >= hb.y - 2
      && measured.x + measured.width <= hb.x + hb.width + 2
      && measured.y + measured.height <= hb.y + hb.height + 2
    ) {
      return measured as SplitRect
    }
    return fromArea.contentRect as SplitRect
  }
  if (!measured) return null
  const content = hostContentRect()
  const fitted = fitRectToContent(measured, content)
  // user:“修完在 dev 里用日志证明：webview 矩形 ⊆ pane 内容区”+
  // (只在真的收过一次时打一条：正常路径应该永远不触发；触发就说明上游把 rect 算大了，日志直接给出是哪一边越了多少)。
  if (fitted?.clamped) {
    // user:“不变量日志别只在 dev 打一次…按 trace/按 pane 节流”+
    // (同一 pane 一秒最多一条，`count` 是这一秒里被折掉的次数；布局抖动时不再刷屏)。
    const pane = `${props.tab.id}:${surface.value}`
    const verdict = invariantThrottle(pane)
    if (verdict.log && import.meta.env?.DEV) {
      console.warn('[browser-bounds-invariant]', {
        pane,
        count: verdict.count,
        host: measured,
        content,
        fitted: fitted.rect,
        overflow: content ? rectOverflow(content, measured) : null,
        dpr: typeof window === 'undefined' ? 1 : window.devicePixelRatio,
      })
    }
  }
  return fitted ? fitted.rect : measured
}
// user:“两个网页重叠”+(同一块分屏里的所有标签是一个组：切换标签时 Rust 按组把其它网页收起；
// 浮窗、已收起的浮窗各算一组，互不牵连)。
const groupId = computed(() => {
  const paneId = props.pane ?? ''
  return paneId && paneId !== 'float' && paneId !== 'parked'
    ? `area:${paneId}`
    : `surface:${props.tab.id}`
})
function options() {
  // user:“矩形唯一来源 + 越界不变量 + 单一可见性判定”+(V2-C1b：contentRect 来自引擎；
  // 越界用 clampToHost 求交并报 overflow；visible 只由 browserVisible 决定
  // ——浮层计数来自单一登记口，浮窗拖动（floating）不让位。)
  const contentRect = hostRect()
  const fromArea = areaRects()
  const hostBox = (fromArea?.hostRect as SplitRect | undefined) ?? hostContentRect() ?? contentRect
  const clamped = contentRect && hostBox ? clampToHost(contentRect, hostBox) : null
  if (clamped?.overflow && contentRect && hostBox) {
    rectDiagnostics({
      pane: `${props.tab.id}:${surface.value}`,
      rect: contentRect,
      host: hostBox,
      dpr: typeof window === 'undefined' ? 1 : window.devicePixelRatio,
    })
  }
  const rect = (clamped?.rect ?? contentRect) as SplitRect | null
  const overlayCount = isComposed.value ? 0 : (overlayDepth() + (contextMenuState.open ? 1 : 0))
  // user:“首页显示期间必须保证该标签没有可见 webview / 置底先让开 / 有浮层压在宿主机上”+
  // (DirectComposition 模式下菜单不隐藏网页；但浮层或分隔条拖拽期间隐藏实时网页并展示模糊冻结帧，松手立刻恢复)。
  const areaVisible = props.visible && !floatBehind.value && !homeVisible.value && !dragYield.value && (isComposed.value || !hostBlockedByOverlay(host.value))
  const visible = rect ? browserVisible({ rect, areaVisible, overlayCount, phase: isComposed.value ? 'idle' : visibilityPhase() }) : false
  const dpr = typeof window === 'undefined' ? 1 : (window.devicePixelRatio || 1)
  // user:“下发改用 webviewBoundsArgs”+(CSS px × dpr 只在这一处乘；physical=true 告诉命令层别再造二次换算)。
  const args = webviewBoundsArgs({ surfaceId: props.tab.id, contentRect: rect ?? { x: 0, y: 0, width: 0, height: 0 }, visible }, dpr)
  return { ...args, surfaceId: props.tab.id, physical: true, isFloat: isFloatSurface.value, stackIndex: stackIndex.value, group: groupId.value }
}
const frozenPreview = ref<string | null>(null)
let captureSeq = 0
async function captureFrozenFrame() {
  if (disposed || !created.value || homeVisible.value || !services.available()) return
  const seq = ++captureSeq
  try {
    const res = (await services.call(props.tab.id, 'screenshot', { target: 'viewport' })) as { png?: string } | undefined
    if (!disposed && seq === captureSeq && res?.png) {
      frozenPreview.value = res.png
    }
  } catch { /* ignore capture failure */ }
}

async function sync() {
  // user:“恢复布局时先不创建原生网页”+(同步矩形只对已创建的标签生效，后台标签不因此提前加载)。
  if (disposed || !created.value || !services.available()) return
  const phase = visibilityPhase()
  const reflowing = phase === 'draggingTab' || phase === 'resizingDivider' || phase === 'movingArea'
  if (reflowing) {
    if (reflowYielded) return
    reflowYielded = true
  } else if (reflowYielded) {
    reflowYielded = false
    // 松手第一帧必须真的下发：拖动可能把矩形改回原值，lastBounds 不重置就会把 visible=true 当成没变。
    lastBounds = ''
  }
  const isFloating = phase === 'floating'
  // user:“2。遮挡的问题用冻结加模糊”+(浮层拖动时跳过 syncing 串行阻塞，直接覆盖下发最新坐标以压低延迟)
  if (syncing && !isFloating) { needsSync = true; return }
  const next = options(), serialized = serializeBounds(next)
  const forceHide = !next.visible && lastSentVisible !== false
  composedVisible.value = isComposed.value && next.visible
  if (registerComposedRect) {
    const dpr = window.devicePixelRatio || 1
    registerComposedRect(props.tab.id, composedVisible.value
      ? { x: next.x / dpr, y: next.y / dpr, width: next.width / dpr, height: next.height / dpr }
      : null)
  }
  if (!forceHide && serialized === lastBounds) return
  // user:“网页跑到分屏外面”+(一次性诊断：宿主矩形 / 视口尺寸 / devicePixelRatio / 实际下发值
  // 打在同一行、带同一个 trace，和 Rust 侧 [bounds-diag] 对齐比较。只在 dev 构建输出。)
  const trace = `b${(syncSeq += 1).toString(36)}-${Date.now().toString(36)}`
  if (import.meta.env.DEV) {
    const raw = host.value?.getBoundingClientRect()
    console.info('[bounds-send]', JSON.stringify({
      trace,
      host: raw ? { x: raw.x, y: raw.y, width: raw.width, height: raw.height } : null,
      inner: [window.innerWidth, window.innerHeight],
      dpr: window.devicePixelRatio,
      send: next,
    }))
  }
  syncing = true
  // user:“网页区域形状与命令参数解耦”+(显式展开成普通对象，避免结构化类型在命令边界上被拒)。
  try {
    await services.call(props.tab.id, 'bounds', { ...next, trace })
    lastBounds = serialized
    lastSentVisible = next.visible
    activationTried = false
  } catch (e) {
    if (disposed) return
    if (recoverLostNativeTab(e)) return
    // user:“回车之后网页不出现”+(后台标签的下发会被拒：先把它激活，再重算一次矩形)。
    if (next.visible && errorCode(e) === 'tab_inactive' && !activationTried) {
      activationTried = true
      try { await services.call(props.tab.id, 'activate'); needsSync = true; return }
      catch (cause) { if (!recoverLostNativeTab(cause)) { error.value = errorText(cause); retriable.value = false } return }
    }
    error.value = errorText(e); retriable.value = false
  }
  finally { syncing = false; if (needsSync) { needsSync = false; void sync() } }
}
function applyEvent(payload: BrowserNativeEvent) {
  if (disposed || payload.id !== props.tab.id) return
  // user:“地址栏下方出现 [object Object] 文本”+(事件里的 message 也可能被塞成对象：
  //  入口处就折成一句话，界面永远拿不到对象)。
  if (payload.error) { if (recoverLostNativeTab(payload.error)) return; error.value = errorText(payload.error); retriable.value = payload.error.retriable === true; certificateHost.value = payload.error.code === 'certificate_error' ? addressText(payload.error.host) : ''; return }
  if (payload.openTab) { openPendingTab(payload.openTab.url); return }
  // user:“Ctrl+F 在网页聚焦时也能唤起查找”+(Rust 拦下快捷键后用 action:"open" 通知这里打开查找条)。
  if (payload.find) { findMatches.value = payload.find.matches; findIndex.value = payload.find.index; if (payload.find.action === 'open') void openFind(); return }
  if (payload.permission) {
    // user:“地址栏下方出现 [object Object] 文本”+(授权提示的 message 同样只存字符串)。
    const request = { ...payload.permission, message: errorText(payload.permission.message, '') }
    permissionRequest.value = request.requestId ? request : null
    if (payload.permission.decision === 'allow') notice.value = request.message
    return
  }
  if (payload.siteData) { notice.value = errorText(payload.siteData.message, ''); return }
  if (payload.diagnostics) { notice.value = errorText(payload.diagnostics.message, ''); return }
  // user:“开始/完成/失败三态”+(同一条记录按 id 覆盖，列表里不会出现两份)。
  if (payload.download) {
    const record = payload.download.record
    const index = downloads.value.findIndex(item => item.id === record.id)
    if (index >= 0) { downloads.value.splice(index, 1, record) } else { downloads.value.unshift(record) }
    notice.value = `${record.filename} · ${downloadStateLabel(record.state)}`
    if (record.state === 'finished' && downloadsOpen.value === false) downloadsOpen.value = true
    return
  }
  eventRevision++
  if (payload.owner !== undefined) owner.value = payload.owner
  // 归人之后没人推动状态：46 秒后问一次，让宿主的「静默即交还」有机会生效。
  if (payload.owner === 'human') scheduleOwnerPoll()
  if (payload.loading !== undefined) loading.value = payload.loading
  if (payload.canGoBack !== undefined) canBack.value = payload.canGoBack
  if (payload.canGoForward !== undefined) canForward.value = payload.canGoForward
  // user:“独立页面缩放…并与 pane 比例分开记忆”+(缩放写回标签自己：比例在分屏树的 ratio 里，两者互不覆盖)。
  if (payload.zoom !== undefined) zoom.value = payload.zoom
  // user:“浏览器地址栏里显示出 [object Object]”+(状态事件的 url/title 只收字符串：
  //  非字符串当作没给，地址栏保留上一次有效地址，标签记录也不被写脏；用户正在输入时不改输入框)。
  const nextTitle = addressText(payload.title)
  const nextUrl = addressText(payload.url)
  if (nextTitle) title.value = nextTitle
  if (nextUrl && !editingAddress.value) address.value = nextUrl
  updateTab({
    ...(nextUrl ? { resource: nextUrl } : {}),
    ...(nextTitle || nextUrl ? { title: nextTitle || hostname(nextUrl) } : {}),
    ...(payload.zoom !== undefined ? { zoom: normalizeZoom(payload.zoom) } : {}),
  })
}
// user:“target=_blank 打开的是新标签而不是丢失”+(Rust 拦下弹窗，前端在同一个分屏里开一个新标签)。
function openPendingTab(url: string) {
  if (!props.controller || !props.pane) return
  props.controller.add('browser', url, hostname(url), props.pane)
}
async function navigate() {
  // user:“输入地址之后回车无反应”+(被上一次还没回来的创建挡住时，至少说一句原因：
  //  静默 return 正是“回车没反应”的来源之一)。
  if (creating) { notice.value = t('上一个网页还在打开，稍等一下再试'); return }
  let target = ''
  try {
    target = resolveAddress(address.value, getStoredSearchEngine()).url
  } catch (e) {
    error.value = e instanceof BrowserAddressError ? e.message : '请输入网址或搜索内容'
    retriable.value = false
    return
  }
  try {
    error.value = ''; retriable.value = false; loading.value = true
    // user:“手动键入要能写回标签”+(地址栏是这条标签唯一的输入口：解析成功后立刻把地址写回
    //  props.tab.resource，并且退出「正在输入」状态；即使原生网页创建失败，用户输入的地址也不会丢)。
    editingAddress.value = false; address.value = target; updateTab({ resource: target })
    if (!services.available()) throw Error('内置浏览器需要在桌面应用中使用；也可以在默认浏览器中打开')
    // user:“确保视觉、功能和交互不退化”+(等事件监听就绪后再创建网页，关闭期间不再创建)。
    creating = true
    await listenerReady
    if (disposed) return
    if (eventListenerFailed) throw Error('浏览器事件监听不可用，请关闭后重新打开分屏')
    const before = eventRevision
    // 记下这一次是不是“刚建出来”：缩放只在网页新生的那一次补发，普通导航不该每次多打一发 IPC。
    const firstLoad = !created.value
    // user:“输入地址之后回车无反应”+(原生命令可能迟迟不回：给一个明确期限，
    //  到点就把可读原因写在地址栏下方，而不是让界面一直停在“正在打开”)。
    await Promise.race([
      services.call(props.tab.id, firstLoad ? 'create' : 'navigate', { ...options(), url: target, profile: currentProfile.value }),
      new Promise((_, reject) => setTimeout(() => reject(Error(t('打开网页超时（15 秒没有回应）'))), CREATE_DEADLINE_MS)),
    ])
    if (disposed) { await closeOnce(); return }
    created.value = true
    // user:“失败回到首页并提示原因”+(网页真的建起来了，上一次的失败标记就该收掉，否则切回来还会闪一张首页)。
    homeFailed.value = false
    // user:“确保视觉、功能和交互不退化”+(原生浏览器先报告重定向时，不用旧请求地址覆盖它)。
    if (eventRevision === before) { address.value = target; updateTab({ resource: target, title: hostname(target) }) }
    // user:“页面缩放…与 pane 比例分开记忆”+(记住的缩放要在网页重建后重新下发一次：
    //  新建的原生网页从 100% 起步，不补这一步，重启后工具栏读数与实际页面就对不上，等于没记住)。
    const storedZoom = normalizeZoom(props.tab.zoom ?? 1)
    if (firstLoad && storedZoom !== 1 && !disposed) {
      try { await services.call(props.tab.id, 'zoom', { action: 'set', value: storedZoom }); zoom.value = storedZoom } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
    }
    // 创建时已经带过一次 bounds；这里再排一次帧，覆盖创建期间的布局变化。
    void queueSync()
  } catch (e) {
    // user:“输入地址之后回车无反应”+(原生侧已经开着这个标签（超时后迟到成功、或热重载后状态失配）时，
    //  把它当作“已经有了”：补上本地状态再同步矩形，不让用户再按一次回车才见效)。
    if (errorCode(e) === 'tab_exists') {
      created.value = true; homeFailed.value = false; error.value = ''; loading.value = false
      void queueSync()
      return
    }
    if (created.value && recoverLostNativeTab(e)) { loading.value = false; return }
    error.value = errorText(e); loading.value = false
    // user:“失败回到首页并提示原因，不要白屏”+(只有“还没建出网页”的失败才退回首页；
    //  已经有网页的标签照旧停在该页，错误条留在工具栏下方)。
    if (!created.value) homeFailed.value = true
  } finally { creating = false }
}
/**
 * user:“输入解析沿用与地址栏同一套规则：像网址就直接打开，否则走搜索（不要另写一套判断）”+
 * (首页不解析任何东西：把原话写进地址栏那个字段，再走同一个 navigate。
 *  于是 resolveAddress 只有一份调用点，两处输入永远同一套判断，也不会出现“首页能开、地址栏不能开”)。
 */
async function submitFromHome(text: string) {
  address.value = text
  editingAddress.value = false
  await navigate()
}
/** user:“Ctrl+L 聚焦地址栏”+(从中央输入栏一键跳到顶部地址栏；内容全选，直接就能改)。 */
function focusAddressBar() { void nextTick(() => { addressField.value?.focus(); addressField.value?.select() }) }
async function action(action: string) { try { await services.call(props.tab.id, action) } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) } }
async function stop() { try { await services.call(props.tab.id, 'stop'); loading.value = false } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) } }
// user:“审查分屏代码，并优化”+(地址不合法时留在原地提示，而不是在点击处理里抛出无人接收的异常)。
async function openExternal() {
  try { if (address.value.trim()) await services.openExternal(resolveAddress(address.value, getStoredSearchEngine()).url) }
  catch (e) { error.value = errorText(e) }
}
// user:“能开多个标签”+(新标签由前端布局模型创建；空地址的标签不预建原生 webview)。
function newTab() { newTabWithProfile('normal') }
// user:“Ctrl+Shift+T 能把关掉的标签找回来”+(关闭栈在 Rust，重建仍走布局模型)。
async function reopenClosed() {
  if (!props.controller || !props.pane) return
  try {
    const closed = await services.call(props.tab.id, 'reopen') as { url?: string; title?: string } | undefined
    if (closed?.url) props.controller.add('browser', closed.url, closed.title || hostname(closed.url), props.pane)
  } catch (e) { error.value = errorText(e) }
}
async function findStep(action: 'start' | 'next' | 'prev') {
  if (!created.value) return
  try { await services.call(props.tab.id, 'find', { action, query: findQuery.value }) } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
}
async function openFind() {
  findOpen.value = true
  await nextTick()
  findField.value?.focus(); findField.value?.select()
  if (findQuery.value) void findStep('start')
}
async function closeFind() {
  findOpen.value = false; findMatches.value = 0; findIndex.value = -1
  if (!created.value) return
  try { await services.call(props.tab.id, 'find', { action: 'stop' }) } catch { /* 停止查找失败不影响界面 */ }
}
async function zoomStep(action: 'in' | 'out' | 'reset') {
  if (!created.value) return
  try { await services.call(props.tab.id, 'zoom', { action }) } catch (e) { if (!recoverLostNativeTab(e)) error.value = errorText(e) }
}
const findLabel = computed(() => {
  if (!findQuery.value) return ''
  return findMatches.value ? `${findIndex.value + 1}/${findMatches.value}` : '无结果'
})
/**
 * user:“模式切换：工具栏一个模式按钮（分屏/全屏/悬浮）+ 快捷键；切模式不重新加载页面（保持同一 webview 实例，只改 bounds/可见性）”+
 * (只写标签上的 surface，别的一律不动：webview 不重建，页面滚动位置与表单内容天然保住。
 *  独立预览里的浮窗也保持页面实例)。
 */
function setSurface(next: Exclude<SurfaceMode, 'focus'>) {
  moreMenuOpen.value = false
  // 不支持的形态一律不切：按钮已置灰，这里再兜一层，避免菜单以外的路径（快捷键、右键）切出一个摆不出来的屏。
  if (!addressText(props.tab.resource) && next !== 'split') return
  if (next !== 'split' && !surfaceSupport.value.float) return
  if (next === surface.value) return
  if (next === 'float' && !props.tab.surfaceFrame) props.tab.surfaceFrame = defaultFloatFrame(floaterViewport())
  if (props.controller && next === 'float') {
    // 互斥规则只写一份：surfaceModes.exclusiveSurfaceOwners 说谁该被复位，这里只负责复位。
    const all = props.controller.tabs.value
    const reset = new Set(exclusiveSurfaceOwners(all.map(({ tab }) => ({ id: tab.id, surface: tab.surface })), props.tab.id))
    for (const { tab } of all) if (reset.has(tab.id)) { tab.surface = 'split'; tab.surfaceExpanded = false }
  }
  props.tab.surface = next
  props.tab.surfaceExpanded = false
  floatBehind.value = false
  // 切成悬浮时同时激活当前标签。
  if (props.pane) props.controller?.activate(props.pane, props.tab.id)
  void nextTick(() => { void ensureBrowser(); queueSync() })
}
function exitSurface() { if (surface.value !== 'split') setSurface('split') }
/**
 * 浮窗拖动 / 右下角缩放：手势中先隐藏网页、显示占位块，松手才提交 bounds。
 * user:“可拖动、可缩放、不抢焦点”+(只在浮窗自己身上起手势，不碰分屏的拖拽状态机)。
 */
let stopSurfaceGesture: (() => void) | undefined
function beginSurfaceGesture(event: PointerEvent, kind: 'move' | 'resize') {
  if (event.button !== 0 || surface.value !== 'float') return
  event.preventDefault(); event.stopPropagation()
  stopSurfaceGesture?.()
  const start = { x: event.clientX, y: event.clientY }
  const origin = currentFloatFrame()
  const viewport = floaterViewport()
  const limit = floatBottomLimit()
  surfaceGesture.value = kind
  const move = (e: PointerEvent) => {
    const delta = { dx: e.clientX - start.x, dy: e.clientY - start.y }
    const next = kind === 'move' ? moveFloatFrame(origin, delta, viewport) : resizeFloatFrame(origin, delta, viewport)
    // 指针走到哪窗就到哪：高度按输入框上沿收，绝不允许盖住正在打字的地方。
    props.tab.surfaceFrame = fitFloatFrame(next, viewport, limit)
    // user:“拖动/缩放期间按帧节流下发 bounds（rAF 合并、同帧最多一次、矩形没变不发），让网页跟着容器走”+
    // (queueSync 已经是单帧合并；sync() 里面还有一道 serializeBounds 去重，所以同一帧的多次 move 只发一条，
    //  指针没动时一条都不发)。
    queueSync()
  }
  const stop = () => {
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
    window.removeEventListener('keydown', cancelKey)
    stopSurfaceGesture = undefined
    surfaceGesture.value = 'none'
    // 松手后才提交 bounds：这一帧让位，下一帧网页按新矩形出现。
    void nextTick(queueSync)
  }
  const cancelKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); stop() } }
  stopSurfaceGesture = stop
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stop)
  window.addEventListener('pointercancel', stop)
  window.addEventListener('keydown', cancelKey)
}
// user:“置底 = 网页先让开、框还留着”+(点一下收起网页，再点一下回来；框不会消失，所以不会“找不到了”)。
function toggleFloatBehind() { floatBehind.value = !floatBehind.value; void nextTick(queueSync) }
// user:“悬浮窗要有明确的关闭/置底/收回分屏的出口，不能进去出不来”+
// (关闭才是真的关掉这个标签；没有控制器时（展厅）退回分屏，绝不把用户困在一个关不掉的框里)。
function closeFloat() {
  if (props.controller && props.pane) props.controller.closeTab(props.pane, props.tab)
  else setSurface('split')
}
// user:“Esc 退出”+(焦点在网页宿主这一层时也要能退：window 上的监听会被网页吃掉，所以再挂一道本地的)。
function onSurfaceEscape(event: KeyboardEvent) {
  if (surface.value === 'split') return
  event.preventDefault(); event.stopPropagation(); exitSurface()
}
// user:“常用快捷键”+(只在 Sunday 界面有焦点时生效；网页获得焦点后按键进入网页，这是 M1 的已知限制)。
// user:“聚焦是一个无意义功能，移除”+(移除聚焦全屏快捷键，保留网页查找与地址栏快捷键)。
function onKeydown(event: KeyboardEvent) {
  if (!props.visible) return
  if (event.key === 'Escape' && surface.value !== 'split') { event.preventDefault(); event.stopPropagation(); exitSurface(); return }
  if (!event.ctrlKey) return
  const key = event.key.toLowerCase()
  // user:“Ctrl+L 聚焦地址栏”+(这套键盘表只在 Sunday 界面有焦点时生效；网页拿到键盘后按键进网页，这是已知限制)。
  if (key === 'l' && !event.shiftKey && !event.altKey) { event.preventDefault(); focusAddressBar(); return }
  // user:“补一个…悬浮窗的置底快捷”+(置底只在浮窗成立：别的形态里按它没有意义，所以先看形态再动手)。
  if (key === 'd' && event.shiftKey && surface.value === 'float') { event.preventDefault(); toggleFloatBehind(); return }
  // 独立预览没有宿主快捷键，由组件切换分屏与浮层。
  if (key === 'm' && event.shiftKey && !props.controller) { event.preventDefault(); setSurface(surface.value === 'float' ? 'split' : 'float'); return }
  if (key === 'f' && !event.shiftKey) { event.preventDefault(); void openFind() }
  else if (key === '=' || key === '+') { event.preventDefault(); void zoomStep('in') }
  else if (key === '-') { event.preventDefault(); void zoomStep('out') }
  else if (key === '0') { event.preventDefault(); void zoomStep('reset') }
  else if (key === 't' && event.shiftKey) { event.preventDefault(); void reopenClosed() }
}
// user:“恢复布局时先不创建原生网页，等标签真正可见再加载”+(后台标签各开一个子 WebView 既慢又占内存)。
// user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
// (这句只说明前端记着的原生标签已经不在了——应用重载、宿主关掉了它、或映射失效。
//  以前它既不清映射也不重建，还被当成错误条；而错误条会挡掉所有鼠标事件，
//  结果就是网页永远点不动。现在统一自愈：丢映射 → 清错误 → 按当前地址重建一次；
//  同一标签 2 秒内只重建一次，避免原生连续失败时空转)。
let recoveringLostTab = false, lastLostRebuildAt = 0
function recoverLostNativeTab(cause: unknown): boolean {
  if (!nativeTabLost(cause)) return false
  if (disposed) return true
  const now = Date.now()
  if (recoveringLostTab || !canRebuildLostTab(now, lastLostRebuildAt)) return true
  recoveringLostTab = true
  lastLostRebuildAt = now
  forgetBrowserTab(props.tab.id)
  created.value = false
  error.value = ''
  retriable.value = false
  certificateHost.value = ''
  lastBounds = ''
  activationTried = false
  void nextTick(() => {
    recoveringLostTab = false
    if (disposed) return
    if (props.visible) void ensureBrowser()
    else queueSync()
  })
  return true
}
async function ensureBrowser() {
  if (!props.visible || disposed || creating || !addressText(props.tab.resource) || !services.available()) return
  if (created.value) { await action('activate'); lastBounds = ''; void sync(); return }
  await navigate()
}
watch(() => props.visible, visible => { if (visible) { void nextTick(ensureBrowser) } void nextTick(sync) })
// user:“自动聚焦（进入首页即聚焦，切回该标签也聚焦）”+(只在“这块屏真的可见”时抢焦点：后台标签不偷焦点)。
// 首页自己用 nextTick 再聚焦，所以这里在标签刚出现、组件还没挂好时调用也不会丢。
watch([homeVisible, () => props.visible], ([home, visible]) => { if (home && visible) homeRef.value?.focus() })
watch(overlayYield, async (yielded) => {
  if (yielded) {
    await captureFrozenFrame()
    void sync()
  } else {
    captureSeq += 1
    frozenPreview.value = null
    lastBounds = ''
    void sync()
  }
})
watch([stackIndex, () => contextMenuState.open], sync)
// user:“菜单打开立刻 hide，关闭后一帧再 show”+
// (页眉「更多」是浏览器自己的下拉：它自己登记一层，网页在菜单活着期间一律让位，
//  否则菜单被原生层盖住，就表现为「点了没反应」。恢复走 queueSync，天然晚一帧)。
let moreOverlayRelease: (() => void) | null = null
function onMoreOutsidePointerDown(event: PointerEvent) {
  if (!moreMenuOpen.value) return
  const target = event.target as HTMLElement | null
  if (target?.closest('.split-browser-menu')) return
  moreMenuOpen.value = false
}
watch(moreMenuOpen, open => {
  if (open) {
    moreOverlayRelease?.(); moreOverlayRelease = openOverlay('browser-more-menu')
    window.addEventListener('pointerdown', onMoreOutsidePointerDown, true)
  } else {
    window.removeEventListener('pointerdown', onMoreOutsidePointerDown, true)
    closeOverlay(moreOverlayRelease); moreOverlayRelease = null
  }
  void sync()
})
watch(() => props.controller?.floats?.value?.length ?? 0, count => {
  if (count > 0 && !isFloatSurface.value) moreMenuOpen.value = false
})
onBeforeUnmount(() => {
  window.removeEventListener('pointerdown', onMoreOutsidePointerDown, true)
  closeOverlay(moreOverlayRelease); moreOverlayRelease = null
})
// user:“自动触发点（都加 200ms 去抖）：挂载后 1 秒；分屏开/合、主内容切换、聚焦全屏/浮窗切换之后；
// 窗口 resize 结束；以及用户点「更多」但菜单没有打开时”+
// (dev 跑起来不需要用户操作就能看到四条探针；之后只在命中结果变化时补一条，带自增 seq 方便对时间线)。
// user:“保留 Ctrl+Alt+Shift+H 手动态”+(用户想主动取证时还按那一下)。
const devHit = autoHitTestEnabled() ? createAutoHitTest({ debounceMs: 200, mountDelayMs: 1000 }) : null
const stopHitTest = devHit ? installHitTestShortcut() : null
const stopStealProbe = devHit
  ? installStealProbe({
      selector: '[data-browser-more]',
      // user:“点「更多」但菜单没有打开时…立刻打一条 [hit-test]，把 owner 与 path 抓下来”+
      // (点击被吃掉时组件内的 handler 根本不会执行，所以这一层只能在捕获阶段比对坐标)。
      onSteal: info => console.warn('[hit-test]', { seq: -1, reason: 'more-click-stolen', ...info }),
    })
  : null
const workspaceState = props.controller?.state
if (devHit) {
  watch(
    () => [
      workspaceState?.mainTab?.id ?? '',
      Object.keys(workspaceState?.panes ?? {}).sort().join(','),
      surface.value,
    ],
    () => devHit.nudge('layout'),
  )
}
onBeforeUnmount(() => { devHit?.stop(); stopHitTest?.(); stopStealProbe?.() })
onMounted(async () => {
  if (typeof ResizeObserver !== 'undefined') { resizeObserver = new ResizeObserver(queueSync); resizeObserver.observe(host.value!) }
  // user:“审查分屏代码，并优化”+(只观察会影响网页宿主的两类变化：body 自身的拖动/缩放类名，以及模态框、右栏或菜单的插入删除)。
  if (typeof MutationObserver !== 'undefined') {
    classObserver = new MutationObserver(queueSync); classObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] })
    childObserver = new MutationObserver(records => { if (records.some(record => [...record.addedNodes, ...record.removedNodes].some(obscuresHostNode))) queueSync() })
    childObserver.observe(document.body, { childList: true, subtree: true })
  }
  window.addEventListener('resize', queueSync)
  window.addEventListener('keydown', onKeydown)
  if (services.available()) {
    // user:“确保视觉、功能和交互不退化”+(监听失败时明确提示，避免无状态的浏览器或未处理异常)。
    listenerReady = services.subscribe(applyEvent)
      .then(stop => { if (disposed) stop(); else unlisten = stop })
      .catch(cause => { eventListenerFailed = true; if (!disposed) error.value = errorText(cause) })
    await listenerReady
    if (disposed || eventListenerFailed) return
  }
  await ensureBrowser()
  // user:“进入首页即聚焦”+(挂载完成的这一刻首页可能已经在画了：watch 在挂载前拿不到组件引用，这里补一次)。
  if (homeVisible.value && props.visible) homeRef.value?.focus()
  void sync()
})
onBeforeUnmount(() => { disposed = true; cancelAnimationFrame(syncFrame); cancelAnimationFrame(moveFrame); cancelAnimationFrame(wheelFrame); resizeObserver?.disconnect(); classObserver?.disconnect(); childObserver?.disconnect(); unlisten?.(); window.removeEventListener('resize', queueSync); window.removeEventListener('keydown', onKeydown); if (created.value) void closeOnce().catch(() => {}) })
let moveFrame = 0
let pendingMove: PointerEvent | null = null
let wheelFrame = 0
let pendingWheelEvent: WheelEvent | null = null
let pendingWheelDelta = 0
function routeMouseInput(kind: number, event: MouseEvent, wheelDelta = 0) {
  // user:“内置浏览器出现：这个浏览器标签已经关闭 导致无法点击操作网页”+
  // (错误条只是说明，不是输入开关：网页在不在由 created 决定。以前这里多判了 errorLabel，
  //  任何一次失败都会把点击/滚轮永久挡在门外；真丢了标签时由 recoverLostNativeTab 重建)。
  if (!isComposed.value || !created.value || !props.visible || homeVisible.value) return
  const r = host.value?.getBoundingClientRect()
  if (!r || r.width <= 0 || r.height <= 0) return
  const dpr = typeof window === 'undefined' ? 1 : (window.devicePixelRatio || 1)
  const x = Math.round((event.clientX - r.left) * dpr)
  const y = Math.round((event.clientY - r.top) * dpr)
  let vk = 0
  if (event.buttons & 1) vk |= 0x0001
  if (event.buttons & 2) vk |= 0x0002
  if (event.shiftKey) vk |= 0x0004
  if (event.ctrlKey) vk |= 0x0008
  if (event.buttons & 4) vk |= 0x0010
  void services.call(props.tab.id, 'input', { kind, virtualKeys: vk, wheelDelta, x, y }).catch(cause => { recoverLostNativeTab(cause) })
}
function onHostPointerMove(event: PointerEvent) {
  pendingMove = event
  if (moveFrame) return
  moveFrame = requestAnimationFrame(() => {
    moveFrame = 0
    const next = pendingMove
    pendingMove = null
    if (next) routeMouseInput(0x0200, next)
  })
}
function onHostPointerDown(event: PointerEvent) {
  const kind = event.button === 2 ? 0x0204 : event.button === 1 ? 0x0207 : 0x0201
  routeMouseInput(kind, event)
}
function onHostPointerUp(event: PointerEvent) {
  const kind = event.button === 2 ? 0x0205 : event.button === 1 ? 0x0208 : 0x0202
  routeMouseInput(kind, event)
}
function onHostWheel(event: WheelEvent) {
  if (!isComposed.value || !created.value || !props.visible || homeVisible.value) return
  event.preventDefault()
  pendingWheelDelta += Math.round(-event.deltaY)
  pendingWheelEvent = event
  if (wheelFrame) return
  wheelFrame = requestAnimationFrame(() => {
    wheelFrame = 0
    const ev = pendingWheelEvent
    const delta = Math.max(-32768, Math.min(32767, pendingWheelDelta)) & 0xFFFF
    pendingWheelEvent = null
    pendingWheelDelta = 0
    if (ev) routeMouseInput(0x020A, ev, delta)
  })
}
</script>
<template>
  <!-- user:“悬浮窗：可拖动、可缩放的小窗…原生 webview 没有圆角与阴影，所以浮窗外观要用 DOM 边框 + 内缩”+
       (外框是这个 div 的边框/圆角/阴影；网页矩形靠内边距收进来，于是网页四边都落在边框以内)。
       悬浮时连工具条一起收成一条窄把手：小窗里再摆一排地址栏按钮，既挤占了网页又不像“瞥一眼”。 -->
  <div class="split-browser" :class="{ 'split-browser--float': surface === 'float' }" @keydown.esc="onSurfaceEscape">
    <div v-if="surface === 'float'" class="split-browser-float-bar" :title="title || address || t('悬浮窗')" @pointerdown.prevent="beginSurfaceGesture($event, 'move')">
      <span class="split-browser-float-grip" aria-hidden="true"></span>
      <span class="split-browser-float-title">{{ title || hostname(address) || t('悬浮窗') }}</span>
      <button class="split-icon-button" type="button" :title="floatBehind ? t('把网页提回前面') : t('把网页置底') + ' (Ctrl+Shift+D)'" :aria-label="floatBehind ? t('把网页提回前面') : t('把网页置底')" @pointerdown.stop @click.stop="toggleFloatBehind">{{ floatBehind ? ChevronUp : ChevronDown }}</button>
      <button class="split-icon-button" type="button" :title="t('放回分屏')" :aria-label="t('放回分屏')" @pointerdown.stop @click.stop="setSurface('split')"><PictureInPicture2 :size="13" /></button>
      <!-- user:“悬浮窗要有明确的关闭/置底/收回分屏的出口，不能进去出不来”+
           (置底=临时让开、放回分屏=回到网格、关闭=真的关掉这个标签；三条出口一字排开，谁也不必猜)。 -->
      <button class="split-icon-button" type="button" :title="t('关闭这个悬浮窗')" :aria-label="t('关闭这个悬浮窗')" @pointerdown.stop @click.stop="closeFloat"><X :size="13" /></button>
    </div>
    <!-- user:“这个上面的页眉是干什么的？…页眉上要留的就是前进、返回、刷新、地址栏和一个『更多』”+
         (页眉只留五个槽位：返回、前进、刷新（加载中变停止）、地址栏、更多；
          页内查找/缩放/站点/标签/形态/下载/诊断全部收进「更多」的分组菜单，每项都调原来那个动作函数，
          快捷键照旧；标签页仍是独立的一行，不并进来)。 -->
    <form v-if="surface !== 'float'" class="split-content-toolbar split-browser-header" data-browser-header @submit.prevent="navigate">
      <button class="split-icon-button" data-browser-slot="back" type="button" :title="t('后退')" :aria-label="t('后退')" :disabled="!created || !canBack" @click="action('back')"><ArrowLeft :size="14" /></button>
      <button class="split-icon-button" data-browser-slot="forward" type="button" :title="t('前进')" :aria-label="t('前进')" :disabled="!created || !canForward" @click="action('forward')"><ArrowRight :size="14" /></button>
      <button v-if="loading" class="split-icon-button" data-browser-slot="reload" type="button" :title="t('停止加载')" :aria-label="t('停止加载')" :disabled="!created" @click="stop"><Square :size="12" /></button>
      <button v-else class="split-icon-button" data-browser-slot="reload" type="button" :title="t('刷新')" :aria-label="t('刷新')" :disabled="!created" @click="action('reload')"><RotateCw :size="14" /></button>
      <!-- user:“地址栏保持整行弹性宽度，其余全部图标化、无文字”+(输入框吃掉所有剩余宽度，五个槽位之外不再放任何东西)。 -->
      <input ref="addressField" v-model="address" data-browser-slot="address" type="text" :aria-label="t('网页地址')" :placeholder="t('搜索或输入网址')" spellcheck="false" @focus="focusAddress" @blur="blurAddress" />
      <!-- user:“我怎么把页面交给agent？有UI吗？”+(归人时给一个明确的交回入口；不占地址栏宽度，窄了自动折进图标)。 -->
      <button v-if="owner === 'human'" class="split-text-button split-browser-handback" data-browser-handback type="button" :title="t('交回给 Agent：它才能继续在这个页面点击/输入')" @click="handBackToAgent">{{ t('交回给 Agent') }}</button>
      <div class="split-browser-menu" data-browser-slot="more">
        <button class="split-icon-button split-browser-more" type="button" data-browser-more :title="profileBadgeLabel ? t('更多 · 当前会话 {0}', { 0: profileBadgeLabel }) : t('更多')" :aria-label="t('更多')" aria-haspopup="menu" :aria-expanded="moreMenuOpen" @click.stop="toggleMoreMenu">
          <MoreHorizontal :size="14" aria-hidden="true" />
          <ChevronDown class="split-browser-more-chevron" :size="10" aria-hidden="true" />
          <span v-if="profileBadgeLabel" class="split-browser-badge" data-browser-more-badge>{{ profileBadgeLabel }}</span>
        </button>
        <!-- user:“页眉的更多卡片精简，只保留必要项，窗口形态什么的删除，保留缩放、下载、查找、转到默认浏览器，其余均去除”+
             (精简为 4 项必要能力：缩放步进条、页内查找、下载列表、用默认浏览器打开)。 -->
        <div v-if="moreMenuOpen" class="split-browser-menu-list split-browser-more-list" role="menu" data-browser-more-menu>
          <div class="split-browser-more-section">
            <div class="split-browser-more-stepper" role="group" :aria-label="t('页面缩放')">
              <button class="split-browser-more-step" data-browser-more-item="zoom-out" type="button" role="menuitem" :disabled="!created" :title="created ? 'Ctrl+-' : t('还没有网页')" @click="void zoomStep('out')">−</button>
              <button class="split-browser-more-step split-browser-more-step--value" data-browser-more-item="zoom-reset" type="button" role="menuitem" :disabled="!created" :title="t('点击还原 100% · Ctrl+0')" @click="runMenuItem(() => zoomStep('reset'))">{{ zoomLabel }}</button>
              <button class="split-browser-more-step" data-browser-more-item="zoom-in" type="button" role="menuitem" :disabled="!created" :title="created ? 'Ctrl++' : t('还没有网页')" @click="void zoomStep('in')">+</button>
            </div>
            <button class="split-browser-menu-item split-browser-menu-item--row" data-browser-more-item="find" type="button" role="menuitem" :disabled="!created" :title="created ? '' : t('还没有网页')" @click="runMenuItem(openFind)"><span>{{ t('页内查找') }}</span><small>{{ created ? 'Ctrl+F' : t('还没有网页') }}</small></button>
            <button class="split-browser-menu-item split-browser-menu-item--row" data-browser-more-item="downloads" type="button" role="menuitem" @click="runMenuItem(toggleDownloads)"><span>{{ downloadsOpen ? t('收起下载列表') : t('下载列表') }}</span><small>{{ downloadSummaryLabel }}</small></button>
            <button class="split-browser-menu-item split-browser-menu-item--row" data-browser-more-item="external" type="button" role="menuitem" @click="runMenuItem(openExternal)"><span>{{ t('用默认浏览器打开') }}</span><small>{{ t('系统浏览器') }}</small></button>
          </div>
        </div>
      </div>
    </form>
    <div v-if="permissionRequest" class="split-browser-permission" role="alertdialog" aria-live="polite">
      <span class="split-browser-permission-text">{{ permissionPromptTitle(permissionRequest) }}</span>
      <button class="split-text-button" type="button" @click="decidePermission('allow', 'once')">仅本次允许</button>
      <button class="split-text-button" type="button" @click="decidePermission('allow', 'site')">该站点始终允许</button>
      <button class="split-text-button" type="button" @click="decidePermission('deny', 'once')">拒绝</button>
    </div>
    <p v-if="noticeLabel" class="split-browser-notice" role="status">{{ noticeLabel }}</p>
    <div v-if="downloadsOpen" class="split-browser-downloads" role="region" aria-label="下载列表">
      <p v-if="!downloads.length" class="split-browser-downloads-empty">还没有下载（只记录开始 / 完成 / 失败，不做进度）</p>
      <div v-for="record in downloads" :key="record.id" class="split-browser-download-row">
        <span class="split-browser-download-name" :title="record.path || record.url">{{ record.filename }}</span>
        <span class="split-browser-download-state">{{ downloadStateLabel(record.state) }}</span>
        <button v-if="record.state === 'finished'" class="split-text-button" type="button" @click="openDownload(record)">{{ approvePending === record.id ? '确认打开' : '打开' }}</button>
        <button v-if="record.state === 'finished'" class="split-text-button" type="button" @click="revealDownload(record)">定位</button>
      </div>
    </div>
    <div v-if="findOpen" class="split-browser-find">
      <input ref="findField" v-model="findQuery" type="text" aria-label="页内查找内容" placeholder="在页面中查找" spellcheck="false" @input="findStep('start')" @keydown.enter.exact.prevent="findStep('next')" @keydown.shift.enter.exact.prevent="findStep('prev')" @keydown.esc.prevent="closeFind" />
      <span class="split-browser-find-count" aria-live="polite">{{ findLabel }}</span>
      <button class="split-icon-button" type="button" title="上一个" aria-label="上一个" @click="findStep('prev')"><ChevronUp :size="14" /></button>
      <button class="split-icon-button" type="button" title="下一个" aria-label="下一个" @click="findStep('next')"><ChevronDown :size="14" /></button>
      <button class="split-icon-button" type="button" title="关闭查找" aria-label="关闭查找" @click="closeFind"><X :size="12" /></button>
    </div>
    <p v-if="errorLabel" class="split-content-error" role="alert">{{ errorLabel }}<button v-if="retriable" class="split-text-button" type="button" @click="navigate">重试</button><button v-if="certificateHost" class="split-text-button" type="button" @click="continueCertificate">继续访问（不推荐）</button></p>
    <!-- user:“当浏览器标签没有地址时，在 pane 内渲染一张首页而不是空白”+
         (首页显示期间这个标签**没有**原生 webview：要么还没创建，要么上次建失败退回来了，
          所以这里画的 DOM 一定不会被原生网页盖住；进站后首页自己消失，网页照旧由 Rust 建出来)。 -->
    <div
      ref="host"
      class="split-browser-host"
      :class="{ 'is-composed-live': composedVisible && created && visible && !homeVisible && !overlayYield }"
      @pointermove="onHostPointerMove"
      @pointerdown="onHostPointerDown"
      @pointerup="onHostPointerUp"
      @wheel="onHostWheel"
      @contextmenu.prevent
    >
      <!-- user:“点完更多之后，整个浏览器消失了，只剩那个菜单了”+
           (网页让位是有意的：原生 webview 永远在 DOM 之上，菜单要能看见就必须让它先退。
            但空出来的宿主区不能是一片“加载失败”的空白 —— 铺一层与主题一致的底色 + 一行很轻的说明，
            菜单一关就撤掉，网页下一帧照旧回来)。 -->
      <div v-if="overlayYield" class="split-browser-yield" data-browser-yield role="status">
        <img v-if="frozenPreview" class="split-browser-frozen" :src="frozenPreview" alt="" aria-hidden="true" />
        <span v-if="title || hostname(address)" class="split-browser-yield-title">{{ title || hostname(address) }}</span>
        <small>{{ visibilityPhase() === 'draggingTab' ? t('拖拽标签时网页暂时让位') : dragYield ? t('拖动时网页暂时冻结') : t('菜单打开时网页暂时让位') }}</small>
      </div>
      <BrowserHomeView v-if="homeVisible" ref="homeRef" :controller="controller" :pane="pane" :busy="loading" @submit="submitFromHome">
        <!-- 自定义组件扩展位：卡片类组件（参考图里的 Explore / 天气 / 便签）由外层挂进来，首页自己不做假卡片。 -->
        <template #cards><slot name="home-cards" /></template>
      </BrowserHomeView>
      <div v-else-if="!created" class="split-empty"><Globe :size="26" :stroke-width="1.2" /><span>在这里打开网页，继续手边的工作</span></div>
    </div>
    <!-- user:“悬浮窗：可拖动、可缩放的小窗…原生 webview 没有圆角与阴影，所以浮窗外观要用 DOM 边框 + 内缩”+
         (缩放角必须落在网页矩形之外：原生网页永远画在 DOM 之上，落在网页里的把手会被它整个盖掉、点都点不到)。 -->
    <span v-if="surface === 'float'" class="split-browser-resize" title="拖动调整大小" aria-label="拖动调整大小" @pointerdown.prevent="beginSurfaceGesture($event, 'resize')"></span>
  </div>
</template>
<style scoped>
/* user:“悬浮窗：可拖动、可缩放的小窗…原生 webview 没有圆角与阴影，所以浮窗外观要用 DOM 边框 + 内缩”+
   (外框 = 这一层的边框/圆角/阴影；网页矩形由内边距收进来，于是四边都落在边框以内。
    内边距用 --split-surface-inset 一个变量，缩放角与拖动把手都据此排在网页外面)。 */
.split-browser--float {
  --split-surface-inset: 8px;
  box-sizing: border-box;
  gap: 0;
  padding: var(--split-surface-inset);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 18%, transparent);
  border-radius: var(--radius-lg, 12px);
  background: var(--theme-main-background);
  box-shadow: 0 18px 48px color-mix(in srgb, #000 30%, transparent);
  overflow: hidden;
}
/* user:“在网页区域显示一层与主题一致的占位背景 + 一行很轻的提示”+(全令牌，不加新颜色)。 */
.split-browser-host { position: relative; }
.split-browser-host.is-composed-live { background: transparent !important; }
.split-browser-yield { position: absolute; inset: 0; display: grid; align-content: center; justify-items: center; gap: var(--space-1); padding: var(--space-4); text-align: center; background: var(--theme-main-background); color: color-mix(in srgb, var(--theme-main-text) 58%, transparent); font-size: 12px; pointer-events: none; overflow: hidden; }
.split-browser-frozen { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; filter: blur(8px) brightness(0.82); transform: scale(1.03); pointer-events: none; }
.split-browser-yield-title, .split-browser-yield small { position: relative; z-index: 1; }
.split-browser-yield-title { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: color-mix(in srgb, var(--theme-main-text) 78%, transparent); font-size: 13px; }
.split-browser-yield small { font-size: 11px; opacity: .72; }
.split-browser--float .split-browser-host { border-radius: calc(var(--radius-lg, 12px) - var(--split-surface-inset)); }
/* user:“可拖动”+(整条把手就是拖拽面；它排在网页上方，所以不会被原生网页盖住而拖不动)。 */
.split-browser-float-bar { display: flex; flex: 0 0 auto; align-items: center; gap: var(--space-1); box-sizing: border-box; height: 26px; margin-bottom: var(--split-surface-inset); padding: 0 var(--space-1) 0 0; border-radius: calc(var(--radius-lg, 12px) - var(--split-surface-inset)); background: color-mix(in srgb, var(--theme-main-text) 8%, transparent); cursor: grab; touch-action: none; }
.split-browser-float-bar:active { cursor: grabbing; }
.split-browser-float-grip { flex: 0 0 auto; width: 3px; height: 12px; margin-left: var(--space-2); border-radius: 2px; background: color-mix(in srgb, var(--theme-main-text) 30%, transparent); }
.split-browser-float-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; color: color-mix(in srgb, var(--theme-main-text) 72%, transparent); }
/* 跟手之后不再需要“松手放下”的占位层：网页跟着矩形走，拖动中看到的就是最终位置。 */
/* 缩放角排在内边距里（网页之外），所以原生网页盖不住它。 */
.split-browser-resize { position: absolute; right: 0; bottom: 0; width: var(--split-surface-inset, 8px); height: var(--split-surface-inset, 8px); cursor: nwse-resize; touch-action: none; }
.split-browser-resize::after { content: ''; position: absolute; right: 2px; bottom: 2px; width: 4px; height: 4px; border-right: 1px solid color-mix(in srgb, var(--theme-main-text) 45%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 45%, transparent); }
/* user:“按参考图核对布局：地址栏输入框圆角、右侧保留现有图标、间距对齐参考图”+
   (只改浏览器这条地址栏的形状：顶部工具条本身的高度与图标顺序不动，别的工具栏输入框也不受影响)。 */
.split-browser .split-content-toolbar input[type="text"] { border-radius: 999px; padding-inline: var(--space-3); }
/* 交回给 Agent：只在归人时出现；地址栏仍是弹性宽度，这个按钮不抢地址栏的最小可读宽度。 */
.split-browser-handback { flex: 0 0 auto; white-space: nowrap; max-width: 40%; overflow: hidden; text-overflow: ellipsis; }
/* user:“窄窗口：优先保「地址栏 + 更多」，返回/前进/刷新在极窄时可折进更多（给个阈值，用容器宽度算）”+
   (阈值按这一条页眉自己的可用宽度算，不看窗口：分屏、浮窗、窄栏里同一份规则都成立。
    折起来的三个按钮仍在「更多」里能点到，所以任何宽度下都不丢路)。
    高度、图标尺寸全部沿用现有工具条与 --icon/--space 令牌，不新增硬编码颜色。 */
.split-browser-header { container: browser-header / inline-size; }
.split-browser-more { position: relative; gap: 0; }
.split-browser-more-chevron { margin-left: 1px; opacity: .7; }
.split-browser-more .split-browser-badge { position: absolute; right: -2px; bottom: -2px; }
/* user:“确认菜单本身不盖住工具栏：菜单应相对「更多」按钮定位、向下展开，不能 inset:0 铺满面板”+
   (定位来自 .split-browser-menu-list 的 top:100%; right:0；这里只把它限制在窄分屏里也放得下的大小)。 */
/* user:“在浏览器状态下页眉的更多点后卡片会被遮挡，依旧是层级问题”+
   (.split-browser-header 启用 container-type 会创建独立层叠上下文，必须提高其 z-index 压在 .split-browser-host 和占位层之上) */
.split-browser-header { position: relative; z-index: 10; }
.split-browser-more-list { z-index: var(--z-popover, 600); width: min(300px, calc(100vw - var(--space-5))); max-height: min(60vh, 420px); overflow-y: auto; gap: var(--space-2); padding: var(--space-2); border-radius: var(--radius); box-shadow: var(--shadow-md); }
.split-browser-more-section { display: flex; flex-direction: column; gap: 3px; }
.split-browser-more-section + .split-browser-more-section { border-top: 1px solid color-mix(in srgb, var(--theme-composer-text) 8%, transparent); padding-top: var(--space-1); }
.split-browser-more-group { margin: 0 var(--space-1) 2px; color: color-mix(in srgb, var(--theme-composer-text) 55%, transparent); font-size: 10px; font-weight: 600; letter-spacing: .02em; }
.split-browser-more-stepper { display: grid; grid-template-columns: 36px 1fr 36px; gap: 2px; padding: 2px; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-composer-text) var(--alpha-hover, 8%), transparent); }
.split-browser-more-step { height: 24px; border: 0; border-radius: var(--radius-sm); background: transparent; color: inherit; font: inherit; font-size: 12px; cursor: pointer; }
.split-browser-more-step--value { font-variant-numeric: tabular-nums; font-weight: 500; }
.split-browser-more-step:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-composer-text) var(--alpha-active, 12%), transparent); }
.split-browser-more-step:disabled { opacity: .45; cursor: default; }
.split-browser-more-pills { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-1); }
.split-browser-more-pill { display: inline-flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px; min-height: 26px; padding: 2px var(--space-1); border: 0; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-composer-text) var(--alpha-hover, 8%), transparent); color: inherit; font: inherit; font-size: 11px; cursor: pointer; }
.split-browser-more-pill:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-composer-text) var(--alpha-active, 12%), transparent); }
.split-browser-more-pill.is-current { background: color-mix(in srgb, var(--theme-composer-text) var(--alpha-active, 12%), transparent); font-weight: 600; }
.split-browser-more-pill:disabled:not(.is-current) { opacity: .45; cursor: default; }
.split-browser-more-pill small { font-size: 9px; opacity: .65; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.split-browser-menu-item--row { flex-direction: row; align-items: center; justify-content: space-between; gap: var(--space-2); }
.split-browser-menu-current { margin-left: var(--space-1); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-composer-text) 12%, transparent); padding: 0 4px; font-style: normal; font-size: 9px; }
@container browser-header (max-width: 300px) {
  .split-browser-header [data-browser-slot="back"],
  .split-browser-header [data-browser-slot="forward"],
  .split-browser-header [data-browser-slot="reload"] { display: none; }
}
/* user:“独立页面缩放…与 pane 比例分开记忆”+(读数是个可点的按钮：点一下回 100%，比“再按两次减号”清楚)。 */
.split-browser-zoom { flex: 0 0 auto; min-width: 40px; height: 24px; padding: 0 var(--space-1); border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-main-text) 62%, transparent); font: inherit; font-size: 11px; font-variant-numeric: tabular-nums; cursor: pointer; }
.split-browser-zoom:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); color: var(--theme-main-text); }
.split-browser-zoom:disabled { opacity: .45; cursor: default; }
/* user:“下载列表沿用工具栏材质”+(三态只用文字，不加进度条：我们并不做字节进度)。 */
.split-browser-downloads { flex: 0 0 auto; max-height: 132px; overflow-y: auto; padding: var(--space-1) var(--space-2); border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent); font-size: 12px; }
.split-browser-downloads-empty { margin: 0; font-size: 11px; opacity: .6; }
.split-browser-download-row { display: flex; align-items: center; gap: var(--space-2); padding: 2px 0; }
.split-browser-download-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.split-browser-download-state { flex: 0 0 auto; font-size: 11px; opacity: .7; }
/* user:“会话形态与站点操作要看得见”+(角标、下拉与权限条沿用现有工具栏材质与间距，不引入新颜色)。 */
.split-browser-badge { flex: 0 0 auto; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-main-text) 12%, transparent); color: var(--theme-main-text); padding: 0 var(--space-1); font-size: 10px; line-height: 16px; opacity: .8; }
.split-browser-menu { position: relative; flex: 0 0 auto; }
.split-browser-menu-list { position: absolute; top: 100%; right: 0; z-index: 30; display: flex; flex-direction: column; min-width: 190px; gap: 2px; padding: var(--space-1); border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent); border-radius: var(--radius-sm); background: var(--theme-composer-background); color: var(--theme-composer-text); box-shadow: 0 8px 24px color-mix(in srgb, #000 24%, transparent); }
.split-browser-menu-item { display: flex; flex-direction: column; gap: 1px; border: 0; border-radius: var(--radius-sm); background: transparent; color: inherit; padding: var(--space-1) var(--space-2); text-align: left; font: inherit; font-size: 12px; cursor: pointer; }
.split-browser-menu-item:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-main-text) 10%, transparent); }
.split-browser-menu-item:disabled { opacity: .45; cursor: default; }
.split-browser-menu-item small { font-size: 10px; opacity: .6; }
.split-browser-permission { display: flex; flex: 0 0 auto; align-items: center; gap: var(--space-2); padding: var(--space-1) var(--space-2); border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent); font-size: 12px; }
.split-browser-permission-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.split-browser-notice { margin: 0; padding: var(--space-1) var(--space-2); font-size: 11px; opacity: .7; }
/* user:“界面与 Sunday 现有设计语言一致”+(查找条沿用工具栏的材质与间距，不引入新颜色)。 */
.split-browser-find { display: flex; flex: 0 0 auto; align-items: center; gap: var(--space-1); padding: var(--space-1) var(--space-2); border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent); }
.split-browser-find input { flex: 1; min-width: 0; border: 0; border-radius: var(--radius-sm); outline: none; background: var(--theme-composer-background); color: var(--theme-composer-text); padding: var(--space-1) var(--space-2); font: inherit; font-size: 12px; }
.split-browser-find-count { flex: 0 0 auto; min-width: 44px; text-align: right; font-size: 11px; opacity: .6; }
</style>

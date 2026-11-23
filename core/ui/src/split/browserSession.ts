// user:“会话三态：普通 / 临时 / 自定义目录”+(前端只负责显示与选择；真正的隔离由 Rust 在创建 webview 前决定)。
//
// 这里集中放「会话形态 + 权限提示 + 站数据清理目标」的纯函数，方便单测覆盖，
// 规则与 Rust 侧 `browser/session.rs`、`browser/security.rs` 保持同一份口径。
import type { SplitTab } from '@/workspace/types'

/** 普通会话（独立目录、持久）；临时会话（InPrivate、关闭即失效）。 */
export type BrowserProfileKind = 'normal' | 'incognito'

export const DEFAULT_BROWSER_PROFILE: BrowserProfileKind = 'normal'

/** 自定义目录形态在状态里带 `custom:` 前缀（M2 不向普通用户暴露，只作分组与实验入口）。 */
const CUSTOM_PREFIX = 'custom:'

/** 同一个地址的普通标签与临时标签必须共存，所以 profile 要参与「是否同一个标签」的比较。 */
export function browserProfileKey(tab: Pick<SplitTab, 'profile'>): string {
  const raw = tab.profile?.trim()
  return raw ? raw : DEFAULT_BROWSER_PROFILE
}

/** user:“临时标签不恢复”+(incognito 关闭即销毁，重启后凭空出现等于伪造隔离)。 */
export function isTemporaryProfile(profile?: string): boolean {
  return browserProfileKey({ profile }) === 'incognito'
}

/** 恢复策略：普通与自定义目录按 URL 恢复，临时会话不恢复。 */
export function restoresOnRestart(profile?: string): boolean {
  return !isTemporaryProfile(profile)
}

/** 自定义目录恢复时要标注所属目录（没有目录就是 null）。 */
export function profileRestoreNote(profile?: string): string | null {
  const key = browserProfileKey({ profile })
  return key.startsWith(CUSTOM_PREFIX) ? key.slice(CUSTOM_PREFIX.length) : null
}

/** 标签角标文案：普通会话不显示角标，其余都要能一眼看出会话形态。 */
export function profileBadge(profile?: string): string {
  if (isTemporaryProfile(profile)) return '临时'
  const note = profileRestoreNote(profile)
  if (note) {
    const folder = note.split(/[\\/]/).filter(Boolean).pop()
    return folder ? `目录 ${folder}` : '独立目录'
  }
  return ''
}

/** 不可用时把入口置灰并给出原因（不静默降级成共享会话）。 */
export function profileOptions(temporaryAvailable: boolean): Array<{ kind: BrowserProfileKind; label: string; hint: string; available: boolean }> {
  return [
    { kind: 'normal', label: '普通标签', hint: '登录态跨重启保留', available: true },
    {
      kind: 'incognito',
      label: '临时标签',
      hint: temporaryAvailable ? '关闭即丢弃，登录态不保留' : '临时会话在本版本不可用',
      available: temporaryAvailable,
    },
  ]
}

// ---------------------------------------------------------------------------
// 权限提示
// ---------------------------------------------------------------------------

export interface BrowserPermissionRequest {
  host: string
  kind: string
  requestId?: string
  message: string
}

const PERMISSION_LABELS: Record<string, string> = {
  camera: '摄像头',
  microphone: '麦克风',
  geolocation: '位置信息',
  notifications: '通知',
  clipboard_read: '剪贴板内容',
  other_sensors: '传感器',
  autoplay: '自动播放',
  file_read_write: '本地文件读写',
  local_fonts: '本地字体列表',
  multiple_downloads: '批量下载',
  midi_system_exclusive_messages: 'MIDI 设备',
  window_management: '窗口管理',
  unknown: '未知权限',
}

/** 权限类型的中文名；未知类型不显示原始英文键名给用户。 */
export function permissionLabel(kind: string): string {
  return PERMISSION_LABELS[kind] ?? PERMISSION_LABELS.unknown
}

/** 授权条标题：说清谁要什么，默认已经是拒绝。 */
export function permissionPromptTitle(request: BrowserPermissionRequest): string {
  return `${request.host} 想要使用${permissionLabel(request.kind)}`
}

/** 结果提示：拒绝也要可见，不能点了没反应。 */
export function permissionResultText(request: BrowserPermissionRequest, decision: 'allow' | 'deny', scope: 'once' | 'site'): string {
  const name = permissionLabel(request.kind)
  if (decision === 'deny') return `已拒绝 ${request.host} 使用${name}`
  return scope === 'site' ? `已允许 ${request.host} 长期使用${name}` : `已允许 ${request.host} 本次使用${name}`
}

// ---------------------------------------------------------------------------
// 站数据清理
// ---------------------------------------------------------------------------

/** 清理目标 host：地址栏里的绝对 URL → host；解析失败就是空串（前端不下发无效清理）。 */
export function siteDataHost(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase()
  } catch {
    return ''
  }
}

/**
 * user:“站数据清理只清存储，缓存不动”+(默认清 Cookie 与页面存储；缓存类目标不上送，
 * 参数形状与 Rust 侧 `SiteDataKinds::parse` 一致）。
 */
export const SITE_DATA_KINDS = ['cookies', 'storage'] as const

/** 缓存类目标：列出只为断言「清理请求永远不会带上它们」。 */
export const SITE_DATA_CACHE_TARGETS = ['cache', 'disk_cache', 'cache_storage'] as const

/** 实际会被清掉的存储目标（展示与断言共用一份）。 */
export const SITE_DATA_STORAGE_TARGETS = ['cookies', 'local_storage', 'indexed_db', 'service_worker'] as const

export function siteDataKindsArg(): string[] {
  return [...SITE_DATA_KINDS]
}

/** 缓存不会被动，所以文案要如实说明「从缓存打开的旧页面可能还显示已登录」。 */
export function siteDataSummary(host: string): string {
  return `已清除 ${host} 的登录与存储（Cookie、localStorage、IndexedDB、Service Worker）；缓存资源未清理，从缓存直接打开的旧页面可能仍显示已登录内容`
}

// ---------------------------------------------------------------------------
// 下载（M3：只做开始/完成/失败三态，没有字节进度）
// ---------------------------------------------------------------------------

export interface BrowserDownloadRecord {
  id: string
  tab: string
  url: string
  filename: string
  path?: string | null
  state: 'started' | 'finished' | 'failed'
  needsApproval: boolean
  startedAt: string
  finishedAt?: string | null
}

/** 下载状态文案：不出现「暂停/下载中 xx%」这种我们并不支持的表达。 */
export function downloadStateLabel(state: BrowserDownloadRecord['state']): string {
  if (state === 'started') return '下载中'
  if (state === 'finished') return '已完成'
  return '失败'
}

/** 危险后缀的二次确认文案：说明为什么拦，而不是只弹一个「确定吗」。 */
export function downloadApprovalText(record: BrowserDownloadRecord): string {
  return `${record.filename} 是可执行/脚本文件，确认来源可信后再打开`
}

export function downloadSummary(records: BrowserDownloadRecord[]): string {
  const active = records.filter(record => record.state === 'started').length
  const done = records.filter(record => record.state === 'finished').length
  if (!records.length) return '还没有下载'
  return active ? `${active} 个正在下载，${done} 个已完成` : `${done} 个已完成`
}

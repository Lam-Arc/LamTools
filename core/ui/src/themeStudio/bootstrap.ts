import { THEME_STUDIO_DRAFT_STORAGE_KEY, THEME_STUDIO_STORAGE_KEY } from './constants.ts'
import { migrateStudioDocument } from './migrate.ts'
import { validateStudioDocument } from './validate.ts'
import { applyStudioDocument, STUDIO_PREVIEW_STYLE_ID, STUDIO_STYLE_ID } from './runtime.ts'
import { THEME_HISTORY_STORAGE_KEY } from './history.ts'
import type { StudioDocument } from './schema.ts'

/**
 * 启动时恢复已发布主题。
 *
 * user:“而且为什么这个点了发布之后 它的修改不生效啊”+
 * (发布只发生在编辑器里，应用启动时必须把本地存储里的已发布文档
 *  重新应用为正式样式，否则关闭编辑器后修改就“消失”了。
 *  读取、迁移、校验任何一步失败都保持默认外观，绝不写半份样式。)
 */

export interface ApplyStoredThemeOptions {
  /** 默认读 localStorage 的已发布文档；测试可注入其它读取来源。 */
  read?: () => unknown
  /** 样式挂载容器，默认 document.head；测试可注入隔离容器。 */
  container?: HTMLElement
  /** 素材地址解析；默认按文档自带的内嵌 data URL 解析。 */
  assetUrl?: (assetId: string) => string | null
  /** 安全模式开关读取；默认看 URL 与 localStorage 标记。 */
  safeMode?: () => boolean
}

/** 安全模式的本地标记：与主题内容无关，坏主题也读得到。 */
export const THEME_SAFE_MODE_KEY = 'sunday.themeStudio.safeMode'
/** URL 上带这个参数等同于打开安全模式，方便主题坏到进不去设置时救命。 */
export const THEME_SAFE_MODE_PARAM = 'safe-theme'

export interface SafeModeOptions {
  search?: string
  readFlag?: () => boolean
  writeFlag?: (on: boolean) => void
  container?: HTMLElement
}

function readSafeFlag(): boolean {
  try {
    return globalThis.localStorage?.getItem(THEME_SAFE_MODE_KEY) === '1'
  } catch {
    return false
  }
}

function writeSafeFlag(on: boolean): void {
  try {
    if (on) globalThis.localStorage?.setItem(THEME_SAFE_MODE_KEY, '1')
    else globalThis.localStorage?.removeItem(THEME_SAFE_MODE_KEY)
  } catch {
    /* 存不下标记时仍按本次会话处理，不影响恢复动作本身 */
  }
}

/**
 * 是否处于安全模式。
 *
 * user:“提供与自定义主题无关的安全模式入口/启动参数或等价恢复方法”+
 * (主题把界面弄坏时，URL 参数和本地标记两条路都不依赖主题本身。)
 */
export function isSafeThemeMode(options: SafeModeOptions = {}): boolean {
  const search = options.search ?? globalThis.location?.search ?? ''
  const pattern = new RegExp(`(?:^|[?&])${THEME_SAFE_MODE_PARAM}=1(?:&|$)`)
  if (pattern.test(search)) return true
  try {
    return options.readFlag ? options.readFlag() : readSafeFlag()
  } catch {
    return false
  }
}

function removeStudioStyles(container: HTMLElement | undefined): void {
  const root = container ?? globalThis.document?.head
  if (!root) return
  for (const styleId of [STUDIO_STYLE_ID, STUDIO_PREVIEW_STYLE_ID]) {
    root.querySelectorAll(`style[data-ui-theme-studio="${styleId}"]`).forEach((node) => node.remove())
  }
}

/** 进入安全模式：立刻撤掉自定义主题样式，并记住这次选择。 */
export function enterSafeThemeMode(options: SafeModeOptions = {}): void {
  ;(options.writeFlag ?? writeSafeFlag)(true)
  removeStudioStyles(options.container)
}

/** 退出安全模式：下一次启动恢复正常读取已发布主题。 */
export function exitSafeThemeMode(options: SafeModeOptions = {}): void {
  ;(options.writeFlag ?? writeSafeFlag)(false)
}

export interface RecoverOptions {
  container?: HTMLElement
  writeFlag?: (on: boolean) => void
}

/**
 * 一键恢复：清掉已发布主题与草稿，回到内置外观。
 *
 * user:“不可因自定义主题导致设置无法进入”+
 * (只删主题相关的存储键；历史保留，方便用户找回上一版。)
 */
export function recoverThemeStorage(options: RecoverOptions = {}): void {
  try {
    globalThis.localStorage?.removeItem(THEME_STUDIO_STORAGE_KEY)
    globalThis.localStorage?.removeItem(THEME_STUDIO_DRAFT_STORAGE_KEY)
  } catch {
    /* 存储不可用时至少把界面样式撤掉 */
  }
  ;(options.writeFlag ?? writeSafeFlag)(false)
  removeStudioStyles(options.container)
}

/** 清历史只在用户明确要求时发生；恢复默认主题不会顺手删掉回滚线索。 */
export function clearThemeHistoryStorage(): void {
  try {
    globalThis.localStorage?.removeItem(THEME_HISTORY_STORAGE_KEY)
  } catch {
    /* 忽略存储异常 */
  }
}

export function applyStoredPublishedTheme(options: ApplyStoredThemeOptions = {}): boolean {
  if (options.safeMode ? options.safeMode() : isSafeThemeMode()) return false
  let raw: unknown = null
  try {
    raw = options.read ? options.read() : globalThis.localStorage?.getItem(THEME_STUDIO_STORAGE_KEY)
  } catch {
    return false
  }
  if (typeof raw === 'string') {
    try {
      raw = JSON.parse(raw)
    } catch {
      return false
    }
  }
  if (!raw) return false

  const migrated = migrateStudioDocument(raw)
  if (!migrated.ok) return false
  const validation = validateStudioDocument(migrated.document)
  if (!validation.ok) return false

  const document: StudioDocument = migrated.document
  const resolveAsset = options.assetUrl
    ?? ((assetId: string) => document.assets.find((asset) => asset.id === assetId)?.url ?? null)
  const result = applyStudioDocument(document, { container: options.container, assetUrl: resolveAsset })
  return result.ok
}

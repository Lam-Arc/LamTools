import { THEME_STUDIO_STORAGE_KEY } from './constants.ts'
import { migrateStudioDocument } from './migrate.ts'
import { validateStudioDocument } from './validate.ts'
import { applyStudioDocument } from './runtime.ts'
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
}

export function applyStoredPublishedTheme(options: ApplyStoredThemeOptions = {}): boolean {
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

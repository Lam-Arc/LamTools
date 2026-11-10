import type { StudioDocument } from './schema.ts'
import { migrateStudioDocument } from './migrate.ts'
import { validateStudioDocument } from './validate.ts'

/**
 * 发布历史：保留上一版与最近若干版，供回滚。
 *
 * user:“主题保存、发布、回退和迁移”“保留上一版发布主题与版本历史”+
 * (发布只切换当前版本，历史另存一份；历史里的坏数据只丢那一条，
 *  绝不让它影响已发布主题或编辑器启动。)
 */

export const THEME_HISTORY_LIMIT = 5
export const THEME_HISTORY_STORAGE_KEY = 'sunday.themeStudio.history.v1'

export interface ThemeHistoryEntry {
  /** 这一版被替换下来的时间（ISO）。 */
  at: string
  document: StudioDocument
}

export interface ThemeHistoryStorage {
  read: () => unknown
  write: (entries: ThemeHistoryEntry[]) => void
}

/** 默认落在 localStorage；读写异常一律吞掉，历史坏了不影响编辑。 */
export function localStorageHistory(): ThemeHistoryStorage {
  return {
    read: () => {
      try {
        const raw = globalThis.localStorage?.getItem(THEME_HISTORY_STORAGE_KEY)
        return raw ? JSON.parse(raw) : null
      } catch {
        return null
      }
    },
    write: (entries) => {
      try {
        globalThis.localStorage?.setItem(THEME_HISTORY_STORAGE_KEY, JSON.stringify(entries))
      } catch {
        /* 配额不足时历史只活在内存里，不打断发布 */
      }
    },
  }
}

/** 文档是否值得留一版：全是空的默认文档不留。 */
export function isEmptyDocument(document: StudioDocument): boolean {
  return Object.keys(document.nodes || {}).length === 0
    && Object.keys(document.templates || {}).length === 0
    && Object.keys(document.instances || {}).length === 0
    && (document.breakpoints || []).length === 0
    && Object.keys(document.variables || {}).length === 0
    && (document.assets || []).length === 0
}

/** 读历史：逐条迁移与校验，坏的直接丢掉，返回的顺序是最新在前。 */
export function loadHistory(storage?: ThemeHistoryStorage): ThemeHistoryEntry[] {
  const raw = storage?.read()
  if (!Array.isArray(raw)) return []
  const entries: ThemeHistoryEntry[] = []
  for (const item of raw) {
    if (!item || typeof item !== 'object') continue
    const candidate = item as { at?: unknown; document?: unknown }
    if (typeof candidate.at !== 'string' || !candidate.at) continue
    const migrated = migrateStudioDocument(candidate.document)
    if (!migrated.ok) continue
    if (!validateStudioDocument(migrated.document).ok) continue
    // 迁移成空文档的条目没有回滚价值，按坏数据一起丢掉。
    if (isEmptyDocument(migrated.document)) continue
    entries.push({ at: candidate.at, document: migrated.document })
    if (entries.length >= THEME_HISTORY_LIMIT) break
  }
  return entries
}

/** 把一版被替换下来的文档推进历史；同一份不重复记。 */
export function pushHistory(
  storage: ThemeHistoryStorage | undefined,
  previous: StudioDocument,
  at: Date = new Date(),
): ThemeHistoryEntry[] {
  const current = loadHistory(storage)
  if (isEmptyDocument(previous)) return current
  const serialized = JSON.stringify(previous)
  if (current[0] && JSON.stringify(current[0].document) === serialized) return current
  const next = [{ at: at.toISOString(), document: previous }, ...current].slice(0, THEME_HISTORY_LIMIT)
  storage?.write(next)
  return next
}

export function clearHistory(storage?: ThemeHistoryStorage): void {
  storage?.write([])
}

/** 历史条目的一句话摘要：给人看的是「什么时候、改了多少」，不是整份 JSON。 */
export function summarizeHistoryEntry(entry: ThemeHistoryEntry): string {
  const document = entry.document
  const nodes = Object.keys(document.nodes || {}).length
  const templates = Object.keys(document.templates || {}).length
  const instances = Object.keys(document.instances || {}).length
  const breakpoints = (document.breakpoints || []).length
  const variables = Object.keys(document.variables || {}).length
  const assets = (document.assets || []).length
  const parts: string[] = []
  if (nodes) parts.push(`元素 ${nodes}`)
  if (templates) parts.push(`模板 ${templates}`)
  if (instances) parts.push(`实例 ${instances}`)
  if (breakpoints) parts.push(`断点 ${breakpoints}`)
  if (variables) parts.push(`变量 ${variables}`)
  if (assets) parts.push(`素材 ${assets}`)
  return parts.length ? parts.join(' · ') : '空主题'
}

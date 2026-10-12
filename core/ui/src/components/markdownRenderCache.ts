// ── Markdown 渲染缓存（模块级共享 LRU）──
// 按 content 缓存 parse+sanitize 结果与 mermaid 块：折叠/展开、重渲染、回访
// 会话（渲染器实例销毁重建）都免重解析。此前缓存在组件实例上，实例销毁即丢，
// 会话回访全部重来；提升到模块级后跨实例、跨会话存活。
// 内存上限双保险：条目数 ≤ MARKDOWN_CACHE_MAX_ENTRIES，且被缓存内容的源文
// 字符总量 ≤ MARKDOWN_CACHE_MAX_CHARS；超限按最久未用逐出，超长单条不缓存。
// 命中即续期：Map 迭代序就是最近使用序，读一次就重插到最新端。

export const MARKDOWN_CACHE_MAX_ENTRIES = 100
export const MARKDOWN_CACHE_MAX_CHARS = 1_000_000

export interface MarkdownCacheEntry {
  html: string
  blocks: { id: string; code: string }[]
  seq: number
  inlinePlots: { id: string; html: string }[]
  inlinePlotSeq: number
}

const cache = new Map<string, MarkdownCacheEntry>()
let cachedChars = 0

export function getCachedMarkdown(key: string): MarkdownCacheEntry | undefined {
  const entry = cache.get(key)
  if (!entry) return undefined
  cache.delete(key)
  cache.set(key, entry)
  return entry
}

export function setCachedMarkdown(key: string, entry: MarkdownCacheEntry): void {
  // 超长单条不缓存：一条就把预算吃光的缓存只会伤害命中率。
  if (key.length > MARKDOWN_CACHE_MAX_CHARS) return
  const existing = cache.get(key)
  if (existing) {
    cache.delete(key)
    cachedChars -= key.length
  }
  cache.set(key, entry)
  cachedChars += key.length
  while (cache.size > MARKDOWN_CACHE_MAX_ENTRIES || (cachedChars > MARKDOWN_CACHE_MAX_CHARS && cache.size > 1)) {
    const oldestKey = cache.keys().next().value
    if (oldestKey === undefined) break
    cache.delete(oldestKey)
    cachedChars -= oldestKey.length
  }
}

/** 测试观察口：当前缓存条数与源文字符总量。 */
export function markdownCacheStatsForTests(): { entries: number; chars: number } {
  return { entries: cache.size, chars: cachedChars }
}

/** 测试隔离用：清空缓存。 */
export function resetMarkdownCacheForTests(): void {
  cache.clear()
  cachedChars = 0
}

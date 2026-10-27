/**
 * Wiki 导航的纯函数：链接解析、标题锚点、阅读进度。
 *
 * 这些规则同时被 WikiView 的点击处理和测试引用，所以集中在一处：
 * - 文内链接一律相对当前文章解析，只有落到 wiki 内的 .md 才算可跳转；
 * - 标题 id 由标题文字生成（与链接里的 #中文锚点 对齐）；
 * - 阅读进度只由滚动位置决定，不依赖具体 DOM 实现。
 */

export interface WikiArticleMeta {
  slug: string
  title: string
  summary: string
  section: string
  size: number
}

export interface WikiGroup {
  id: string
  title: string
  /** 组内文章 slug，顺序即 README 里的阅读顺序。 */
  articles: string[]
}

export interface WikiNavigation {
  /** README 的 slug；为空表示没有索引页。 */
  index: string
  groups: WikiGroup[]
}

export interface WikiHeading {
  id: string
  text: string
  level: number
}

export interface WikiHeadingEntry extends WikiHeading {
  element: HTMLElement
}

export interface WikiLinkTarget {
  slug: string
  hash: string
}

const URL_SCHEME = /^[a-z][a-z0-9+.-]*:/i
const TOC_NOISE = /^(目录|contents|table of contents)$/i

function decode(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

/**
 * 把握手 `.md` 链接解析成 wiki slug（不含扩展名）。
 * 越出 wiki 根目录、外部地址、非 markdown 文件都返回 null；
 * 只有 `#小节` 的链接返回当前文章 + 锚点。
 */
export function resolveWikiHref(href: string, currentSlug: string): WikiLinkTarget | null {
  const raw = href.trim()
  if (!raw || raw.startsWith('//') || URL_SCHEME.test(raw)) return null
  const hashAt = raw.indexOf('#')
  const hash = hashAt >= 0 ? decode(raw.slice(hashAt + 1)) : ''
  const path = (hashAt >= 0 ? raw.slice(0, hashAt) : raw).split('?', 1)[0].trim()
  if (!path) return currentSlug ? { slug: currentSlug, hash } : null
  if (!/\.md$/i.test(decode(path))) return null

  const parts = path.startsWith('/') ? [] : currentSlug.split('/').slice(0, -1)
  const segments = parts.filter(Boolean)
  for (const segment of decode(path).replace(/^\/+/, '').split('/')) {
    if (!segment || segment === '.') continue
    if (segment === '..') {
      if (!segments.length) return null
      segments.pop()
      continue
    }
    segments.push(segment)
  }
  const file = segments.pop() ?? ''
  const stem = file.replace(/\.md$/i, '')
  if (!stem) return null
  return { slug: [...segments, stem].join('/'), hash }
}

/**
 * 标题文字 → 稳定 id。
 *
 * Wiki 文内锚点是按「去掉标点、保留字词、空白折成连字符」的约定写的
 * （#第一步读规则和现状 对应 ## 第一步：读规则和现状），所以这里连中文标点
 * 一起去掉：ASCII、通用标点、CJK 标点与全角标点都不进 id。
 */
export function wikiHeadingId(text: string): string {
  return text
    .trim()
    .toLowerCase()
    .replace(/[\u2000-\u206F\u2E00-\u2E7F\u3000-\u303F\uFF01-\uFF0F\uFF1A-\uFF20\uFF3B-\uFF40\uFF5B-\uFF65\\'!"#$%&()*+,./:;<=>?@\[\]^`{|}~]/g, '')
    .replace(/\s+/g, '-')
}

/** 滚动位置 → 0–1 的阅读进度；没有可滚动范围时按 0 处理。 */
export function wikiScrollProgress(scrollTop: number, clientHeight: number, scrollHeight: number): number {
  const range = scrollHeight - clientHeight
  if (!Number.isFinite(range) || range <= 0) return 0
  return Math.min(1, Math.max(0, scrollTop / range))
}

/**
 * 给正文里的 h2–h4 补 id（`#中文锚点` 要有落点），并返回目录项。
 * 重复标题按 `-1`、`-2` 递增，和常见 markdown 实现的习惯一致。
 */
export function collectWikiHeadings(root: HTMLElement): WikiHeadingEntry[] {
  const used = new Map<string, number>()
  const entries: WikiHeadingEntry[] = []
  for (const element of Array.from(root.querySelectorAll<HTMLElement>('h2, h3, h4'))) {
    const text = (element.textContent ?? '').replace(/\s+/g, ' ').trim()
    if (!text) continue
    const base = element.id || wikiHeadingId(text)
    if (!base) continue
    const seen = used.get(base) ?? 0
    used.set(base, seen + 1)
    const id = seen ? `${base}-${seen}` : base
    element.id = id
    element.dataset.wikiHeading = id
    entries.push({ id, text, level: Number(element.tagName.slice(1)), element })
  }
  return entries
}

/** 目录里是否该显示这个标题（文章自带的「目录」小节不再重复列一遍）。 */
export function isTocHeading(heading: WikiHeading): boolean {
  return !TOC_NOISE.test(heading.text)
}

/**
 * 后端返回的 navigation 可能缺失（旧版本后端）：按 section 兜底分组，
 * 保证左栏仍然有层级，而不是退回一张平铺列表。
 */
export function normalizeWikiNavigation(raw: unknown, articles: WikiArticleMeta[]): WikiNavigation {
  const value = raw as Partial<WikiNavigation> | null | undefined
  if (value && Array.isArray(value.groups)) {
    const groups: WikiGroup[] = []
    for (const [index, group] of value.groups.entries()) {
      const entry = group as Partial<WikiGroup> | null
      if (!entry || !Array.isArray(entry.articles)) continue
      groups.push({
        id: String(entry.id ?? `group-${index}`),
        title: String(entry.title ?? ''),
        articles: entry.articles.map(String),
      })
    }
    if (groups.length) {
      return { index: typeof value.index === 'string' ? value.index : '', groups }
    }
  }

  const buckets = new Map<string, string[]>()
  for (const article of articles) {
    if (!article.slug || article.slug === 'README') continue
    const key = article.section || ''
    buckets.set(key, [...(buckets.get(key) ?? []), article.slug])
  }
  return {
    index: articles.some(article => article.slug === 'README') ? 'README' : '',
    groups: [...buckets.entries()].map(([section, slugs], index) => ({
      id: `group-${index}`,
      title: section || '文档',
      articles: slugs,
    })),
  }
}

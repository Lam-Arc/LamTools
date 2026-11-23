// user:“地址栏里输入网址、搜索、localhost 都要能用”+(前端负责把输入分类成网址还是搜索词；Rust 侧仍会再校验一遍)。
export interface SearchEngine {
  id?: SearchEngineId
  name: string
  /** 模板里的 `{query}` 会被百分号编码后的关键词替换。 */
  template: string
}

export type SearchEngineId = 'bing' | 'google' | 'baidu'

// user:“左侧的那个图标可以切换引擎，bing，谷歌，百度”+(统一在这里维护三个搜索引擎及持久化读写，首页与地址栏共用)
export const SEARCH_ENGINES: ReadonlyArray<Required<SearchEngine>> = [
  { id: 'bing', name: 'Bing', template: 'https://www.bing.com/search?q={query}' },
  { id: 'google', name: 'Google', template: 'https://www.google.com/search?q={query}' },
  { id: 'baidu', name: '百度', template: 'https://www.baidu.com/s?wd={query}' },
]

export const DEFAULT_SEARCH_ENGINE: Required<SearchEngine> = SEARCH_ENGINES[0]

const SEARCH_ENGINE_STORAGE_KEY = 'sunday.browser.search_engine'

export function getStoredSearchEngine(): Required<SearchEngine> {
  try {
    const raw = typeof localStorage !== 'undefined' ? localStorage.getItem(SEARCH_ENGINE_STORAGE_KEY) : null
    return SEARCH_ENGINES.find(item => item.id === raw) ?? DEFAULT_SEARCH_ENGINE
  } catch {
    return DEFAULT_SEARCH_ENGINE
  }
}

export function setStoredSearchEngine(id: SearchEngineId): Required<SearchEngine> {
  const found = SEARCH_ENGINES.find(item => item.id === id) ?? DEFAULT_SEARCH_ENGINE
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(SEARCH_ENGINE_STORAGE_KEY, found.id)
  } catch { /* ignore storage failure */ }
  return found
}

export class BrowserAddressError extends Error {
  constructor(readonly code: 'invalid_url' | 'blocked_scheme', message: string) {
    super(message)
    this.name = 'BrowserAddressError'
  }
}

export type AddressResolution =
  | { kind: 'url'; url: string }
  | { kind: 'search'; url: string }

/** 顶层导航明确拒绝的协议：这些字符串绝不能变成 webview 的文档地址。 */
const BLOCKED_SCHEMES = new Set([
  'javascript', 'data', 'file', 'tauri', 'asset', 'ipc', 'about', 'blob', 'chrome', 'edge',
  'view-source', 'vbscript', 'mailto', 'tel', 'ftp', 'ws', 'wss',
])

/** `localhost:3000` 这种 host:port 里的冒号不是协议分隔符。 */
function explicitScheme(raw: string): { scheme: string; rest: string } | null {
  const match = /^([a-zA-Z][a-zA-Z0-9+.-]*):(.*)$/.exec(raw)
  return match ? { scheme: match[1].toLowerCase(), rest: match[2] } : null
}

function hostOf(text: string): string {
  const host = text.split(/[/?#]/)[0] || text
  return host.replace(/:\d+$/, '')
}

function isLocalHost(text: string): boolean {
  const raw = text.split(/[/?#]/)[0] || text
  if (raw.startsWith('[')) return true
  const host = hostOf(text)
  return host.toLowerCase() === 'localhost' || /^\d{1,3}(\.\d{1,3}){3}$/.test(host)
}

/** 只看主机的形状：无空白、全 ASCII、带点，且最后一段是至少两位的字母（`v2.0` 走搜索）。 */
function looksLikeDomain(text: string): boolean {
  if (!text || /\s/.test(text) || /[^\x20-\x7e]/.test(text)) return false
  const host = hostOf(text)
  if (!host.includes('.')) return false
  const last = host.split('.').pop() || ''
  return last.length >= 2 && /^[a-z]+$/i.test(last)
}

function webUrl(raw: string): string {
  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    throw new BrowserAddressError('invalid_url', '请输入完整的网页地址')
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) {
    throw new BrowserAddressError('blocked_scheme', `不支持在浏览器里打开 ${parsed.protocol.replace(':', '')}: 链接`)
  }
  return parsed.href
}

export function searchUrl(engine: SearchEngine, query: string): string {
  const text = query.trim()
  if (!text) throw new BrowserAddressError('invalid_url', '请输入要搜索的内容')
  return webUrl(engine.template.replace('{query}', encodeURIComponent(text)))
}

/**
 * 地址栏输入 → 可交给 webview 的 http/https 地址。
 * user:“网页是不可信输入”+(危险协议直接报错，不退化成搜索，避免把 `javascript:` 塞进搜索框蒙混过关)。
 */
export function resolveAddress(raw: string, engine: SearchEngine = DEFAULT_SEARCH_ENGINE): AddressResolution {
  const text = raw.trim()
  if (!text) throw new BrowserAddressError('invalid_url', '请输入网址或搜索内容')
  const scheme = explicitScheme(text)
  if (scheme) {
    const portLike = !scheme.rest.startsWith('//') && /^\d+$/.test(scheme.rest)
    if (!portLike) {
      if (scheme.scheme === 'http' || scheme.scheme === 'https') return { kind: 'url', url: webUrl(text) }
      throw new BrowserAddressError('blocked_scheme', `不支持在浏览器里打开 ${scheme.scheme}: 链接`)
    }
  }
  if (isLocalHost(text) || looksLikeDomain(text)) {
    const scheme = isLocalHost(text) ? 'http' : 'https'
    const trimmed = text.replace(/\/+$/, '')
    const candidate = trimmed.includes('/') ? `${scheme}://${trimmed}` : `${scheme}://${trimmed}/`
    try {
      return { kind: 'url', url: webUrl(candidate) }
    } catch { /* 形状像域名但解析失败时退回搜索，和浏览器行为一致 */ }
  }
  return { kind: 'search', url: searchUrl(engine, text) }
}

/** 供界面判断“这个输入指定不能打开”，不需要抛出异常。 */
export function isBlockedScheme(raw: string): boolean {
  const scheme = explicitScheme(raw.trim())
  return Boolean(scheme && BLOCKED_SCHEMES.has(scheme.scheme))
}

/**
 * user:“浏览器地址栏里显示出 [object Object]”+(地址栏只认字符串：只有字符串原样返回，
 * 对象、数字、null、undefined 一律回落到调用方给的上一次有效地址)。
 * 这条兜底不放在 String() 上：String(对象) 一定会得到 `[object Object]`，那正是要杜绝的显示。
 */
export function addressText(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

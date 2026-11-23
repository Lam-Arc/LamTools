// user:“只对 http(s) 生效；本地文件引用仍走预览器/编辑器”+
// (这里把「点一个链接到底该去哪」收敛成一份纯判定：内置浏览器 / 系统浏览器 / 本地文件 / 不接管。
//  三个入口——Ctrl/Cmd+点击、右键菜单、命令面板——都读这同一份结论，不会各写一套规则)。
export type LinkRoute = 'internal' | 'external' | 'local' | 'ignore'

export interface LinkDecision {
  /** 该走哪个通道。 */
  route: LinkRoute
  /** 归一化后的地址；`ignore` 时是原样字符串。 */
  url: string
  /** 给用户看的一句话理由：接管与不接管都要说得出为什么。 */
  reason: string
}

const HTTP_RE = /^https?:\/\//i
/** 本地文件引用：附件、工作区协议、file:// 与 Windows 盘符。 */
const LOCAL_SCHEME_RE = /^(?:attachment|workspace|file|asset|medias):/i
const WINDOWS_PATH_RE = /^[a-z]:[\\/]/i
/** 脚本类协议一律不执行（内置浏览器与系统浏览器都不该被这种链接驱动）。 */
const SCRIPT_SCHEME_RE = /^(?:javascript|data|vbscript):/i

/**
 * user:“只对 http(s) 生效”+(分类只认地址本身：相对锚点、脚本协议不接管，
 * 本地文件引用交给预览器/编辑器，其余协议交给系统)。
 */
export function classifyLink(raw: string): LinkDecision {
  const href = String(raw ?? '').trim()
  if (!href) return { route: 'ignore', url: '', reason: '空链接，没有可打开的目标' }
  if (href.startsWith('#')) return { route: 'ignore', url: href, reason: '页内锚点由页面自己处理' }
  if (SCRIPT_SCHEME_RE.test(href)) return { route: 'ignore', url: href, reason: '脚本类链接一律不执行' }
  if (HTTP_RE.test(href)) return { route: 'internal', url: href, reason: 'http(s) 链接可以在内置浏览器中打开' }
  if (LOCAL_SCHEME_RE.test(href) || WINDOWS_PATH_RE.test(href)) {
    return { route: 'local', url: href, reason: '本地文件引用走预览器/编辑器，不进浏览器' }
  }
  // 形如 `src/page.md`、`./a.txt`、`../up` 的相对路径：同样是本地引用。
  // 注意与裸域名区分：`notes/a.md` 的首段没有点（不是域名），`example.com/a` 才是链接。
  const firstSegment = href.split(/[\\/]/)[0] ?? ''
  if (/^\.{1,2}[\\/]/.test(href) || (/[\\/]/.test(href) && !firstSegment.includes('.') && !firstSegment.includes(':'))
    || /^[^:/?#\\]+\.[a-z0-9]{1,8}(?:[\\/]|$)/i.test(href)) {
    return { route: 'local', url: href, reason: '本地文件引用走预览器/编辑器，不进浏览器' }
  }
  // mailto:/tel:/magnet: 等：不属于 http(s)，交回系统处理，内置浏览器不接管。
  return { route: 'external', url: href, reason: '这种协议需要系统里对应的应用处理' }
}

/** 只有 http(s) 才进内置浏览器：调用方据此决定是否显示入口，不猜。 */
export function opensInBrowser(raw: string): boolean {
  return classifyLink(raw).route === 'internal'
}

/**
 * user:“Ctrl/Cmd + 点击链接直接进内置浏览器”+
 * (带修饰键才算「用户明确要求内置」；不带修饰键依旧是原来的系统浏览器行为，不改变旧习惯)。
 */
export function wantsInternalBrowser(event: { ctrlKey?: boolean; metaKey?: boolean }): boolean {
  return Boolean(event.ctrlKey || event.metaKey)
}

/**
 * 内容寻址层：把「预览什么」解析成「浏览器表面怎么显示」。
 *
 * user:“预览器是内容终点，浏览器是内容入口”+(这里只处理"用户已经拥有的内容"：
 * 本地文件、已渲染的 HTML、回环地址。任意外部站点一律拒绝，交给将来的浏览器模块)。
 *
 * user:“预览的三态解析只有一份…不允许再出现「两套按扩展名分派」”+
 * (扩展名知识全部来自 `./route` 那唯一一张表；本文件只负责在它之上补三件事：
 * 拼本机地址、把 Markdown 转成 HTML、把「灯箱没有这类渲染器」翻译成一句人话)。
 *
 * 这一层是纯逻辑：不碰 DOM 之外的东西，所有外部能力（拼绝对地址、读字节）都从
 * transport 注入，因此可以在单测里完全替身。
 */
import DOMPurify from 'dompurify'
import {
  LOCAL_RENDERER_REASONS,
  baseName,
  isTextPath,
  resolvePreviewRoute,
} from './route'
import type { PreviewTarget } from './target'

/**
 * 三态契约：浏览器原生能看 / 需要本地转换器渲染 / 明确看不了。
 *
 * user:“产出三态”+(调用方只需按 mode 分支，不关心某个扩展名到底归谁)。
 */
export type PreviewDocument =
  | { mode: 'native'; url: string; mime: string; title: string }
  | { mode: 'rendered'; html: string; title: string }
  | { mode: 'unsupported'; reason: string; title: string }

/**
 * 解析选项：宿主自己有没有本地渲染器。
 *
 * user:“预览的三态解析只有一份”+(灯箱没有 Office 渲染器，只能说“去分屏看”；
 *  分屏自己有 docx/xlsx/pptx 渲染器，要能把它当“可显示”处理)。
 */
export interface PreviewResolveOptions {
  localRenderers?: boolean
}

/** 解析层需要的外部能力；真实实现见 preview/transport.ts。 */
export interface PreviewResolveTransport {
  /** 把内核 HTTP 路径拼成浏览器可直接加载的绝对地址。 */
  url(path: string): string
  /** 读取本机文件字节，只有「需要转换」的类型会用到。 */
  read(path: string): Promise<Uint8Array>
}

const INTERNAL_HOSTS = new Set(['127.0.0.1', 'localhost', '::1', '[::1]'])

/**
 * 允许 iframe 加载的地址白名单。
 *
 * user:“URL 只允许 http://127.0.0.1 与内部源，禁止 file:、javascript:、任意远程站点”+
 * (灯箱只承载本地内容；外部站点既嵌不进来，也不该由预览器承担)。
 */
export function isInternalPreviewUrl(url: string): boolean {
  if (!url) return false
  if (url === 'about:srcdoc' || url.startsWith('about:srcdoc')) return true
  if (url.startsWith('blob:')) return true
  // 同源相对地址（浏览器开发模式没有随机端口，走相对路径由 dev 代理转给后台）。
  if (url.startsWith('/') && !url.startsWith('//')) return true
  let parsed: URL
  try { parsed = new URL(url) } catch { return false }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
  return INTERNAL_HOSTS.has(parsed.hostname)
}

/** 危险 scheme：路径本身也可能带着这些前缀，一律拒绝。 */
export function isDangerousReference(value: string): boolean {
  return /^\s*(javascript|vbscript|file|data):/i.test(value || '')
}

/**
 * 转换出来的 HTML 的清理规则。
 *
 * user:“rendered 的 HTML 必须过白名单清理，禁止脚本、禁止远程资源引用”+
 * (转换器输出可能与文件内容同源，不能信任：脚本、内嵌框架、表单一律去掉，
 * 图片/链接只保留回环地址，远程资源直接删掉属性而不是留一个坏链)。
 */
export function sanitizePreviewHtml(html: string): string {
  const clean = DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form', 'base', 'meta', 'link', 'frame', 'frameset'],
    FORBID_ATTR: ['srcset', 'formaction', 'ping', 'onerror', 'onload'],
  })
  return stripRemoteResources(clean)
}

function stripRemoteResources(html: string): string {
  if (typeof document === 'undefined') return html
  const host = document.createElement('div')
  host.innerHTML = html
  for (const element of Array.from(host.querySelectorAll('[src], [href], [poster], [action]'))) {
    for (const attribute of ['src', 'href', 'poster', 'action']) {
      const value = element.getAttribute(attribute)
      if (value === null) continue
      if (isDangerousReference(value)) { element.removeAttribute(attribute); continue }
      if (/^(https?:)?\/\//i.test(value) || value.startsWith('data:')) {
        const absolute = value.startsWith('//') ? `http:${value}` : value
        if (!isInternalPreviewUrl(absolute)) element.removeAttribute(attribute)
      }
    }
  }
  return host.innerHTML
}

/** 某个路径是否由浏览器原生显示（native）；不是则返回 null。 */
export function nativeMimeFor(path: string): string | null {
  const route = resolvePreviewRoute(path)
  if (route.kind !== 'native') return null
  return route.mime
}

/** 人类可读的类型标签，给灯箱头部用。 */
export function previewMimeLabel(mime: string): string {
  if (!mime) return '文件'
  if (mime.startsWith('image/')) return '图片'
  if (mime.startsWith('video/')) return '视频'
  if (mime.startsWith('audio/')) return '音频'
  if (mime === 'application/pdf') return 'PDF'
  if (mime.startsWith('text/')) return '文本'
  return '文件'
}

/**
 * 本机文件的内联读取地址。
 *
 * user:“必须实测 read-reference 的响应头”+(Starlette 默认带 Content-Disposition: attachment，
 * 会让 iframe 变成下载；inline=1 是后端为内联渲染开的那一个口子)。
 *
 * user:“与灯箱共用同一条解析与呈现链路”+(分屏也走这一个函数，两处不能再各拼一份查询参数)。
 */
export function previewReadPath(path: string, workRoot?: string): string {
  const query = new URLSearchParams({ path, inline: '1', ...(workRoot ? { work_root: workRoot } : {}) })
  return `/files/read-reference?${query.toString()}`
}

/**
 * 浏览器解不了的位图（TIF/TIFF）走这条：后端用 Pillow 转成 PNG 再给图片查看器。
 *
 * user:“除了Office类，别的都把它修好”+(否则这些图只能交给默认应用，灯箱里看不到)。
 */
export function previewRasterPath(path: string, workRoot?: string): string {
  const query = new URLSearchParams({ path, inline: '1', ...(workRoot ? { work_root: workRoot } : {}) })
  return `/files/preview-image?${query.toString()}`
}

function unsupported(reason: string, title: string): PreviewDocument {
  return { mode: 'unsupported', reason, title }
}

/**
 * 解析成浏览器表面要显示的内容。
 *
 * user:“resolvePreviewDocument(target, transport)”+(调用方把目标与通道交进来，
 * 拿回三态之一；同一种文件在灯箱和别处走同一条判定，不会有两套体验)。
 */
export async function resolvePreviewDocument(
  target: PreviewTarget,
  transport: PreviewResolveTransport,
  options: PreviewResolveOptions = {},
): Promise<PreviewDocument> {
  if (target.kind === 'html') {
    const title = target.title || '预览'
    return { mode: 'rendered', html: sanitizePreviewHtml(target.html), title }
  }

  if (target.kind === 'url') {
    const title = previewHost(target.url) || '网页'
    if (!isInternalPreviewUrl(target.url)) {
      // 刻意不实现网页浏览：外部站点既嵌不进来，也不属于预览器的职责。
      return unsupported('外部网页不能作为本地内容预览；请在浏览器中打开', title)
    }
    const mime = nativeMimeFor(target.url.split(/[?#]/)[0]) || 'application/octet-stream'
    return { mode: 'native', url: target.url, mime, title }
  }

  const path = target.path || ''
  const title = baseName(path) || '文件'
  if (!path) return unsupported('没有可预览的文件路径', title)
  if (isDangerousReference(path)) return unsupported('这个路径使用了禁止的协议，不能预览', title)

  const route = resolvePreviewRoute(path)
  const url = transport.url(route.kind === 'native' && route.raster
    ? previewRasterPath(path, target.workRoot)
    : previewReadPath(path, target.workRoot))

  if (route.kind === 'native') {
    if (!isInternalPreviewUrl(url)) return unsupported('预览通道没有绑定本机后台地址，无法内联显示', title)
    return { mode: 'native', url, mime: route.mime, title }
  }

  if (route.kind === 'text') {
    if (!isInternalPreviewUrl(url)) return unsupported('预览通道没有绑定本机后台地址，无法内联显示', title)
    return { mode: 'native', url, mime: 'text/plain; charset=utf-8', title }
  }

  if (route.kind === 'markdown') {
    try {
      const bytes = await transport.read(previewReadPath(path, target.workRoot))
      const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes)
      return { mode: 'rendered', html: sanitizePreviewHtml(markdownToHtml(text)), title }
    } catch (cause) {
      return unsupported(cause instanceof Error ? cause.message : '文件无法读取', title)
    }
  }

  if (route.kind === 'local') {
    // user:“不能看的，给的原因和动作与灯箱一致”+(灯箱没有这些渲染器，说清去哪儿看)。
    // 分屏声明自己会排版时，交给它继续读字节渲染，不再说“去分屏看”。
    if (options.localRenderers) return { mode: 'native', url, mime: 'application/octet-stream', title }
    return unsupported(LOCAL_RENDERER_REASONS[route.renderer], title)
  }

  return unsupported(route.reason, title)
}

function previewHost(url: string): string {
  try { return new URL(url).hostname } catch { return '' }
}

/**
 * Markdown 的最小转换器。
 *
 * 刻意不复用 MarkdownRenderer 的完整管线（KaTeX、Mermaid、交互块都需要组件运行时），
 * 灯箱只需要"能读的排版"；完整排版仍由分屏预览承担。
 * TODO(preview/browser 收口)：文档类渲染器统一收编时换成同一条转换管线。
 */
function markdownToHtml(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  const blocks: string[] = []
  const lines = escaped.split(/\r?\n/)
  let paragraph: string[] = []
  let list: string[] = []
  const flushParagraph = () => {
    if (!paragraph.length) return
    blocks.push(`<p>${paragraph.join('<br>')}</p>`)
    paragraph = []
  }
  const flushList = () => {
    if (!list.length) return
    blocks.push(`<ul>${list.map(item => `<li>${item}</li>`).join('')}</ul>`)
    list = []
  }
  for (const line of lines) {
    if (!line.trim()) { flushParagraph(); flushList(); continue }
    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      flushParagraph(); flushList()
      const level = heading[1].length
      blocks.push(`<h${level}>${heading[2]}</h${level}>`)
      continue
    }
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    if (bullet) { flushParagraph(); list.push(bullet[1]); continue }
    flushList()
    paragraph.push(line)
  }
  flushParagraph(); flushList()
  return blocks.join('\n')
}

/** 供分屏复用的文本判定：文本进编辑器而不是预览器。 */
export { isTextPath }

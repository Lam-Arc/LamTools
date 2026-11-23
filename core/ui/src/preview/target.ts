/**
 * 预览器「预览什么」的唯一描述。
 *
 * user:“预览器统一成一个浏览器表面，用两种形态承载（灯箱/分屏）”+(内容寻址层先独立，
 * 灯箱与将来的浏览器工作区都只认这个类型，不各自定义"打开什么")。
 *
 * 刻意不放进分屏状态：分屏的标签树要求每个标签属于一个 pane，而灯箱是单例、没有 pane，
 * 硬塞进去会让两套生命周期互相牵制。
 */

/** 本机文件：路径 + 解析它所需的作用域（项目目录、项目/会话归属）。 */
export interface PreviewFileTarget {
  kind: 'file'
  path: string
  workRoot?: string
  projectId?: string
  sessionId?: string
}

/** 本机可内联渲染的地址（只允许回环地址；外部站点由浏览器模块负责）。 */
export interface PreviewUrlTarget {
  kind: 'url'
  url: string
  /** 展示用名字：`data:` / `blob:` 这类地址没有主机名，标题栏需要一个能读的名字。 */
  title?: string
}

/** 已经渲染好的 HTML（成果物、生成内容、转换器输出的统一出口）。 */
export interface PreviewHtmlTarget {
  kind: 'html'
  html: string
  title: string
}

export type PreviewTarget = PreviewFileTarget | PreviewUrlTarget | PreviewHtmlTarget

/** 文件路径在预览里的作用域。 */
export interface PreviewFileScope {
  workRoot?: string
  projectId?: string
  sessionId?: string
}

export function filePreviewTarget(path: string, scope: PreviewFileScope = {}): PreviewFileTarget {
  return {
    kind: 'file',
    path,
    ...(scope.workRoot ? { workRoot: scope.workRoot } : {}),
    ...(scope.projectId ? { projectId: scope.projectId } : {}),
    ...(scope.sessionId ? { sessionId: scope.sessionId } : {}),
  }
}

export function urlPreviewTarget(url: string, title?: string): PreviewUrlTarget {
  return { kind: 'url', url, ...(title ? { title } : {}) }
}

export function htmlPreviewTarget(html: string, title = '预览'): PreviewHtmlTarget {
  return { kind: 'html', html, title: title || '预览' }
}

/**
 * 同一个预览目标在灯箱与别处之间移交时用的身份。
 *
 * user:“同一个预览目标能在两种形态间一键切换、内容不重载”+(移交必须能判定"还是那一份"，
 * 所以身份由目标自身内容决定，而不是由当前打开它的界面决定)。
 */
export function previewTargetKey(target: PreviewTarget | null | undefined): string {
  if (!target) return ''
  if (target.kind === 'file') {
    const root = (target.workRoot || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    return `file\0${root}\0${target.path.replace(/\\/g, '/').toLowerCase()}`
  }
  if (target.kind === 'url') return `url\0${target.url}`
  return `html\0${target.title}`
}

/** 顶部标题：文件名 / 地址主机名 / HTML 自带的标题。 */
export function previewTargetTitle(target: PreviewTarget | null | undefined): string {
  if (!target) return ''
  if (target.kind === 'file') {
    const name = target.path.replace(/\\/g, '/').split('/').filter(Boolean).pop()
    return name || target.path || '文件'
  }
  if (target.kind === 'url') {
    if (target.title) return target.title
    try { return new URL(target.url).hostname || target.url } catch { return target.url }
  }
  return target.title || '预览'
}

/** 只有文件目标能交给系统默认应用打开。 */
export function previewTargetPath(target: PreviewTarget | null | undefined): string {
  return target && target.kind === 'file' ? target.path : ''
}

export function isPreviewTarget(value: unknown): value is PreviewTarget {
  if (!value || typeof value !== 'object') return false
  const candidate = value as { kind?: unknown; path?: unknown; url?: unknown; html?: unknown }
  if (candidate.kind === 'file') return typeof candidate.path === 'string' && candidate.path.length > 0
  if (candidate.kind === 'url') return typeof candidate.url === 'string'
  if (candidate.kind === 'html') return typeof candidate.html === 'string'
  return false
}

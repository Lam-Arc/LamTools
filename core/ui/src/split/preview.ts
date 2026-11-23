/**
 * 分屏的「进编辑器还是进预览器」判断，以及给旧调用方保留的类型标签。
 *
 * user:“预览的三态解析只有一份…不允许再出现「两套按扩展名分派」”+
 * (这里不再维护任何扩展名表：谁是图片、谁是 Office、谁看不了，全部由
 * `@/preview/route` 那唯一一张表回答。本文件只剩两个问题要回答——
 * 进编辑器还是进预览器，以及预览器该用哪个渲染器。)
 */
import {
  baseName,
  fileExtension,
  isTextPath,
  resolvePreviewRoute,
  type PreviewLocalRenderer,
  type PreviewMediaFamily,
} from '@/preview/route'

export { baseName, fileExtension, isTextPath }

/**
 * 分屏预览使用的渲染器名。
 *
 * user:“分屏预览器不支持图片吗？改一下图片，视频 office，什么东西都尽可能支持一下”+
 * (按文件类型把富媒体、文档与普通文本分开，决定分屏用预览器还是文本编辑器打开)。
 */
export type SplitPreviewKind = PreviewMediaFamily | PreviewLocalRenderer | 'markdown'

/**
 * 预览器要用的渲染器；文本与确实看不了的类型返回 null。
 *
 * user:“docx/xlsx/pptx/md 保留现有前端渲染器，但必须经 resolve 决定走哪条路”+
 * (返回什么完全由统一分派表决定，组件不再自己认扩展名)。
 */
export function previewKindFor(path: string): SplitPreviewKind | null {
  const route = resolvePreviewRoute(path)
  if (route.kind === 'native') return route.family
  if (route.kind === 'local') return route.renderer
  if (route.kind === 'markdown') return 'markdown'
  return null
}

/**
 * user:“默认打开也跟文本文件一样 用分屏预览打开”+
 * (文本继续用编辑器；图片/音视频/PDF/Office 以及无法判断类型的文件都进预览器——
 * 看不了的类型也要进预览器，那里才会给出原因和「用默认应用打开」的出口，
 * 而不是把二进制塞进文本编辑器)。
 */
export function splitContentFor(path: string): 'preview' | 'editor' {
  if (!path) return 'editor'
  if (resolvePreviewRoute(path).kind === 'text') return 'editor'
  return 'preview'
}

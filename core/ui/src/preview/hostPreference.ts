/**
 * 预览器的默认打开宿位。
 *
 * user:“媒体类（image/video/audio/pdf）→ 灯箱；文档类（md/docx/xlsx/pptx）与文本 → 分屏”+
 * (这条规则只决定"用户点一个东西时先落在哪"，两种形态共用同一个浏览器表面，
 * 所以切换宿位不改变看到的内容。)
 */
import { nativeMimeFor } from './resolve'

export type PreviewHost = 'lightbox' | 'split'

/** 按扩展名判断默认宿位；无法判断的类型不猜，交回既有分屏通道。 */
export function defaultPreviewHost(path: string): PreviewHost {
  const mime = nativeMimeFor(path)
  if (!mime) return 'split'
  if (mime.startsWith('image/') || mime.startsWith('video/') || mime.startsWith('audio/')) return 'lightbox'
  if (mime === 'application/pdf') return 'lightbox'
  return 'split'
}

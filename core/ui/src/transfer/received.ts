/**
 * 一条已收到的文件能做什么：预览 / 打开所在文件夹。
 *
 * user:“接收列表：列出 received[]，每条可「预览」（走 core/ui/src/preview/ 的统一链路）与
 * 「打开所在文件夹」；新收到的文件要有可见提示”+(预览的判断只有一份：问 `preview/route`
 * 的分派表，不在这里再按扩展名写第二套；「能不能预览」与「不能的话为什么」一起返回，
 * 界面不会出现点了没反应的按钮)。
 *
 * 纯函数：不碰 DOM、不发请求，单测里零替身即可验证。
 */
import { t } from '@/i18n/index.ts'
import { LOCAL_RENDERER_REASONS, baseName, resolvePreviewRoute } from '@/preview/route'
import { filePreviewTarget, type PreviewFileTarget } from '@/preview/target'
import { formatBytes } from './shape'
import type { ReceivedRow } from './shape'

export interface ReceivedActions {
  /** 能不能在灯箱里直接看。 */
  canPreview: boolean
  /** 不能预览时的一句话原因（能预览时为空串）。 */
  previewReason: string
  /** 能不能在系统文件管理器里定位（绝对路径才能）。 */
  canReveal: boolean
}

/** 绝对路径判定：跨平台只看「像不像一条完整路径」，不假设分隔符。 */
export function isAbsolutePath(path: string): boolean {
  const value = (path || '').trim()
  if (!value) return false
  if (/^[a-zA-Z]:[\\/]/.test(value)) return true // Windows 盘符
  return value.startsWith('/') || value.startsWith('\\\\')
}

/**
 * 接收项的动作资格。
 *
 * local 渲染器（docx/xlsx/pptx）不在灯箱里排不了版：如实说「去分屏看或打开文件夹」，
 * 而不是给一个点了只会弹「不支持」的预览按钮。
 */
export function receivedActions(row: Pick<ReceivedRow, 'path'>): ReceivedActions {
  const path = (row.path || '').trim()
  if (!path) {
    return { canPreview: false, previewReason: t('这条记录没有落盘路径。'), canReveal: false }
  }
  const canReveal = isAbsolutePath(path)
  const route = resolvePreviewRoute(path)
  if (route.kind === 'local') {
    return { canPreview: false, previewReason: t(LOCAL_RENDERER_REASONS[route.renderer]), canReveal }
  }
  if (route.kind === 'unsupported') {
    return { canPreview: false, previewReason: t(route.reason), canReveal }
  }
  return { canPreview: true, previewReason: '', canReveal }
}

/** 预览目标：一律整成「本机文件」，交给灯箱那一条链路去解析。 */
export function receivedPreviewTarget(row: Pick<ReceivedRow, 'path'>): PreviewFileTarget {
  return filePreviewTarget(row.path)
}

/** 「打开所在文件夹」的参数：传文件路径，宿主负责定位到父目录并选中它。 */
export function receivedRevealArgs(row: Pick<ReceivedRow, 'path'>): { path: string } {
  return { path: row.path }
}

/** 接收项的第二行：大小 · 谁发的 · 什么时候。缺的字段不显示占位符。 */
export function receivedMeta(row: ReceivedRow): string {
  const parts: string[] = [formatBytes(row.size)]
  const sender = (row.peer || row.from || '').trim()
  if (sender) parts.push(t('来自 {0}', { 0: sender }))
  if (row.at > 0) parts.push(formatTime(row.at))
  return parts.join(' · ')
}

/** 落盘时间：本地时区的 MM-DD HH:mm，够用且不会因为年份变长挤坏一行。 */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  const date = new Date(seconds * 1000)
  const pad = (value: number) => String(value).padStart(2, '0')
  return pad(date.getMonth() + 1) + '-' + pad(date.getDate()) + ' ' + pad(date.getHours()) + ':' + pad(date.getMinutes())
}

/** 接收项标题：宿主给的名字优先，缺了就从路径里取。 */
export function receivedTitle(row: Pick<ReceivedRow, 'name' | 'path'>): string {
  return (row.name || '').trim() || baseName(row.path) || t('未命名文件')
}

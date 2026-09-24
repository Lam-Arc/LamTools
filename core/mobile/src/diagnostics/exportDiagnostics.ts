import { invoke } from '@tauri-apps/api/core'
import { hasEmbeddedRustCore } from '../native/rustAgent'
import { MOBILE_DIAGNOSTIC_FILE_NAME, MOBILE_DIAGNOSTIC_EXPORT_LIMIT_BYTES } from './MobileDiagnostics'

export type DiagnosticExportDestination = 'android-share' | 'web-share' | 'download'

/** Export diagnostics through Android's chooser, with browser sharing/download fallbacks. */
export async function exportMobileDiagnostics(contents: string): Promise<DiagnosticExportDestination> {
  if (new TextEncoder().encode(contents).byteLength > MOBILE_DIAGNOSTIC_EXPORT_LIMIT_BYTES) {
    throw new Error('诊断日志超出可导出大小上限')
  }

  if (isAndroidTauri()) {
    try {
      await invoke('mobile_diagnostics_share', { contents })
      return 'android-share'
    } catch {
      throw new Error('无法打开 Android 分享面板')
    }
  }

  const file = new File([contents], MOBILE_DIAGNOSTIC_FILE_NAME, { type: 'application/json' })
  if (supportsFileShare(file)) {
    await navigator.share({ files: [file], title: 'LamTools 移动端诊断日志' })
    return 'web-share'
  }

  downloadFile(contents)
  return 'download'
}

function isAndroidTauri(): boolean {
  return hasEmbeddedRustCore()
    && typeof navigator !== 'undefined'
    && /android/i.test(navigator.userAgent)
}

function supportsFileShare(file: File): boolean {
  if (typeof navigator === 'undefined' || typeof navigator.share !== 'function') return false
  const canShare = (navigator as Navigator & { canShare?: (data: ShareData) => boolean }).canShare
  return typeof canShare !== 'function' || canShare.call(navigator, { files: [file] })
}

function downloadFile(contents: string): void {
  if (typeof document === 'undefined' || typeof URL.createObjectURL !== 'function') {
    throw new Error('当前环境不支持导出诊断日志')
  }
  const url = URL.createObjectURL(new Blob([contents], { type: 'application/json' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = MOBILE_DIAGNOSTIC_FILE_NAME
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

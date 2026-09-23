import { invoke } from '@tauri-apps/api/core'

export interface NativeWindowInsets {
  top: number
  right: number
  bottom: number
  left: number
}

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

function finiteInset(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0
}

function normalizeInsets(value: unknown): NativeWindowInsets | null {
  const record = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  // A missing top value means the native view has not received insets yet.
  // Keep that state distinct from a valid zero inset so startup can retry.
  if (typeof record.top !== 'number' || !Number.isFinite(record.top) || record.top < 0) return null
  return {
    top: record.top,
    right: finiteInset(record.right),
    bottom: finiteInset(record.bottom),
    left: finiteInset(record.left),
  }
}

/** Read the Android edge-to-edge insets through the Tauri native bridge. */
export async function readNativeWindowInsets(): Promise<NativeWindowInsets | null> {
  if (!isTauriRuntime()) return null
  try {
    return normalizeInsets(await invoke<NativeWindowInsets>('window_insets_get'))
  } catch {
    // Non-Android Tauri hosts and older installed builds do not expose this
    // command. CSS env() remains the fallback in those environments.
    return null
  }
}

/**
 * Keep the CSS custom properties current across rotation and system-bar
 * changes. The native bridge returns CSS pixels, so no density conversion is
 * needed in the web layer.
 */
export function observeNativeWindowInsets(
  apply: (insets: NativeWindowInsets) => void,
): () => void {
  if (!isTauriRuntime()) return () => {}

  let timer: number | undefined
  let disposed = false
  let startupRetryCount = 0
  const maxStartupRetries = 8

  const sync = async (): Promise<void> => {
    const insets = await readNativeWindowInsets()
    if (disposed) return
    if (insets) {
      apply(insets)
      // Some Android WebViews report a provisional zero before system-bar
      // insets reach the decor view. Apply it, but keep the startup retries so
      // a later nonzero inset can move the title bar below the status bar.
      if (insets.top > 0) {
        if (timer !== undefined) {
          window.clearTimeout(timer)
          timer = undefined
        }
        return
      }
    }
    if (startupRetryCount >= maxStartupRetries || timer !== undefined) return
    const delay = Math.min(50 * (startupRetryCount + 1), 400)
    startupRetryCount += 1
    timer = window.setTimeout(() => {
      timer = undefined
      void sync()
    }, delay)
  }
  const schedule = (): void => {
    if (timer !== undefined) window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      timer = undefined
      void sync()
    }, 50)
  }

  void sync()
  window.addEventListener('resize', schedule, { passive: true })
  window.visualViewport?.addEventListener('resize', schedule, { passive: true })

  return () => {
    disposed = true
    if (timer !== undefined) window.clearTimeout(timer)
    window.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('resize', schedule)
  }
}

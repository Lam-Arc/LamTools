import { invoke } from '@tauri-apps/api/core'

export interface NativeWindowInsets {
  top: number
  right: number
  bottom: number
  left: number
  /** Height of the on-screen keyboard in CSS pixels; 0 while it is closed. */
  imeBottom: number
}

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

function finiteInset(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0
}

/**
 * How often the native bridge is polled while a text field holds focus. The
 * keyboard animates in over ~250ms, so a couple of ticks follow it and the
 * sampler then keeps the value current while typing.
 */
const KEYBOARD_SAMPLE_INTERVAL_MS = 200

function isEditableFocused(): boolean {
  if (typeof document === 'undefined') return false
  const active = document.activeElement as (Element & { closest?: (selector: string) => unknown }) | null
  if (!active || typeof active.closest !== 'function') return false
  return Boolean(active.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'))
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
    imeBottom: finiteInset(record.imeBottom),
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
  let applied: NativeWindowInsets | null = null

  const sameInsets = (a: NativeWindowInsets, b: NativeWindowInsets): boolean => (
    a.top === b.top && a.right === b.right && a.bottom === b.bottom
    && a.left === b.left && a.imeBottom === b.imeBottom
  )

  const sync = async (): Promise<void> => {
    const insets = await readNativeWindowInsets()
    if (disposed) return
    if (insets) {
      // The keyboard sampler below polls while a field is focused; skipping
      // unchanged values keeps that from invalidating styles every tick.
      if (!applied || !sameInsets(applied, insets)) {
        applied = insets
        apply(insets)
      }
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

  // Edge-to-edge keeps the WebView at full height while the IME is up, so no
  // viewport event announces the keyboard. Sample the native inset while a
  // text field holds focus instead; the IME animation settles within a few
  // ticks and the sampler stops on blur.
  let keyboardTimer: number | undefined
  const stopKeyboardSampling = (): void => {
    if (keyboardTimer === undefined) return
    window.clearInterval(keyboardTimer)
    keyboardTimer = undefined
  }
  const startKeyboardSampling = (): void => {
    if (keyboardTimer !== undefined) return
    keyboardTimer = window.setInterval(() => {
      if (disposed || !isEditableFocused()) {
        stopKeyboardSampling()
        return
      }
      void sync()
    }, KEYBOARD_SAMPLE_INTERVAL_MS)
  }
  const onFocusChange = (): void => {
    if (isEditableFocused()) startKeyboardSampling()
    else stopKeyboardSampling()
    schedule()
  }

  void sync()
  window.addEventListener('resize', schedule, { passive: true })
  window.visualViewport?.addEventListener('resize', schedule, { passive: true })
  // Focus events are the only keyboard signal available without a viewport
  // change; a host without a document simply never starts sampling.
  const focusTarget = typeof document === 'undefined' ? null : document
  focusTarget?.addEventListener('focusin', onFocusChange)
  focusTarget?.addEventListener('focusout', onFocusChange)

  return () => {
    disposed = true
    if (timer !== undefined) window.clearTimeout(timer)
    stopKeyboardSampling()
    window.removeEventListener('resize', schedule)
    window.visualViewport?.removeEventListener('resize', schedule)
    focusTarget?.removeEventListener('focusin', onFocusChange)
    focusTarget?.removeEventListener('focusout', onFocusChange)
  }
}

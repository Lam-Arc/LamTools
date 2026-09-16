import { ref, type Ref } from 'vue'

/**
 * Global toast service — the single place UI-wide notifications are shown.
 *
 * Before this existed, every surface (workspace shell, approval controller,
 * goal strip, composer, panels) rendered its own error/notice with its own
 * lifecycle: some auto-dismissed, some stayed pinned until the user happened
 * to clear them, and there was no way to dismiss one manually. The shell had
 * exactly two fixed slots fed by five sources, so a second error silently
 * replaced the first.
 *
 * This module is a module-level singleton (no component instance needed):
 *  - `show()` queues a toast, de-duplicates identical text within 3s, and
 *    auto-dismisses it after a kind-dependent duration (errors 8s, others 3s).
 *  - `dismiss(id)` / `dismissAll()` let the host render close buttons and
 *    "clear" affordances.
 *  - `CoreToastHost` (mounted once inside WorkspaceShell) renders the list;
 *    multiple toasts stack vertically instead of overwriting each other.
 *
 * Lifecycle contract: every toast MUST eventually disappear on its own
 * (duration) or be dismissed explicitly — nothing stays pinned forever.
 */
export type CoreToastKind = 'error' | 'notice' | 'success'

export interface CoreToast {
  id: number
  kind: CoreToastKind
  text: string
  createdAt: number
  duration: number
}

const DEFAULT_DURATION: Record<CoreToastKind, number> = {
  error: 8000,
  notice: 3000,
  success: 3000,
}

/** De-dupe window: an identical (kind, text) toast within this window is skipped. */
const DEDUPE_WINDOW_MS = 3000
export const TRANSIENT_CONNECTION_ERROR_GRACE_MS = 2000

let nextId = 1
const toasts = ref<CoreToast[]>([]) as Ref<CoreToast[]>
const timers = new Map<number, ReturnType<typeof setTimeout>>()

function _dismiss(id: number) {
  const timer = timers.get(id)
  if (timer !== undefined) {
    clearTimeout(timer)
    timers.delete(id)
  }
  const index = toasts.value.findIndex((toast) => toast.id === id)
  if (index !== -1) toasts.value.splice(index, 1)
}

export function showToast(kind: CoreToastKind, text: string, duration?: number): number {
  const normalized = String(text ?? '').trim()
  if (!normalized) return -1
  const now = Date.now()
  const seen = toasts.value.find(
    (toast) => toast.kind === kind && toast.text === normalized && now - toast.createdAt < DEDUPE_WINDOW_MS,
  )
  if (seen) return seen.id

  const id = nextId++
  const toast: CoreToast = {
    id,
    kind,
    text: normalized,
    createdAt: now,
    duration: duration ?? DEFAULT_DURATION[kind],
  }
  toasts.value.push(toast)
  timers.set(
    id,
    setTimeout(() => _dismiss(id), toast.duration),
  )
  return id
}

export function isTransientCoreConnectionError(text: string): boolean {
  const normalized = String(text ?? '').trim().toLowerCase()
  return normalized.startsWith('lamtools direct transport disconnected')
    || normalized.startsWith('lamtools direct transport connection failed')
    || normalized.startsWith('lamtools direct transport closed during connect')
    || normalized === 'core app server transport closed'
}

export interface CoreConnectionErrorToastGate {
  report(text: string, duration?: number): number
  onConnectionState(state: 'connecting' | 'open' | 'closed' | 'error'): void
  dispose(): void
}

/**
 * Delay only transport-disconnect errors. A reconnect inside the grace window
 * cancels the toast; business/provider errors remain immediate and unchanged.
 */
export function createCoreConnectionErrorToastGate(options: {
  isConnected: () => boolean
  graceMs?: number
  emit?: (kind: CoreToastKind, text: string, duration?: number) => number
}): CoreConnectionErrorToastGate {
  const graceMs = options.graceMs ?? TRANSIENT_CONNECTION_ERROR_GRACE_MS
  const emit = options.emit ?? showToast
  let pendingTimer: ReturnType<typeof setTimeout> | null = null
  let pendingText = ''
  let pendingDuration: number | undefined

  function clearPending(): void {
    if (pendingTimer !== null) clearTimeout(pendingTimer)
    pendingTimer = null
    pendingText = ''
    pendingDuration = undefined
  }

  return {
    report(text: string, duration?: number): number {
      const normalized = String(text ?? '').trim()
      if (!normalized) return -1
      if (!isTransientCoreConnectionError(normalized)) {
        return emit('error', normalized, duration)
      }
      if (options.isConnected()) {
        clearPending()
        return -1
      }
      pendingText = normalized
      pendingDuration = duration
      if (pendingTimer === null) {
        pendingTimer = setTimeout(() => {
          pendingTimer = null
          if (!options.isConnected() && pendingText) {
            emit('error', pendingText, pendingDuration)
          }
          pendingText = ''
          pendingDuration = undefined
        }, Math.max(0, graceMs))
      }
      return -1
    },
    onConnectionState(state): void {
      if (state === 'open') clearPending()
    },
    dispose(): void {
      clearPending()
    },
  }
}

export function dismissToast(id: number) {
  _dismiss(id)
}

export function dismissAllToasts() {
  for (const id of [...toasts.value.map((toast) => toast.id)]) _dismiss(id)
}

export function useCoreToast() {
  return {
    toasts,
    show: showToast,
    dismiss: dismissToast,
    dismissAll: dismissAllToasts,
  }
}

/** Test hook: clears queued toasts and their timers. Not part of the public API. */
export function __resetCoreToastStoreForTests() {
  for (const id of [...toasts.value.map((toast) => toast.id)]) _dismiss(id)
  nextId = 1
}

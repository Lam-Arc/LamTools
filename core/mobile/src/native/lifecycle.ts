import { App } from '@capacitor/app'

export type LifecycleListener = () => void

export function onMobileResume(listener: LifecycleListener): () => void {
  let disposed = false
  let hasResumed = false
  let lastResumeAt = 0
  const invoke = () => {
    if (disposed) return
    // A native foreground transition commonly emits appStateChange together
    // with focus/visibilitychange. Treat that burst as one resume so callers
    // do not start overlapping reconnect and refresh work.
    const now = Date.now()
    if (hasResumed && now - lastResumeAt < 250) return
    hasResumed = true
    lastResumeAt = now
    listener()
  }
  const handler = () => {
    if (document.visibilityState === 'visible') invoke()
  }
  window.addEventListener('focus', handler)
  document.addEventListener('visibilitychange', handler)
  let removeNative: (() => Promise<void>) | null = null
  void App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) invoke()
  }).then((handle) => {
    if (disposed) void handle.remove()
    else removeNative = () => handle.remove()
  }).catch(() => undefined)
  return () => {
    disposed = true
    window.removeEventListener('focus', handler)
    document.removeEventListener('visibilitychange', handler)
    void removeNative?.()
  }
}

/**
 * The app is losing the foreground.
 *
 * Android can reclaim a backgrounded process without any further callback, so
 * this is the last reliable moment to make in-memory state durable. It is a
 * best-effort signal, never a guarantee: work that must survive a kill has to be
 * written before this fires.
 */
export function onMobilePause(listener: LifecycleListener): () => void {
  let disposed = false
  let lastPauseAt = 0
  const invoke = () => {
    if (disposed) return
    // A background transition emits several of these; treat the burst as one so
    // callers do not start overlapping saves.
    const now = Date.now()
    if (now - lastPauseAt < 250) return
    lastPauseAt = now
    listener()
  }
  const handler = () => {
    if (document.visibilityState === 'hidden') invoke()
  }
  document.addEventListener('visibilitychange', handler)
  window.addEventListener('pagehide', invoke)
  let removeNative: (() => Promise<void>) | null = null
  try {
    void App.addListener('appStateChange', ({ isActive }) => {
      if (!isActive) invoke()
    }).then((handle) => {
      if (disposed) void handle.remove()
      else removeNative = () => handle.remove()
    }).catch(() => undefined)
  } catch {
    // Without the native plugin the DOM signals above still report the pause.
  }
  return () => {
    disposed = true
    document.removeEventListener('visibilitychange', handler)
    window.removeEventListener('pagehide', invoke)
    void removeNative?.()
  }
}

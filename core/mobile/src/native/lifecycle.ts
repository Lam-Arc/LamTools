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

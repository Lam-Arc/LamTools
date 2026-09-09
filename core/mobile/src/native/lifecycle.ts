import { App } from '@capacitor/app'

export type LifecycleListener = () => void

export function onMobileResume(listener: LifecycleListener): () => void {
  const handler = () => {
    if (document.visibilityState === 'visible') listener()
  }
  window.addEventListener('focus', handler)
  document.addEventListener('visibilitychange', handler)
  let disposed = false
  let removeNative: (() => Promise<void>) | null = null
  void App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) listener()
  }).then((handle) => {
    if (disposed) void handle.remove()
    else removeNative = () => handle.remove()
  })
  return () => {
    disposed = true
    window.removeEventListener('focus', handler)
    document.removeEventListener('visibilitychange', handler)
    void removeNative?.()
  }
}

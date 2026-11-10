/**
 * 独立截图窗口入口。
 *
 * user:“重新设计与实现 Ping 的框选工具”+(截图窗口加载一张静态截图，
 * 框选/标注/发送都在这里完成；它与 Ping 覆盖层是两个窗口。)
 */
document.title = 'Sunday Capture · loading'
window.addEventListener('error', event => {
  document.title = `Sunday Capture · error: ${event.message || 'unknown'}`
})
window.addEventListener('unhandledrejection', event => {
  const reason = event.reason instanceof Error ? event.reason.message : String(event.reason)
  document.title = `Sunday Capture · reject: ${reason}`
})

import './frontendConsoleLog'
import { createApp } from 'vue'
import '@/styles/variables.css'
import '@/styles/base.css'
import CaptureApp from '@/pet/ui/CaptureApp.vue'
import { closePingCapture, fetchPingCaptureFrame, fetchPingCaptureRegion } from '@/pet/bridge.ts'

// 页面挂载前的兜底：读图失败/加载卡住时 Esc 也能把整个窗口关掉。
window.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return
  const host = document.getElementById('capture-app')
  if (host && host.childElementCount > 0) return
  event.preventDefault()
  void closePingCapture().catch(() => undefined)
})

async function boot(): Promise<void> {
  const host = document.getElementById('capture-app')
  if (!host) {
    document.title = 'Sunday Capture · no host element'
    return
  }
  host.setAttribute('aria-label', 'Sunday 截图框选')
  let frame = null
  let bootError = ''
  let presetRegion: [number, number, number, number] | null = null
  try {
    presetRegion = await fetchPingCaptureRegion()
  } catch {
    presetRegion = null
  }
  try {
    frame = await fetchPingCaptureFrame()
  } catch (cause) {
    bootError = cause instanceof Error ? cause.message : String(cause)
  }
  createApp(CaptureApp, { frame, bootError, presetRegion }).mount(host)
  document.title = bootError ? 'Sunday Capture · error' : 'Sunday Capture · ready'
  console.log('[capture] booted', bootError || 'frame ready')
}

void boot()

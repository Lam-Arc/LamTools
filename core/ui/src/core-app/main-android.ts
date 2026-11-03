import { createApp } from 'vue'
import { createLamToolsRuntime, LamToolsApp } from '@/index.ts'
import { createIpcTransport } from '@/transport/ipcTransport.ts'

/**
 * Android/webview entry point.
 *
 * Same components, same projection, same composer as desktop: `LamToolsApp` is the
 * application. The only difference is the pipe underneath, which is Tauri IPC
 * because a listening socket would be reachable by every other app on the device.
 *
 * This file exists so the mobile build does not fork the UI. A separate mobile
 * frontend would be a second product to keep in sync, and would drift the moment
 * desktop changed.
 */

const transport = createIpcTransport()

const runtime = createLamToolsRuntime({
  transport,
  platform: 'mobile',
  capabilities: {
    // The in-app core has no native file picker yet, and no HTTP surface for
    // attachments. Reporting them as unavailable makes the UI hide those
    // affordances instead of failing when the user taps them.
    filePicker: false,
    notifications: false,
    desktopWindow: false,
  },
})

function showFailure(message: string): void {
  const node = document.getElementById('app')
  if (!node) return
  node.innerHTML = ''
  const banner = document.createElement('pre')
  banner.style.cssText = 'padding:16px;color:#f08a8a;white-space:pre-wrap;font:14px system-ui'
  banner.textContent = `Sunday could not reach its core.\n\n${message}`
  node.append(banner)
}

// Connect first, mount second. Mounting first would let a render overwrite the
// failure banner, leaving the exact symptom this is meant to avoid: a black
// screen with no explanation.
transport
  .connect()
  .then(() => {
    createApp(LamToolsApp, { runtime }).mount('#app')
    // A runtime that throws on first render must also say why, rather than
    // leaving the user with an empty dark screen.
    window.addEventListener('error', (event) => {
      if (!document.getElementById('app')?.textContent?.trim()) {
        showFailure(event.message)
      }
    })
  })
  .catch((error: unknown) => {
    showFailure(error instanceof Error ? error.message : String(error))
  })

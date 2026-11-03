import { createApp } from 'vue'
import { createLamToolsRuntime, LamToolsApp } from '@/index.ts'
import { createIpcTransport } from '@/transport/ipcTransport.ts'
import AndroidSettings from './AndroidSettings.vue'

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
 *
 * What is Android-specific lives in one overlay: the app has one endpoint and one key,
 * while the desktop settings screen edits a provider catalogue. See
 * `AndroidSettings.vue` for why those are two screens rather than one with a branch.
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

/**
 * A settings entry point that does not depend on the app shell.
 *
 * The shell is shared with desktop and its navigation assumes screens this host does not
 * have yet. An overlay keeps the settings reachable today and can be folded into the
 * shell later without touching the screen itself.
 *
 * The panel mounts on first open rather than at startup: mounting early would make the
 * first paint wait on two IPC calls for a screen most launches never show.
 */
function mountSettingsEntry(): void {
  const host = document.createElement('div')
  document.body.append(host)

  const panel = document.createElement('div')
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-label', '模型与权限设置')
  panel.style.cssText = [
    'position:fixed',
    'inset:0',
    'z-index:9999',
    'display:none',
    'overflow:auto',
    'background:#14161a',
    'color:#e6e8eb',
  ].join(';')
  host.append(panel)

  const toggle = document.createElement('button')
  toggle.type = 'button'
  toggle.textContent = '设置'
  toggle.style.cssText = [
    'position:fixed',
    'right:12px',
    'top:50%',
    'transform:translateY(-50%)',
    'z-index:10000',
    'padding:10px 14px',
    'border-radius:999px',
    'border:1px solid #2f3540',
    'background:rgba(35,40,48,.92)',
    'color:#e6e8eb',
    'font:14px system-ui',
  ].join(';')
  host.append(toggle)

  let mounted = false
  let open = false
  const setOpen = (next: boolean) => {
    open = next
    if (open && !mounted) {
      createApp(AndroidSettings).mount(panel)
      mounted = true
    }
    panel.style.display = open ? 'block' : 'none'
    toggle.textContent = open ? '返回' : '设置'
  }
  toggle.addEventListener('click', () => setOpen(!open))
}

// Connect first, mount second. Mounting first would let a render overwrite the
// failure banner, leaving the exact symptom this is meant to avoid: a black
// screen with no explanation.
transport
  .connect()
  .then(() => {
    createApp(LamToolsApp, { runtime }).mount('#app')
    mountSettingsEntry()
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

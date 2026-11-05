import { createApp } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { createLamToolsRuntime, LamToolsApp } from '@/index.ts'
import { createIpcTransport } from '@/transport/ipcTransport.ts'
import AndroidSetup from './AndroidSetup.vue'

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
 * What is Android-specific: the app first has to start its own Linux runtime and wait
 * for the Python core inside it to answer. That boot step is why the sequence below is
 * explicit instead of "connect and render": rendering before the core exists produces
 * exactly the failure this file is written to avoid, a dark screen with no explanation.
 */

const transport = createIpcTransport()

const capabilities = {
  // The picker bridge exists, but attachments still travel through the desktop HTTP
  // surface, which this host does not serve yet. Reporting them unavailable hides the
  // affordances instead of failing when the user taps them.
  filePicker: false,
  notifications: false,
  desktopWindow: false,
} as const

function renderScreen(text: string, options: { error?: boolean; action?: string } = {}): void {
  const node = document.getElementById('app')
  if (!node) return
  node.innerHTML = ''
  const panel = document.createElement('div')
  panel.style.cssText = [
    'padding:32px 22px',
    'font:15px/1.65 system-ui',
    'color:' + (options.error ? '#f08a8a' : '#e6e8eb'),
    'white-space:pre-wrap',
    'background:#14161a',
    'min-height:100vh',
    'box-sizing:border-box',
  ].join(';')
  panel.textContent = text
  if (options.action) {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = options.action
    button.style.cssText =
      'margin-top:18px;padding:11px 16px;border-radius:10px;border:1px solid #2f3540;background:#1b1f26;color:#e6e8eb;font:14px system-ui'
    button.addEventListener('click', () => window.location.reload())
    panel.append(document.createElement('br'), button)
  }
  node.append(panel)
}

async function boot(): Promise<void> {
  renderScreen('正在启动核心…\n\n首次打开需要解压随包的 Linux 运行时，可能要等一会儿。')
  try {
    await invoke('core_start')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    renderScreen(`核心启动失败。\n\n${message}`, { error: true, action: '重试' })
    return
  }

  const config = await invoke<{ hasKey: boolean }>('model_config').catch(() => null)
  if (config && !config.hasKey) {
    // No endpoint yet: the first task is configuration, not a chat that cannot answer.
    const host = document.getElementById('app')
    if (!host) return
    host.innerHTML = ''
    createApp(AndroidSetup).mount(host)
    return
  }

  const runtime = createLamToolsRuntime({
    transport,
    platform: 'mobile',
    capabilities: { ...capabilities },
  })
  await transport.connect()
  createApp(LamToolsApp, { runtime }).mount('#app')
  mountSettingsEntry()

  window.addEventListener('error', (event) => {
    if (!document.getElementById('app')?.textContent?.trim()) {
      renderScreen(`界面加载失败。\n\n${event.message}`, { error: true, action: '重试' })
    }
  })
}

/**
 * The settings entry point.
 *
 * Opens the same first-run screen: on this host "settings" and "configuration" are one
 * form, and a second screen that edits the same three fields would only be able to
 * disagree with the first.
 */
function mountSettingsEntry(): void {
  const host = document.createElement('div')
  document.body.append(host)

  const panel = document.createElement('div')
  panel.setAttribute('role', 'dialog')
  panel.setAttribute('aria-label', '模型与运行时设置')
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
      const target = document.createElement('div')
      panel.append(target)
      createApp(AndroidSetup).mount(target)
      mounted = true
    }
    panel.style.display = open ? 'block' : 'none'
    toggle.textContent = open ? '返回' : '设置'
  }
  toggle.addEventListener('click', () => setOpen(!open))
}

void boot()

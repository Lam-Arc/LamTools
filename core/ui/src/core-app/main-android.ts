import { createApp } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { createLamToolsRuntime, LamToolsApp } from '@/index.ts'
import { createIpcTransport } from '@/transport/ipcTransport.ts'

/**
 * Android entry point.
 *
 * Same components, same projection, same composer as desktop: `LamToolsApp` is the
 * application. The only difference is the pipe underneath, which is Tauri IPC because a
 * listening socket would reachable by every other app on the device.
 *
 * The one thing this file adds over the desktop entry is the boot step: the app has to
 * start its own Linux runtime and wait for the Python core inside it to answer. That is
 * why the sequence is explicit instead of "connect and render".
 *
 * There is deliberately no configuration screen here. Model providers and models are
 * managed in the shared settings surface, exactly as on desktop; a second form that wrote
 * the same files would be a second source of truth for one decision.
 */

const transport = createIpcTransport()

const capabilities = {
  // The picker bridge exists but nothing routes its answer yet, so attachments are
  // reported unavailable and the UI hides the affordance instead of failing on tap.
  filePicker: false,
  notifications: false,
  desktopWindow: false,
}

/** The boot screen. First launch unpacks a few hundred megabytes; a blank window there
 *  reads as a crash, so the wait gets one line of text and nothing else. */
function renderBoot(text: string, options: { error?: boolean; retry?: boolean } = {}): void {
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
  if (options.retry) {
    const button = document.createElement('button')
    button.type = 'button'
    button.textContent = '重试'
    button.style.cssText =
      'margin-top:18px;padding:11px 16px;border-radius:10px;border:1px solid #2f3540;background:#1b1f26;color:#e6e8eb;font:14px system-ui'
    button.addEventListener('click', () => window.location.reload())
    panel.append(document.createElement('br'), button)
  }
  node.append(panel)
}

async function boot(): Promise<void> {
  renderBoot('正在启动核心…\n\n首次打开需要解压随包的 Linux 运行时，可能要等一会儿。')
  try {
    await invoke('core_start')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    renderBoot(`核心启动失败。\n\n${message}`, { error: true, retry: true })
    return
  }

  const runtime = createLamToolsRuntime({
    transport,
    platform: 'mobile',
    capabilities,
  })
  await transport.connect()
  createApp(LamToolsApp, { runtime }).mount('#app')

  // A runtime that throws on first render must say why, not leave an empty dark window.
  window.addEventListener('error', (event) => {
    if (!document.getElementById('app')?.textContent?.trim()) {
      renderBoot(`界面加载失败。\n\n${event.message}`, { error: true, retry: true })
    }
  })
}

void boot()

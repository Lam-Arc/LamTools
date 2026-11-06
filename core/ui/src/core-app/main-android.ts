import { createApp } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { createLamToolsRuntime, LamToolsApp } from '@/index.ts'
import { createIpcTransport } from '@/transport/ipcTransport.ts'
import { createRemoteTransport } from '@/transport/remoteTransport.ts'
import { ensureRemote } from '@/app/remoteSession.ts'

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

// user:“手机仍可独立运行自己的本地 Core，两种模式可切换”+(宿主状态决定这一层用哪条
// 通道：连着电脑就用隧道，没连就用本机 Core 的 IPC。界面是同一套，不复制)。
const transport = createIpcTransport()

const capabilities: import('@/app/runtime.ts').RuntimeCapabilities = {
  // No DOM file input on Android: the answer comes from the system document picker.
  // `files.pickPaths` is the same contract desktop uses; the host copies the chosen
  // document into the guest's own directory and answers its in-guest path, which the
  // shared attachment code then registers with the Python core.
  // user:“使用 Android SAF 桥接现有 Python Core 附件接口”+(所以这里只提供路径来源；
  // 不虚报字节通道)。
  filePicker: false,
  notifications: false,
  desktopWindow: false,
  files: {
    async pickPaths(options: { source?: 'file' | 'photos' | 'camera'; multiple?: boolean; accept?: string } = {}) {
      // `multiple` is part of the shared contract but the Android picker always allows
      // several files, so it is not forwarded: an option that does nothing would be a
      // promise the platform cannot keep.
      const paths = await invoke<string[]>('pick_paths', {
        source: options.source ?? 'file',
        accept: options.accept ?? '',
      })
      return paths.length ? paths : null
    },
  },
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

// user:“重新安装你发的新安装包之后，这个问题仍旧存在”+(分屏几何存在 localStorage 里，
// 重装 APK 不清应用数据，所以坏状态会一直带下去；启动时直接丢掉它，让分屏回默认)。
function clearStaleSplitState(): void {
  try {
    const doomed: string[] = []
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (key && key.endsWith(':split-workspace')) doomed.push(key)
    }
    for (const key of doomed) localStorage.removeItem(key)
  } catch {
    // Storage unavailable: there is nothing stale to clear.
  }
}

async function boot(): Promise<void> {
  clearStaleSplitState()
  renderBoot('正在启动核心…\n\n首次打开需要解压随包的 Linux 运行时，可能要等一会儿。')
  try {
    await invoke('core_start')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    renderBoot(`核心启动失败。\n\n${message}`, { error: true, retry: true })
    return
  }

  // 已经连着电脑就整条走隧道；断了就用记住的票据重连一次；都不行才退回本机 Core。
  const peer = await ensureRemote()
  const activeTransport = peer === null ? transport : createRemoteTransport()
  if (peer !== null) capabilities.remote = { peer }
  const runtime = createLamToolsRuntime({
    transport: activeTransport,
    platform: 'mobile',
    capabilities,
  })
  await activeTransport.connect()
  // The window is edge to edge, so nothing resizes when the keyboard opens and nothing
  // reserves the status bar. The host publishes both heights; the shared layout already
  // reads these two variables, so there is no second layout engine here.
  // user:“内容没有为上方标题栏让位（会与手机上方的 bar 重叠）”+(状态栏那一截由宿主
  // 报上来，界面自己留位，不再压到系统栏下面)。
  const applyInsets = (payload: { keyboard?: unknown; top?: unknown } | undefined) => {
    const root = document.documentElement
    const height = Number(payload?.keyboard ?? 0)
    const top = Number(payload?.top ?? 0)
    if (!Number.isFinite(height) || height <= 0) root.style.removeProperty('--native-keyboard-inset')
    else root.style.setProperty('--native-keyboard-inset', `${height}px`)
    if (!Number.isFinite(top) || top <= 0) root.style.removeProperty('--native-safe-area-top')
    else root.style.setProperty('--native-safe-area-top', `${top}px`)
  }
  await listen<{ keyboard?: unknown; top?: unknown }>('insets', (event) => {
    applyInsets(event.payload)
  })

  // user:“大问题，返回不可用，我被困在设置页面了”+(系统返回键先问界面：界面能关掉
  // 当前整版视图就关，关不了才让宿主把任务放到后台。判断只有界面做得出来。
  await listen('back-request', () => {
    const handled = !window.dispatchEvent(new CustomEvent('sunday:back', { cancelable: true }))
    if (!handled) void invoke('app_background')
  })
  createApp(LamToolsApp, { runtime }).mount('#app')

  // A runtime that throws on first render must say why, not leave an empty dark window.
  window.addEventListener('error', (event) => {
    if (!document.getElementById('app')?.textContent?.trim()) {
      renderBoot(`界面加载失败。\n\n${event.message}`, { error: true, retry: true })
    }
  })
}

void boot()

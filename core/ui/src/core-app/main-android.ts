import { createApp } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import { createLamToolsRuntime, LamToolsApp } from '@/index.ts'
import { createIpcTransport } from '@/transport/ipcTransport.ts'
import { createRemoteTransport } from '@/transport/remoteTransport.ts'
import {
  activateDevice,
  ensureRemote,
  readDevices,
  remoteStatus,
} from '@/app/remoteSession.ts'
import type { RuntimeWorkspaceControl, RuntimeWorkspaceOption } from '@/app/runtime.ts'
import { ref } from 'vue'
import { bootScreen, type BootProgressPayload } from './bootScreen.ts'

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

/**
 * 设备切换：本机 + 配对过的电脑。
 *
 * user:“假如说我有多个设备，我该怎么切换呢？我怎么从控制电脑切回手机？”+(输入框上方那个
 * 设备菜单以前是空的，因为宿主从来没有提供工作环境选项；现在它列出本机和每一台配对的
 * 电脑，选一项就切过去，切回「本机」就是不再走隧道)。
 */
function createWorkspaceControl(activePeer: string | null): RuntimeWorkspaceControl {
  const options = ref<RuntimeWorkspaceOption[]>([
    { id: 'local', label: '本机', platform: 'android', deviceName: '这台手机' },
    ...readDevices().map((device) => ({
      id: device.id,
      label: device.name,
      platform: 'desktop',
      deviceName: device.name,
      online: Boolean(activePeer) && device.id === activePeer,
    })),
  ])
  const activeId = ref(activePeer ? activePeer : 'local')
  return {
    activeId,
    options,
    async select(id: string) {
      if (id === activeId.value) return
      activateDevice(id === 'local' ? null : id)
      // user:“我怎么从控制电脑切回手机”+(只清票据不够：宿主里的隧道还连着，重开之后
      // 又会按「已连接」走回电脑。切换必须先断掉现有隧道，再按新选择重开)。
      try {
        await invoke('p2p_disconnect')
      } catch {
        // 没有连接时这里是空操作，不影响切换。
      }
      window.location.reload()
    },
  }
}

/** A thrown value as text. `invoke` rejects with a string from the Rust side, and a
 *  non-Error object would otherwise render as "[object Object]" on the boot layer. */
function describeError(error: unknown): string {
  if (typeof error === 'string') return error
  if (error instanceof Error) return error.message
  return String(error)
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

/**
 * 给数据通道加一道闸。
 *
 * user:“进去的时候加载界面居然要加载 30 秒”“我定的要求是 5 秒以内”+(核心启动要几秒，
 * 界面不该干等它：先把界面挂出来，请求在这里排队，等核心能回答的那一刻再发出去)。
 */
function gateTransport<T extends object>(base: T, ready: Promise<unknown>): T {
  return new Proxy(base, {
    get(target, prop, receiver) {
      if (prop === 'request') {
        return async (...args: unknown[]) => {
          await ready.catch(() => undefined)
          const call = Reflect.get(target, prop) as (...a: unknown[]) => Promise<unknown>
          return call.apply(target, args)
        }
      }
      const value = Reflect.get(target, prop, receiver)
      return typeof value === 'function' ? (value as (...a: unknown[]) => unknown).bind(target) : value
    },
  })
}

/** The wait before the first paint, reported honestly.
 *
 *  user:“从点击图标到进入工作台，全程有反馈：原生窗口底色先挡住白闪，随后 HTML 启动层
 *  接管，显示品牌标记、动画和三阶段文字”+(这里就是「随后接管」：启动层挂在 #app 外面，
 *  Vue 挂载清不掉它，只有首屏真的有内容了才淡出)。 */
async function boot(): Promise<void> {
  clearStaleSplitState()
  const screen = bootScreen()
  // The first line is set before anything can fail, so the layer never shows a stale
  // default while the host is already working.
  screen.phase('staging', '正在准备启动环境…')

  // Registered before `core_start` on purpose: the first progress event is emitted
  // inside that command (staging, then the unpack), and a listener attached afterwards
  // would miss exactly the part this screen exists to report.
  try {
    await listen<BootProgressPayload>('runtime-progress', (event) => {
      screen.apply(event.payload)
    })
  } catch (error) {
    // A missing event bridge must not stop the app from starting; the phase text simply
    // stays where it is.
    console.warn('[sunday] boot: cannot listen for runtime-progress', describeError(error))
  }

  // 拨号和启动核心同时进行：连电脑要花的时间藏在核心启动里，不额外占用首屏。
  // user:“从点击这个应用到我进界面，我定的要求是 5 秒以内”+(所以这两件事不能排队)。
  // 后台拨号不占界面时间，预算给足；连上了再重开一次切过去。
  const remoteAttempt = ensureRemote(20_000)
  // 启动核心不再挡在挂载前面：核心慢几秒，界面就先出来，数据等它。
  const coreReady = invoke('core_start')
  coreReady.catch(() => undefined)


  try {
    screen.phase('ready', '正在加载界面…')

    // 已经连着电脑就整条走隧道；连着的时候上面那次拨号已经成功；连不上就从这里拿到
    // null，界面用本机 Core，不再等第二次。
    // user:“我定的要求是 5 秒以内”+(界面永远不等拨号：宿主要是已经连着电脑就整条走隧道，
    // 否则先用本机把界面挂出来，拨号在后台继续，连上了再重开一次切过去)。
    const knownRemote = await remoteStatus()
    const peer: string | null = knownRemote?.connected ? (knownRemote.peer ?? '') : null
    if (peer === null) {
      void remoteAttempt.then((late) => {
        if (!late) return
        try {
          if (performance.now() > 40_000) return
          if (sessionStorage.getItem('sunday.p2p.switched') === late) return
          sessionStorage.setItem('sunday.p2p.switched', late)
        } catch {
          return
        }
        window.location.reload()
      })
    }
    const activeTransport = peer === null ? gateTransport(transport, coreReady) : createRemoteTransport()
    if (peer !== null) capabilities.remote = { peer }
    const runtime = createLamToolsRuntime({
      transport: activeTransport,
      platform: 'mobile',
      capabilities,
      workspaceControl: createWorkspaceControl(peer),
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
    // The first publish happens in `MainActivity.onCreate`, before this listener exists.
    // Without this read the interface starts with an empty safe-area variable and lays
    // its top controls under the status bar or the notch.
    try {
      applyInsets(await invoke<{ keyboard?: unknown; top?: unknown }>('window_insets'))
    } catch (error) {
      console.warn('[sunday] insets: cannot read the first values', describeError(error))
    }

    // user:“大问题，返回不可用，我被困在设置页面了”+(系统返回键先问界面：界面能关掉
    // 当前整版视图就关，关不了才让宿主把任务放到后台。判断只有界面做得出来。
    await listen('back-request', () => {
      const handled = !window.dispatchEvent(new CustomEvent('sunday:back', { cancelable: true }))
      if (!handled) void invoke('app_background')
    })
    const app = createApp(LamToolsApp, { runtime })
    const reportPaintError = (message: string) => {
      if (!document.getElementById('app')?.textContent?.trim()) {
        screen.fail(`界面加载失败。

${message}`)
      }
    }
    // Registered before mount: an async render error after a successful mount would
    // otherwise only reach the console, and the boot layer would fade onto a blank page.
    window.addEventListener('error', (event) => reportPaintError(event.message))
    window.addEventListener('unhandledrejection', (event) => {
      const reason = event.reason
      reportPaintError(reason instanceof Error ? reason.message : String(reason))
    })
    app.config.errorHandler = (error) => {
      reportPaintError(error instanceof Error ? error.message : String(error))
    }
    app.mount('#app')

    // 核心要是启动失败，启动层还在就当场说明；已经淡出就在控制台留下原因，
    // 界面上的请求会各自报出自己拿到的那条错误。
    coreReady.catch((error) => {
      const message = `核心启动失败。

${describeError(error)}`
      if (screen.visible) screen.fail(message)
      else console.error('[sunday] boot:', message)
    })


    // Not awaited: the boot layer leaves when the interface has painted, and nothing
    // after this point should wait for a fade.
    void screen.reveal()
  } catch (error) {
    screen.fail(`界面启动失败。\n\n${describeError(error)}`)
  }
}

void boot()

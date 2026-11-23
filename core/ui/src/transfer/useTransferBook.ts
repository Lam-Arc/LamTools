/**
 * 互传名册的界面侧状态：一次取回、之后只收宿主推送。
 *
 * user:“进度优先使用现有事件/状态推送（宿主已有 p2p-status 推送），不要新增 3 秒轮询；
 * 界面不可见时停止动画”+(打开时取一次 `p2p_status` 对齐，之后只收宿主的 `p2p-state`：
 * 宿主 2 秒一拍、快照没变就什么都不发。页面不可见时连进度动画都停，后台不留空转)。
 *
 * `invoke` 与 `now` 都可注入：单测里不需要 Tauri 环境。
 */
import { onUnmounted, ref, watch, type Ref } from 'vue'
import { isFreshReceived, normalizeReceived, normalizeTransfers, type ReceivedRow, type TransferRow } from './shape'

export interface TransferBookOptions {
  /** 宿主命令通道；缺省时走 `@tauri-apps/api/core` 的 invoke。 */
  invoke?: (command: string, args?: Record<string, unknown>) => Promise<unknown>
  /** 注入「现在」（Unix 秒），用于「新收到的文件」提示；默认取系统时间。 */
  now?: () => number
  /** 注入可见性判断；默认读 document.visibilityState。 */
  visible?: () => boolean
  /** user:“交互测试”+(展厅不订阅真实宿主事件)。 */
  listenToHost?: boolean
}

export interface TransferBook {
  transfers: Ref<TransferRow[]>
  received: Ref<ReceivedRow[]>
  loading: Ref<boolean>
  error: Ref<string>
  /** 界面可见且确有在传：进度动画只在这时跑。 */
  animating: Ref<boolean>
  /** 打开面板之后新收到的文件（打「新」标）。 */
  fresh: (row: ReceivedRow) => boolean
  refresh: () => Promise<void>
  applySnapshot: (raw: unknown) => void
  cancel: (id: string) => Promise<void>
  reveal: (path: string) => Promise<void>
  attach: () => Promise<() => void>
}

async function defaultInvoke(command: string, args?: Record<string, unknown>): Promise<unknown> {
  const module = await import('@tauri-apps/api/core')
  return module.invoke(command, args)
}

export function useTransferBook(options: TransferBookOptions = {}): TransferBook {
  const transfers = ref<TransferRow[]>([])
  const received = ref<ReceivedRow[]>([])
  const loading = ref(false)
  const error = ref('')
  const animating = ref(false)
  // 打开这一刻之前收到的文件不算「新」：否则每次进面板都在闪「新」标。
  const since = (options.now ? options.now() : Math.floor(Date.now() / 1000))
  const visible = options.visible ?? (() => (typeof document === 'undefined' ? true : document.visibilityState !== 'hidden'))

  function syncAnimation(): void {
    animating.value = visible() && transfers.value.some((row) => row.active)
  }

  /** 一份快照（`p2p_status` 的答复或 `p2p-state` 的推送）落到界面。 */
  function applySnapshot(raw: unknown): void {
    const payload = (raw || {}) as { transfers?: unknown; received?: unknown }
    if ('transfers' in payload) transfers.value = normalizeTransfers(payload.transfers)
    if ('received' in payload) received.value = normalizeReceived(payload.received)
    syncAnimation()
  }

  async function invokeHost(command: string, args?: Record<string, unknown>): Promise<unknown> {
    const invoke = options.invoke ?? defaultInvoke
    return invoke(command, args)
  }

  /** 取一次完整状态：只在打开、切回窗口、手动刷新时发生，不做定时轮询。 */
  async function refresh(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      applySnapshot(await invokeHost('p2p_status'))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  /** 取消一条在传的传输：宿主负责让发送进程停下来。 */
  async function cancel(id: string): Promise<void> {
    if (!id) return
    try {
      await invokeHost('p2p_cancel_transfer', { id })
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return
    }
    await refresh()
  }

  /** 打开文件所在文件夹（宿主用系统文件管理器定位到它）。 */
  async function reveal(path: string): Promise<void> {
    if (!path) return
    try {
      await invokeHost('p2p_reveal_path', { path })
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  /**
   * 收宿主的推送。
   *
   * user:“进度优先使用现有事件/状态推送”+(`p2p-state` 是宿主唯一的状态推送：连接、设备、
   * 传输、已收到的文件都在同一份快照里，界面不需要第二套通道)。
   */
  async function attach(): Promise<() => void> {
    const unlisteners: Array<() => void> = []
    if (typeof document !== 'undefined') {
      const onVisibility = (): void => {
        syncAnimation()
        // 切回可见时对齐一次：不可见期间宿主可能攒了变化。
        if (visible()) void refresh()
      }
      document.addEventListener('visibilitychange', onVisibility)
      unlisteners.push(() => document.removeEventListener('visibilitychange', onVisibility))
    }
    if (options.listenToHost !== false) {
      try {
        const { listen } = await import('@tauri-apps/api/event')
        const unlisten = await listen('p2p-state', (event) => {
          applySnapshot(event.payload)
        })
        unlisteners.push(unlisten)
      } catch {
        // 没有推送时界面仍能靠手动刷新与切回窗口对齐；这里不静默失败成空列表。
      }
    }
    return () => {
      for (const off of unlisteners) {
        try {
          off()
        } catch {
          // 卸载阶段的失败无需上报。
        }
      }
    }
  }

  watch(transfers, syncAnimation, { deep: false })

  return {
    transfers,
    received,
    loading,
    error,
    animating,
    fresh: (row) => isFreshReceived(row, since),
    refresh,
    applySnapshot,
    cancel,
    reveal,
    attach,
  }
}

/** 组件里常用的写法：挂载时取一次 + 收推送，卸载时全部退订。 */
export function useTransferBookLifecycle(options: TransferBookOptions = {}): TransferBook {
  const book = useTransferBook(options)
  let detach: (() => void) | null = null
  let disposed = false
  void book.refresh()
  void book.attach().then((off) => {
    if (disposed) off()
    else detach = off
  })
  onUnmounted(() => {
    disposed = true
    detach?.()
    detach = null
  })
  return book
}

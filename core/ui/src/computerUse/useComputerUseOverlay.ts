/**
 * 主窗口里的 Computer Use 联动：只负责轮询任务状态、开合全屏覆盖层。
 *
 * user:“我不是说这个胶囊放在屏幕的最上方，紧贴屏幕上面吗？还有那个流光边框”+
 * (胶囊和 2px 流光属于整块屏幕，画在覆盖层窗口里；主窗口不再画任何可见元素，
 *  否则胶囊只能贴着应用窗口上沿，贴不到屏幕。)
 */
import { onBeforeUnmount, onMounted } from 'vue'

const POLL_INTERVAL_MS = 1500

let running = false

async function invokeTauri(command: string, args?: Record<string, unknown>): Promise<unknown> {
  const internals = (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  if (!internals) return null
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke(command, args)
}

async function apiBase(): Promise<string> {
  try {
    return (await invokeTauri('get_api_base')) as string
  } catch {
    return ''
  }
}

/** 任务在跑就保证覆盖层开着，任务没了就收掉。 */
async function syncOverlay(active: boolean): Promise<void> {
  if (active === running) return
  try {
    await invokeTauri(active ? 'computer_use_overlay_open' : 'computer_use_overlay_close')
    running = active
  } catch {
    // 桌面端不支持时静默跳过，下一次轮询再试。
  }
}

export function useComputerUseOverlay(): void {
  let timer: ReturnType<typeof setInterval> | null = null
  let base: string | null = null
  let disposed = false

  async function poll(): Promise<void> {
    if (disposed) return
    try {
      base ??= await apiBase()
      const response = await fetch(`${base}/api/core/computer-use/status`)
      if (!response.ok) return
      const data = (await response.json()) as { active?: boolean }
      await syncOverlay(Boolean(data?.active))
    } catch {
      // 后端还在启动或重启，保持上一次状态。
    }
  }

  onMounted(() => {
    void poll()
    timer = setInterval(() => void poll(), POLL_INTERVAL_MS)
  })

  onBeforeUnmount(() => {
    disposed = true
    if (timer !== null) clearInterval(timer)
  })
}

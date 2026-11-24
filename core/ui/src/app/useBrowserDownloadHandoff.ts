// user:“接管时把 Cookie 和 User-Agent 传给 aria2；接管失败要能退回浏览器直接下载”
// user:“下载进度不镜像本身就是反直觉且不原生，改掉”
// +(交给 EasyNet 的任务要和浏览器原生下载一样：有进度、有速度、能暂停继续取消、完成能打开)。
import type { UnlistenFn } from '@tauri-apps/api/event'
import {
  browserDownloadHeaders,
  browserDownloadRetry,
  browserDownloadTakeover,
  hasSplitNative,
  subscribeBrowserDownloadHeaders,
  subscribeBrowserDownloadRequests,
} from '@/split/native'

type RequestRpc = (method: string, params?: Record<string, unknown>) => Promise<unknown>
type Toast = (kind: 'notice' | 'error', text: string, duration?: number) => void

interface Headers {
  cookie: string
  userAgent: string
}

interface Tracked {
  tab: string
  filename: string
  directory: string
}

interface ProgressRow {
  gid: string
  tab: string
  filename: string
  status: string
  completed: number
  total: number
  speed: number
  errorText: string
  directory: string
}

const HEADER_WAIT_MS = 2500
const TICK_MS = 1500
const ACTIVE_STATES = new Set(['waiting', 'active', 'paused', 'recoverable'])

function message(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  if (typeof error === 'string' && error) return error
  return '未知错误'
}

export function useBrowserDownloadHandoff(options: { requestRpc: RequestRpc; toast: Toast }) {
  const pending = new Map<string, { resolve: (value: Headers | null) => void; timer: ReturnType<typeof setTimeout> }>()
  const stops: UnlistenFn[] = []
  const tracked = new Map<string, Tracked>()
  let ticker: ReturnType<typeof setInterval> | null = null
  let started = false

  const key = (tab: string, url: string) => `${tab}\u0000${url}`

  function settle(tab: string, url: string, headers: Headers | null) {
    const entry = pending.get(key(tab, url))
    if (!entry) return
    clearTimeout(entry.timer)
    pending.delete(key(tab, url))
    entry.resolve(headers)
  }

  function waitHeaders(tab: string, url: string): Promise<Headers | null> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        pending.delete(key(tab, url))
        resolve(null)
      }, HEADER_WAIT_MS)
      pending.set(key(tab, url), { resolve, timer })
    })
  }

  /** EasyNet 是否真的可用：不可用就关掉接管，浏览器完全退回原生下载。 */
  async function syncTakeover(): Promise<boolean> {
    if (!hasSplitNative()) return false
    let ready = false
    try {
      const listing = (await options.requestRpc('plugin.system.list', {})) as
        | { plugins?: Array<{ id?: string; name?: string; enabled?: boolean; available?: boolean; backend?: { state?: string } }> }
        | undefined
      const plugin = (listing?.plugins || []).find((row) => row.id === 'easynet' || row.name === 'easynet')
      ready = Boolean(plugin?.enabled && plugin?.available && plugin?.backend?.state === 'ready')
    } catch {
      ready = false
    }
    try {
      return await browserDownloadTakeover(ready)
    } catch {
      return false
    }
  }

  // ── 进度：只在有任务在跑的时候轮询，全部结束就停 ──────────────────
  async function pushProgress(): Promise<void> {
    if (!tracked.size) {
      stopTicker()
      return
    }
    let tasks: Array<Record<string, unknown>> = []
    try {
      const status = (await options.requestRpc('easynet.status', {})) as { downloads?: Array<Record<string, unknown>> } | undefined
      tasks = Array.isArray(status?.downloads) ? status!.downloads! : []
    } catch {
      // 插件暂时不可用：这一轮不更新，下一轮再试；不伪造进度。
      return
    }
    const rows: ProgressRow[] = []
    for (const [gid, meta] of tracked) {
      const task = tasks.find((row) => row?.gid === gid)
      if (!task) {
        rows.push({ gid, tab: meta.tab, filename: meta.filename, status: 'gone', completed: 0, total: 0, speed: 0, errorText: '', directory: meta.directory })
        continue
      }
      rows.push({
        gid,
        tab: meta.tab,
        filename: String(task.filename || meta.filename),
        status: String(task.status || ''),
        completed: Number(task.completedLength || 0),
        total: Number(task.totalLength || 0),
        speed: Number(task.downloadSpeed || 0),
        errorText: String(task.errorText || ''),
        directory: String(task.directory || meta.directory),
      })
      if (task.filename) meta.filename = String(task.filename)
      if (task.directory) meta.directory = String(task.directory)
    }
    window.dispatchEvent(new CustomEvent('sunday:easynet-download-progress', { detail: { tasks: rows } }))
    if (!rows.some((row) => ACTIVE_STATES.has(row.status))) stopTicker()
  }

  function startTicker() {
    if (ticker) return
    void pushProgress()
    ticker = setInterval(() => { void pushProgress() }, TICK_MS)
  }

  function stopTicker() {
    if (!ticker) return
    clearInterval(ticker)
    ticker = null
  }

  async function handoff(tab: string, url: string) {
    // 先挂等待，再发命令：命令的结果走事件回来，命令本身不阻塞。
    const waiting = waitHeaders(tab, url)
    try {
      await browserDownloadHeaders(tab, url)
    } catch {
      settle(tab, url, null)
    }
    const headers = await waiting
    const payload: Record<string, string> = {}
    if (headers?.cookie) payload.Cookie = headers.cookie
    if (headers?.userAgent) payload['User-Agent'] = headers.userAgent
    try {
      const result = (await options.requestRpc('easynet.transfer.add', {
        url,
        source: 'browser',
        headers: payload,
      })) as { gid?: string; filename?: string; directory?: string } | undefined
      const gid = String(result?.gid || '')
      if (gid) {
        tracked.set(gid, {
          tab,
          filename: String(result?.filename || url),
          directory: String(result?.directory || ''),
        })
        startTicker()
      }
      options.toast('notice', `已交给 EasyNet 下载：${result?.filename || url}`)
      window.dispatchEvent(
        new CustomEvent('sunday:easynet-download-added', {
          detail: { gid, filename: result?.filename || '', tab, url },
        }),
      )
    } catch (error) {
      // 接管没成功就让原生下载走一遍：用户至少还能拿到文件，并知道为什么换了通道。
      const reason = message(error)
      try {
        await browserDownloadRetry(tab, url)
        options.toast('error', `EasyNet 没接住这次下载，已改用浏览器直接下载：${reason}`)
      } catch {
        options.toast('error', `下载失败：${reason}`)
      }
    }
  }

  async function onAction(event: Event) {
    const detail = (event as CustomEvent<{ gid?: string; action?: string }>).detail
    const gid = String(detail?.gid || '')
    const action = String(detail?.action || '')
    if (!gid || !action) return
    try {
      await options.requestRpc('easynet.transfer.action', { gid, action })
    } catch (error) {
      options.toast('error', `操作没生效：${message(error)}`)
    }
    void pushProgress()
  }

  async function start(): Promise<void> {
    if (started || !hasSplitNative()) return
    started = true
    stops.push(await subscribeBrowserDownloadRequests(({ tab, url }) => { void handoff(tab, url) }))
    stops.push(await subscribeBrowserDownloadHeaders(({ tab, url, cookie, userAgent }) => {
      settle(tab, url, { cookie, userAgent })
    }))
    window.addEventListener('sunday:easynet-download-action', onAction)
    await syncTakeover()
  }

  function stop(): void {
    started = false
    window.removeEventListener('sunday:easynet-download-action', onAction)
    for (const entry of pending.values()) clearTimeout(entry.timer)
    pending.clear()
    stopTicker()
    for (const off of stops.splice(0)) off()
  }

  return { start, stop, syncTakeover }
}

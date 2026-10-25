/** bili-scroll 卡片墙：日报列表 + 判重近况（自绘 entry）。
 *
 * user:“它刷过的视频：卡片墙”+经宿主全局桥 window.LamToolsPluginRPC
 * 调插件自己的操作渲染；30 秒轮询刷新。
 */

type PluginRpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

declare global {
  interface Window {
    LamToolsPluginRPC?: PluginRpc
  }
}

interface ReportRow {
  file: string
  path: string
  bytes: number
}

interface SeenRow {
  bvid: string
  title?: string
  up?: string
  status?: string
  date?: string
}

const containers = document.querySelectorAll<HTMLElement>('[data-plugin-entry="bili-scroll"]')

function rpc(method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> {
  const bridge = window.LamToolsPluginRPC
  if (!bridge) throw new Error('宿主未就绪')
  return bridge(method, params)
}

function esc(value: string): string {
  const div = document.createElement('div')
  div.textContent = value
  return div.innerHTML
}

async function render(): Promise<void> {
  let reports: ReportRow[] = []
  let seen: SeenRow[] = []
  try {
    const listed = await rpc('bili-scroll.reports.list')
    reports = (listed.reports as ReportRow[]) || []
  } catch {
    /* 日报接口失败不阻断卡片墙 */
  }
  try {
    const brief = await rpc('bili-scroll.duty.brief')
    seen = (brief.seen_recent as SeenRow[]) || []
  } catch {
    /* 值班参数失败不阻断卡片墙 */
  }

  for (const container of containers) {
    const status = container.querySelector<HTMLElement>('[data-wall-status]')
    const list = container.querySelector<HTMLElement>('[data-wall-list]')
    if (status) {
      status.textContent = `日报 ${reports.length} 份 · 已看 ${seen.length} 条`
    }
    if (list) {
      const rows = seen
        .map((row) => {
          const badge =
            row.status === 'picked' ? '挑了' : row.status === 'commented' ? '评论' : '跳过'
          const link = `https://www.bilibili.com/video/${row.bvid}`
          return `<div class="bili-card"><strong>${esc(row.title || row.bvid)}</strong>` +
            `<span>${esc(row.up || '')} · ${badge}</span>` +
            `<a href="${link}" target="_blank" rel="noreferrer">${link}</a></div>`
        })
        .join('')
      list.innerHTML =
        rows ||
        '<div class="bili-card">还没有记录——先跑一轮值班。</div>'
    }
  }
}

function mount(): void {
  if (!containers.length) return
  for (const container of containers) {
    container.innerHTML =
      '<div data-wall-status class="bili-wall-status">加载中…</div>' +
      '<div data-wall-list class="bili-wall-list"></div>'
  }
  void render()
  window.setInterval(() => void render(), 30_000)
}

mount()

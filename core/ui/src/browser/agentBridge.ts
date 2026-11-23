// user:“让 Agent Loop 能直接调用：打开/切换标签、快照、点击、输入、等待、截图”+
// (工具在 Core 进程里，网页在桌面宿主的子 webview 里。这里把 Core 队列里的请求翻译成
// Tauri 命令执行，再把**结构化结果**写回队列：成功给 payload，失败给 {code,message}，
// 绝不静默——工具层超时会明确报 timeout)。
import { invoke } from '@tauri-apps/api/core'

/** 只转发这份白名单：Core 侧多写一个命令名也不会被执行。 */
const ALLOWED_COMMANDS = new Set([
  'browser_open',
  // user:“一次搜索只开一个标签”+(换引擎原地导航：这条命令之前没进白名单，
  // 结果第二台引擎直接报「宿主没有这个命令」，整次搜索退化成 web_fetch)。
  'browser_nav',
  'browser_tabs',
  'browser_activate',
  'browser_close',
  'browser_snapshot',
  'browser_act',
  'browser_wait_for',
  'browser_screenshot',
  'browser_control',
  // user:“以结构化数据作为 Agent 的主要输入”+(搜索适配器只借这一条：按选择器取回 DOM 片段，
  // 只读，不给网页侧增加任何能力)。
  'browser_html',
  // user:“把「截图/选中区域 → 提取文字」做通”+(截图取字也借这条队列，
  // 但执行的仍是宿主自己的 Tauri 命令 ocr_image，不新增通道)。
  'ocr_image',
])

const POLL_INTERVAL_MS = 200
// user:“每次搜索都会单独开一个分屏吗？”+
// (排查实测：某次 browser_open 的 invoke 一直不返回，drain 的串行锁就被它占住，
//  之后所有浏览器指令都撞「桌面应用没有响应」。给每条命令加硬超时：到点写回失败、
//  释放锁，通道能自愈——一次卡住不该让浏览器能力永久失效)。
const COMMAND_TIMEOUT_MS = 30000

interface AgentRequest {
  id: string
  command: string
  args: Record<string, unknown>
}

interface HostError {
  code: string
  message: string
  retriable?: boolean
}

function hasDesktop(): boolean {
  return typeof window !== 'undefined' && Boolean((window as unknown as Record<string, unknown>).__TAURI_INTERNALS__)
}

function normalizeError(thrown: unknown): HostError {
  if (thrown && typeof thrown === 'object') {
    const candidate = thrown as Record<string, unknown>
    if (typeof candidate.code === 'string') {
      return { code: candidate.code, message: String(candidate.message ?? ''), retriable: Boolean(candidate.retriable) }
    }
  }
  return { code: 'internal', message: String(thrown ?? '宿主没有说明原因') }
}

let apiBase: Promise<string> | null = null
let started = false
let draining = false

function base(): Promise<string> {
  if (!apiBase) apiBase = invoke<string>('get_api_base')
  return apiBase
}

async function postResult(id: string, ok: boolean, payload: unknown, error: HostError | null): Promise<void> {
  const origin = await base()
  await fetch(`${origin}/api/core/browser/agent/result`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, ok, payload, error }),
  })
}

async function runOne(origin: string, request: AgentRequest): Promise<void> {
  if (!ALLOWED_COMMANDS.has(request.command)) {
    await fetch(`${origin}/api/core/browser/agent/result`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: request.id,
        ok: false,
        error: { code: 'unsupported', message: `宿主没有这个命令：${request.command}` },
      }),
    })
    return
  }
  let ok = true
  let payload: unknown = null
  let error: HostError | null = null
  try {
    payload = await Promise.race([
      invoke(request.command, request.args ?? {}),
      new Promise<never>((_, reject) =>
        window.setTimeout(
          () => reject(new Error(`宿主执行超时（${COMMAND_TIMEOUT_MS}ms）：${request.command}`)),
          COMMAND_TIMEOUT_MS,
        ),
      ),
    ])
    // user:“第一次搜索建 agent-browser 分屏”+(Agent 从 Core 开的标签没有前端映射：
    // 在命令成功的这一刻告诉界面「这个原生标签是 Agent 的」，由工作区收养进 agent-browser 屏。
    // 用户自己开的标签不会经过这条通道，所以不存在误收养)。
    if (request.command === 'browser_open' && payload && typeof payload === 'object') {
      const tab = String((payload as Record<string, unknown>).tab ?? '')
      // 带上要打开的地址：空地址会让这块分屏先画出「首页」，看起来像没进网页。
      const url = String(((request.args ?? {}) as Record<string, unknown>).url ?? '')
      if (tab) window.dispatchEvent(new CustomEvent('sunday:browser-agent-tab', { detail: { tab, url } }))
    }
  } catch (thrown) {
    ok = false
    error = normalizeError(thrown)
  }
  await postResult(request.id, ok, payload, error)
}

async function drain(): Promise<void> {
  if (draining) return
  draining = true
  try {
    const origin = await base()
    const response = await fetch(`${origin}/api/core/browser/agent/pending`)
    if (!response.ok) return
    const body = (await response.json()) as { requests?: AgentRequest[] }
    for (const request of body.requests ?? []) {
      // 串行执行：同一个标签上的两条指令不能并发，否则点击顺序不可预期。
      await runOne(origin, request)
    }
  } finally {
    draining = false
  }
}

/**
 * 启动浏览器 Agent 通道的宿主侧执行器。返回停止函数。
 *
 * 只需要在主窗口里跑：子 webview（网页本身）永远拿不到 Tauri IPC，所以这条通道
 * 只存在于我们自己发起的 invoke 里。
 */
export function startBrowserAgentBridge(): () => void {
  if (started || !hasDesktop()) return () => {}
  started = true
  const timer = window.setInterval(() => {
    void drain().catch(() => {
      // Core 还没起来或暂时不可达：下一轮再试，不打扰用户。
    })
  }, POLL_INTERVAL_MS)
  return () => {
    window.clearInterval(timer)
    started = false
  }
}

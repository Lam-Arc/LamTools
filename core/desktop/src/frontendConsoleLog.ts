/**
 * Developer-mode console retention.
 *
 * WebView2 console output stays inside the webview: a frontend error was
 * invisible in the terminal and devtools had to be opened while it was still
 * on screen. In dev builds every console call, uncaught error and unhandled
 * rejection is batched and appended to `data/core-agent/frontend-console.log`
 * by the Rust shell, next to the backend log.
 *
 * 用户要求（原文）：“以后开发者模式，你把前端的 console 一块儿给留存下来。
 * 方便你随时查”
 */
import { invoke } from '@tauri-apps/api/core'

const FLUSH_MS = 400
const MAX_LINE_CHARS = 8_000
const MAX_BATCH_CHARS = 64 * 1024
const LEVELS = ['log', 'info', 'warn', 'error', 'debug', 'trace'] as const

let installed = false
let queue: string[] = []
let queuedChars = 0
let timer: ReturnType<typeof setTimeout> | null = null

function isDevBuild(): boolean {
  const env = (import.meta as unknown as { env?: { DEV?: boolean } }).env
  return env?.DEV === true
}

function describe(value: unknown, seen: WeakSet<object> = new WeakSet()): string {
  if (typeof value === 'string') return value
  if (value instanceof Error) {
    return value.stack ? `${value.name}: ${value.message}\n${value.stack}` : `${value.name}: ${value.message}`
  }
  if (typeof value === 'function') return `[Function ${value.name || 'anonymous'}]`
  if (typeof value === 'symbol' || typeof value === 'bigint') return String(value)
  if (!value || typeof value !== 'object') return String(value)
  if (seen.has(value)) return '[Circular]'
  // user:“修”+(根对象由 replacer 首次登记，避免普通对象被当成循环引用而丢失日志。)
  try {
    return JSON.stringify(value, (_key, item) => {
      if (typeof item === 'bigint') return String(item)
      if (item instanceof Error) return `${item.name}: ${item.message}`
      if (item && typeof item === 'object') {
        if (seen.has(item)) return '[Circular]'
        seen.add(item)
      }
      return item
    })
  } catch {
    return Object.prototype.toString.call(value)
  }
}

function truncate(line: string): string {
  return line.length > MAX_LINE_CHARS
    ? `${line.slice(0, MAX_LINE_CHARS)}…[truncated ${line.length - MAX_LINE_CHARS} chars]`
    : line
}

function scheduleFlush(): void {
  if (timer !== null) return
  timer = setTimeout(() => {
    timer = null
    void flush()
  }, FLUSH_MS)
}

async function flush(): Promise<void> {
  if (queue.length === 0) return
  const batch = queue
  queue = []
  queuedChars = 0
  try {
    await invoke('append_frontend_console', { lines: batch.join('\n') })
  } catch {
    // Logging must never break the app, and reporting the failure through
    // console would feed the same broken channel.
  }
}

function enqueue(level: string, args: unknown[]): void {
  const timestamp = new Date().toISOString()
  const line = truncate(`${timestamp} [${level}] ${args.map(arg => describe(arg)).join(' ')}`)
  queue.push(line)
  queuedChars += line.length
  if (queuedChars >= MAX_BATCH_CHARS) {
    void flush()
    return
  }
  scheduleFlush()
}

/** Install once; safe to call from non-Tauri dev builds (invoke rejects). */
export function installFrontendConsoleLog(): void {
  if (installed || !isDevBuild() || typeof window === 'undefined') return
  installed = true
  const target = console as unknown as Record<
    (typeof LEVELS)[number],
    (...args: unknown[]) => void
  >
  for (const level of LEVELS) {
    const original = target[level].bind(console)
    target[level] = (...args: unknown[]) => {
      original(...args)
      enqueue(level, args)
    }
  }
  window.addEventListener('error', (event) => {
    enqueue('error', [
      'Uncaught error:',
      event.error instanceof Error ? event.error : event.message,
      event.filename ? `at ${event.filename}:${event.lineno}:${event.colno}` : '',
    ])
  }, { capture: true })
  window.addEventListener('unhandledrejection', (event) => {
    enqueue('error', ['Unhandled rejection:', event.reason])
  })
  window.addEventListener('pagehide', () => {
    if (queue.length === 0) return
    const lines = queue.join('\n')
    queue = []
    queuedChars = 0
    void invoke('append_frontend_console', { lines }).catch(() => {})
  })
  enqueue('info', ['[frontend-console] developer console retention enabled'])
}

installFrontendConsoleLog()

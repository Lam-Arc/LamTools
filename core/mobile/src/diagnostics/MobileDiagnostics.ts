import type { RemoteDiagnosticEvent } from '../connection/TunnelTransport'

export const MOBILE_DIAGNOSTIC_RETENTION_LIMIT = 500
export const MOBILE_DIAGNOSTIC_EXPORT_LIMIT_BYTES = 256 * 1024
export const MOBILE_DIAGNOSTIC_FILE_NAME = 'sunday-mobile-diagnostics.json'

const TRANSPORT_EVENTS = new Set([
  'state',
  'frame_sent',
  'frame_receive_failed',
  'http_sent',
  'http_received',
  'rpc_sent',
  'rpc_received',
  'event_received',
  'socket_error',
  'socket_closed',
  'wire_message_failed',
])

const NATIVE_STAGES = new Set([
  'native_received',
  'native_registered',
  'native_project_ready',
  'native_hooks_ready',
  'native_mcp_start',
  'native_subagents_ready',
  'native_runtime_start',
  'native_runtime_done',
  'native_dreaming_done',
  'runtime_compaction_start',
  'runtime_compaction_done',
  'runtime_hooks_start',
  'runtime_hooks_done',
  'runtime_model_start',
  'runtime_model_done',
  'http_retry_wait',
  'http_send_start',
  'http_request_build_error',
  'http_request_built',
  'http_waiting_for_headers',
  'http_send_timeout',
  'http_connect_error',
  'http_send_task_panicked',
  'http_send_task_cancelled',
  'http_transport_error',
  'http_headers_received',
  'http_body_received',
  'http_provider_error',
  'http_streaming',
])

const FRAME_TYPES = new Set([
  'rpc.data',
  'http.request',
  'http.response',
  'http.cancel',
  'binary.data',
  'control.data',
  'event.data',
])
const STATES = new Set(['connecting', 'connected', 'reconnecting', 'disconnected', 'failed'])

export interface MobileDiagnosticEntry {
  at: string
  source: 'transport' | 'native'
  event: string
  frame_type?: string
  state?: string
  status?: number
  bytes?: number
  sequence?: number
  connection_generation?: number
  close_code?: number
  close_was_clean?: boolean
  error_kind?: 'aborted' | 'timeout' | 'network' | 'protocol' | 'unknown'
}

export interface MobileDiagnosticStagePayload {
  stage?: unknown
}

export interface MobileDiagnosticsOptions {
  now?: () => Date
  limit?: number
}

/** Payload-free, bounded diagnostics retained only for this WebView lifetime. */
export class MobileDiagnostics {
  private readonly entries: MobileDiagnosticEntry[] = []
  private readonly listeners = new Set<(entries: readonly MobileDiagnosticEntry[]) => void>()
  private readonly now: () => Date
  private readonly limit: number

  constructor(options: MobileDiagnosticsOptions = {}) {
    this.now = options.now || (() => new Date())
    const requestedLimit = options.limit
    this.limit = requestedLimit !== undefined && Number.isFinite(requestedLimit)
      ? Math.min(MOBILE_DIAGNOSTIC_RETENTION_LIMIT, Math.max(1, Math.floor(requestedLimit)))
      : MOBILE_DIAGNOSTIC_RETENTION_LIMIT
  }

  recordTransport(event: RemoteDiagnosticEvent): void {
    if (event.component !== 'mobile' || !TRANSPORT_EVENTS.has(event.event)) return
    const entry: MobileDiagnosticEntry = {
      at: this.now().toISOString(),
      source: 'transport',
      event: event.event,
    }
    if (event.frame_type && FRAME_TYPES.has(event.frame_type)) entry.frame_type = event.frame_type
    if (event.state && STATES.has(event.state)) entry.state = event.state
    assignSafeNumber(entry, 'status', event.status, 0, 599)
    assignSafeNumber(entry, 'bytes', event.bytes, 0, 256 * 1024 * 1024)
    assignSafeNumber(entry, 'sequence', event.sequence, 0, Number.MAX_SAFE_INTEGER)
    assignSafeNumber(entry, 'connection_generation', event.connection_generation, 0, Number.MAX_SAFE_INTEGER)
    assignSafeNumber(entry, 'close_code', event.close_code, 0, 65535)
    if (typeof event.close_was_clean === 'boolean') entry.close_was_clean = event.close_was_clean
    const errorKind = classifyError(event.error)
    if (errorKind) entry.error_kind = errorKind
    this.push(entry)
  }

  recordNativeStage(payload: unknown): void {
    if (!isRecord(payload) || typeof payload.stage !== 'string' || !NATIVE_STAGES.has(payload.stage)) return
    this.push({
      at: this.now().toISOString(),
      source: 'native',
      event: payload.stage,
    })
  }

  subscribe(listener: (entries: readonly MobileDiagnosticEntry[]) => void): () => void {
    this.listeners.add(listener)
    listener(this.snapshot())
    return () => this.listeners.delete(listener)
  }

  snapshot(): MobileDiagnosticEntry[] {
    return this.entries.map(entry => ({ ...entry }))
  }

  clear(): void {
    this.entries.length = 0
    this.notify()
  }

  serialize(): string {
    const header = {
      schema: 'lamtools.mobile-diagnostics',
      version: 1,
      exported_at: this.now().toISOString(),
      retention: '采集记录仅保存在当前应用运行期间的内存中；页面或应用重新载入后清空。Android 分享时会在应用缓存生成临时副本，下次导出覆盖该副本，系统清理应用缓存时删除。',
      redaction: '不包含对话或文件内容、凭据、网络地址、方法名、原始错误文本、请求 ID、运行 ID 或设备 ID。',
      entries: this.snapshot(),
    }
    const output = `${JSON.stringify(header, null, 2)}\n`
    if (utf8Length(output) > MOBILE_DIAGNOSTIC_EXPORT_LIMIT_BYTES) {
      // Each entry contains only short allowlisted fields. This guard is an
      // additional bound in case a future schema change violates that rule.
      throw new Error('诊断日志超出可导出大小上限')
    }
    return output
  }

  private push(entry: MobileDiagnosticEntry): void {
    this.entries.push(entry)
    if (this.entries.length > this.limit) this.entries.splice(0, this.entries.length - this.limit)
    this.notify()
  }

  private notify(): void {
    const entries = this.snapshot()
    for (const listener of this.listeners) {
      try {
        listener(entries)
      } catch {
        // Diagnostic observers must never interfere with transport behavior.
      }
    }
  }
}

function assignSafeNumber<K extends 'status' | 'bytes' | 'sequence' | 'connection_generation' | 'close_code'>(
  entry: MobileDiagnosticEntry,
  key: K,
  value: unknown,
  min: number,
  max: number,
): void {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) return
  entry[key] = value
}

function classifyError(value: unknown): MobileDiagnosticEntry['error_kind'] | undefined {
  if (typeof value !== 'string' || !value) return undefined
  const text = value.slice(0, 512).toLowerCase()
  if (text.includes('abort') || text.includes('cancel')) return 'aborted'
  if (text.includes('timeout') || text.includes('timed out')) return 'timeout'
  if (text.includes('network') || text.includes('socket') || text.includes('connect')) return 'network'
  if (text.includes('protocol') || text.includes('frame') || text.includes('decrypt')) return 'protocol'
  return 'unknown'
}

function utf8Length(value: string): number {
  return new TextEncoder().encode(value).byteLength
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

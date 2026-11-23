/**
 * 把宿主给的互传名册整理成界面能直接画的行。
 *
 * user:“传输面板：在「远程连接」面板或文件屏里列出 transfers[]（方向、文件名、进度、状态），
 * 支持取消；失败可重试；完成后可「打开所在文件夹」”+(宿主只转述传输进程说过的事实
 * （`p2p_status.transfers[]` / `received[]`），这里负责三件确定的事：字段类型收窄、
 * 百分比自洽（缺了就用字节算，越界就夹住）、顺序（在传的在前，同组新的在前）)。
 *
 * 纯函数：不碰 DOM、不发请求，单测里零替身即可验证。
 */
import { t } from '@/i18n/index.ts'
import { baseName } from '@/preview/route'

/** 本端视角的方向。 */
export type TransferDirection = 'send' | 'receive'

/** 传输层给的五个稳定状态词（`transfer.rs` 的 `Progress.state`）。 */
export type TransferState = 'offered' | 'transferring' | 'completed' | 'failed' | 'cancelled'

/** 一行传输。字段与宿主 `p2p_status.transfers[]` 对齐，只做收窄与派生。 */
export interface TransferRow {
  id: string
  direction: TransferDirection
  name: string
  total: number
  transferred: number
  /** 0–100 的整数，界面直接绑宽度。 */
  percent: number
  state: TransferState
  code: string
  message: string
  /** 接收端落盘路径（完成时才有），用于「打开所在文件夹」。 */
  path: string
  /** 本机源文件绝对路径（本端发起的传输才有）：重试时直接再发它。 */
  source: string
  /** 还在传（占着进度动画与取消按钮）。 */
  active: boolean
  /** 失败/取消之后还能再发一次（只有发送侧能重试，接收侧重试没有意义）。 */
  retryable: boolean
}

/** 一条已落盘的文件。字段与宿主 `p2p_status.received[]` 对齐。 */
export interface ReceivedRow {
  transferId: string
  path: string
  name: string
  size: number
  /** 对端设备名。 */
  peer: string
  /** 对端自己报的来源（手机/电脑）。 */
  from: string
  /** 落盘时间（Unix 秒）。 */
  at: number
}

const ACTIVE_STATES = new Set<TransferState>(['offered', 'transferring'])
const STATES = new Set<string>(['offered', 'transferring', 'completed', 'failed', 'cancelled'])

/** 未知状态一律按失败看待：宁可显示「出错了」也不要假装成还在传。 */
function stateOf(raw: unknown): TransferState {
  const value = typeof raw === 'string' ? raw.trim() : ''
  return (STATES.has(value) ? value : 'failed') as TransferState
}

function directionOf(raw: unknown): TransferDirection {
  return raw === 'receive' ? 'receive' : 'send'
}

function numberOr(raw: unknown, fallback = 0): number {
  const value = typeof raw === 'number' ? raw : Number(raw)
  return Number.isFinite(value) && value >= 0 ? Math.floor(value) : fallback
}

function textOf(raw: unknown): string {
  return typeof raw === 'string' ? raw : ''
}

/** 百分比自洽：宿主给了可信的数就用它，否则按字节算；一律夹在 0–100。 */
function percentOf(rawPercent: unknown, transferred: number, total: number, state: TransferState): number {
  const given = typeof rawPercent === 'number' ? rawPercent : Number(rawPercent)
  if (Number.isFinite(given) && given >= 0 && given <= 100) return Math.floor(given)
  if (total <= 0) return state === 'completed' ? 100 : 0
  return Math.min(100, Math.floor((transferred * 100) / total))
}

/**
 * transfers[] → 界面行。
 *
 * user:“支持取消；失败可重试；完成后可「打开所在文件夹」”+(所以每行都带 `active`/
 * `retryable`/`path` 三个判定结果，组件里不再重复判断)。
 */
export function normalizeTransfers(raw: unknown): TransferRow[] {
  if (!Array.isArray(raw)) return []
  const rows: TransferRow[] = []
  raw.forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const entry = item as Record<string, unknown>
    const id = textOf(entry.id) || textOf(entry.transferId) || 't-' + index
    const state = stateOf(entry.state)
    const total = numberOr(entry.total)
    const transferred = Math.min(numberOr(entry.transferred), total > 0 ? total : Number.MAX_SAFE_INTEGER)
    const direction = directionOf(entry.direction)
    const code = textOf(entry.code)
    rows.push({
      id,
      direction,
      name: textOf(entry.name) || t('未命名文件'),
      total,
      transferred,
      percent: percentOf(entry.percent, transferred, total, state),
      state,
      code,
      message: textOf(entry.message),
      path: textOf(entry.path),
      source: textOf(entry.source),
      active: ACTIVE_STATES.has(state),
      // 只有「本端发出去的、已经停下来的」才有重试的意义：接收侧重试等于让对方重发。
      retryable: direction === 'send' && (state === 'failed' || state === 'cancelled'),
    })
  })
  // 在传的在前；同一组内新的在前（宿主按时间追加，所以反转即最新优先）。
  const active = rows.filter((row) => row.active).reverse()
  const finished = rows.filter((row) => !row.active).reverse()
  return [...active, ...finished]
}

/** received[] → 界面行；没有路径的条目没有可做的动作，直接丢掉。 */
export function normalizeReceived(raw: unknown): ReceivedRow[] {
  if (!Array.isArray(raw)) return []
  const rows: ReceivedRow[] = []
  raw.forEach((item, index) => {
    if (!item || typeof item !== 'object') return
    const entry = item as Record<string, unknown>
    const path = textOf(entry.path)
    if (!path) return
    rows.push({
      transferId: textOf(entry.transferId) || textOf(entry.id) || 'r-' + index,
      path,
      name: textOf(entry.name) || baseName(path) || t('未命名文件'),
      size: numberOr(entry.size),
      peer: textOf(entry.peer),
      from: textOf(entry.from),
      at: numberOr(entry.at),
    })
  })
  return rows
}

/** 这份名册里还有没有正在传的东西（界面据此决定要不要开动画）。 */
export function hasActiveTransfer(rows: TransferRow[]): boolean {
  return rows.some((row) => row.active)
}

/** 字节数说人话：12 B / 340 KB / 12.4 MB / 1.2 GB。 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  const shown = unit === 0 ? String(Math.round(value)) : value.toFixed(value >= 100 ? 0 : 1)
  return shown + ' ' + units[unit]
}

/** 「1.2 MB / 240 MB」这种文案：进度条旁边的第二行。 */
export function progressText(row: Pick<TransferRow, 'transferred' | 'total'>): string {
  return formatBytes(row.transferred) + ' / ' + formatBytes(row.total)
}

/** 状态词 → 中文标签（传输层不解析中文，界面也不猜传输层）。 */
export function transferStateLabel(state: TransferState): string {
  if (state === 'offered') return t('等待对方接受')
  if (state === 'transferring') return t('传输中')
  if (state === 'completed') return t('已完成')
  if (state === 'cancelled') return t('已取消')
  return t('失败')
}

/** 方向 → 中文标签。 */
export function transferDirectionLabel(direction: TransferDirection): string {
  return direction === 'receive' ? t('接收') : t('发送')
}

/** 这条落盘文件是不是「这次打开面板之后新收到的」：用来打「新」标。 */
export function isFreshReceived(row: Pick<ReceivedRow, 'at'>, sinceSeconds: number): boolean {
  return row.at > 0 && row.at > sinceSeconds
}

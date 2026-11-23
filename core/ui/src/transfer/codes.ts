/**
 * 传输错误码 → 中文人话。
 *
 * user:“文案与错误码一一对应（把 file_* 映射成中文人话），i18n 四语言同步”+(传输层给的是
 * 稳定码（`core/p2p/src/transfer.rs` 的 `CODE_*` 常量），界面绝不按中文分支、也不自己
 * 拼一句「传失败了」；每一码都有唯一一句话，未知码退回通用原因，但不吞掉传输层给的原文)。
 *
 * 这一层是纯映射：不碰 DOM、不发请求，单测里零替身即可验证。
 */
import { t } from '@/i18n/index.ts'

/** 传输层定义的全部错误码（顺序与 `transfer.rs` 一致，便于对照）。 */
export const TRANSFER_CODES = [
  'file_untrusted',
  'file_bad_name',
  'file_bad_request',
  'file_too_large',
  'file_not_found',
  'file_busy',
  'file_disk_error',
  'file_size_mismatch',
  'file_timeout',
  'file_cancelled',
  'file_peer_error',
] as const

export type TransferCode = typeof TRANSFER_CODES[number]

/** 这句话该用什么语气显示：取消是正常结局，忙/超时是「等一下再试」，其余是失败。 */
export type TransferErrorTone = 'error' | 'warn' | 'info'

const TEXTS: Record<string, string> = {
  file_untrusted: '对方不在可信设备名单里，可能已被撤销授权。重新配对后再发送。',
  file_bad_name: '文件名不合法（空名、包含 .. 或系统保留名），换一个名字再发。',
  file_bad_request: '传输参数不符合约定（块序号或块大小不对），这一次已被丢弃。',
  file_too_large: '文件超过单文件 8 GiB 上限，请先分割再发。',
  file_not_found: '这次传输已经不在进行中（可能已过期或已被取消）。',
  file_busy: '同时在传的文件太多，等这一批传完再发。',
  file_disk_error: '写盘失败：对方磁盘已满，或接收目录不可写。',
  file_size_mismatch: '收发字节数与约定不一致，文件不完整，已丢弃。',
  file_timeout: '长时间没有新数据，传输已中断。',
  file_cancelled: '传输已取消。',
  file_peer_error: '对方拒绝了这次传输。',
}

const TONES: Record<string, TransferErrorTone> = {
  file_cancelled: 'info',
  file_busy: 'warn',
  file_timeout: 'warn',
}

const UNKNOWN = '传输出错，稍后可以重试。'

/** 这一码有没有对应的中文文案（界面据此决定「显示原因」还是「显示原文」）。 */
export function isKnownTransferCode(code: string): boolean {
  return Object.hasOwn(TEXTS, code)
}

/** 一句给人看的原因：已知码走映射，未知码带上传输层的原文，绝不静默。 */
export function transferErrorText(code: string, message = ''): string {
  const known = TEXTS[(code || '').trim()]
  if (known) return t(known)
  const raw = (message || '').trim()
  if (raw) return t(UNKNOWN) + '（' + raw + '）'
  return t(UNKNOWN)
}

/** 这句话的语气（取消不算失败，界面不该标红）。 */
export function transferErrorTone(code: string): TransferErrorTone {
  return TONES[(code || '').trim()] || 'error'
}

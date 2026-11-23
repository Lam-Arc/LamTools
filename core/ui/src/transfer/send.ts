/**
 * 发送资格：能不能把这个文件发给这台设备。
 *
 * user:“发送入口：列出已信任设备（含在线状态与直连/中继），选中后开始传输；对端离线/未配对
 * 给可读原因，不要静默失败”+(每一个会被禁用的按钮都要带着理由，界面不需要自己猜为什么点不动；
 * 判断集中在这一个纯函数里，「通道直连还是中继」只是提示，不参与拦截)。
 *
 * 纯函数：不碰 DOM、不发请求，单测里零替身即可验证。
 */
import { t } from '@/i18n/index.ts'
import { isAbsolutePath } from './received'

/** 单文件上限：与 `core/p2p/src/transfer.rs` 的 `MAX_FILE_BYTES` 一致（8 GiB）。 */
export const MAX_TRANSFER_BYTES = 8 * 1024 * 1024 * 1024

/** 一台可选的接收方。`online`/`path` 来自宿主的在线名册，`trusted` 来自可信名单。 */
export interface TransferTarget {
  id: string
  name: string
  /** 在可信名单里（配过对、或已被允许）。 */
  trusted: boolean
  /** 此刻在线（宿主 devices[] 里有它）。 */
  online: boolean
  /** 当前这台设备走的是直连还是中继；unknown 表示还在判定。 */
  path: 'direct' | 'relay' | 'unknown'
  /**
   * 本机握着它的地址票（配对时记下）。票在界面这边，宿主不知道对方是谁。
   * 缺省视为有票（老调用点不必改）。
   */
  hasTicket?: boolean
}

/** 要发的东西：路径 + 大小（大小未知时传 0，不做上限拦截）。 */
export interface TransferPayload {
  path: string
  size?: number
}

export interface SendEligibility {
  /** 能不能发。 */
  allowed: boolean
  /** 不能发时的一句话原因（能发时为空串）。 */
  reason: string
  /** 能发但需要提醒的情况（例如走中继、文件很大），不改按钮状态。 */
  warning: string
}

/** 在线状态与通道的中文说法。 */
export function targetPathLabel(path: TransferTarget['path']): string {
  if (path === 'direct') return t('直连')
  if (path === 'relay') return t('经中继')
  return t('正在判定')
}

/** 设备行的一句话副标题：在线/离线 + 通道。 */
export function targetSubtitle(target: TransferTarget): string {
  if (!target.trusted) return t('未配对 · 先在这台设备上扫码配对')
  if (!target.online) return t('离线 · 打开对方设备上的远程连接后再发')
  return t('在线 · {0}', { 0: targetPathLabel(target.path) })
}

const BIG_FILE = 1024 * 1024 * 1024

/**
 * 一次发送的资格判定，按「用户先遇到什么」排序：文件本身不合法 > 设备不可用 > 提醒。
 *
 * user:“对端离线/未配对给可读原因，不要静默失败”+(所以每一处 return 都带 reason，
 * 调用方只负责把它显示出来，不再补词)。
 */
export function sendEligibility(target: TransferTarget | null | undefined, payload: TransferPayload): SendEligibility {
  const path = (payload.path || '').trim()
  if (!path) return { allowed: false, reason: t('没有选中文件。'), warning: '' }
  if (!isAbsolutePath(path)) {
    // 远程会话里的路径可能属于对方机器：本机打不开也就发不出去。
    return { allowed: false, reason: t('只支持发送本机文件，这个路径在本机打不开。'), warning: '' }
  }
  const size = typeof payload.size === 'number' && payload.size > 0 ? payload.size : 0
  if (size > MAX_TRANSFER_BYTES) {
    return { allowed: false, reason: t('文件超过单文件 8 GiB 上限，请先分割。'), warning: '' }
  }
  if (!target) return { allowed: false, reason: t('还没有可选设备。'), warning: '' }
  if (!target.trusted) {
    return { allowed: false, reason: t('这台设备还没配对，不能接收文件。'), warning: '' }
  }
  if (!target.online) {
    return { allowed: false, reason: t('这台设备当前离线，等它连上再发。'), warning: '' }
  }
  if (target.hasTicket === false) {
    // 名单里有它、也真的在线，但本机没有可拨的票：诚实说明要重扫，而不是发出去再失败。
    return { allowed: false, reason: t('这台设备没有地址票，先在「设备连接」里重新扫码配对。'), warning: '' }
  }
  const warning = size >= BIG_FILE
    ? t('文件较大，传输期间保持两台设备都在线。')
    : target.path === 'relay'
      ? t('这次走中继，速度会慢一些。')
      : ''
  return { allowed: true, reason: '', warning }
}

/**
 * 把「可信名单」与「在线名册」合成可选列表。
 *
 * user:“列出已信任设备（含在线状态与直连/中继）”+(可信名单是权威（谁允许收），
 * 在线名册是事实（谁现在连得上）；两边任一为真的设备都要出现，不能让用户找不到它)。
 * `hasTicket` 传进来时顺手标出「本机有没有它的票」——票在界面这边，宿主不知道。
 */
export function mergeTransferTargets(
  trusted: Array<{ id?: unknown; name?: unknown }>,
  online: Array<{ id?: unknown; name?: unknown; path?: unknown }>,
  hasTicket?: (id: string) => boolean,
): TransferTarget[] {
  const seen = new Map<string, TransferTarget>()
  const readId = (value: unknown) => (typeof value === 'string' ? value.trim() : '')
  const readName = (value: unknown) => (typeof value === 'string' ? value.trim() : '')
  for (const device of trusted) {
    const id = readId(device?.id)
    if (!id) continue
    seen.set(id, { id, name: readName(device?.name) || id.slice(0, 8), trusted: true, online: false, path: 'unknown' })
  }
  for (const device of online) {
    const id = readId(device?.id)
    if (!id) continue
    const name = readName(device?.name)
    const path = device?.path === 'direct' || device?.path === 'relay' ? device.path : 'unknown'
    const existing = seen.get(id)
    if (existing) {
      existing.online = true
      existing.path = path
      if (name) existing.name = name
    } else {
      // 在线但不在可信名单：多半是刚扫码还没落名单，照样列出来，但标记为不可发。
      seen.set(id, { id, name: name || id.slice(0, 8), trusted: false, online: true, path })
    }
  }
  // 能发的排前面，其次在线的，最后按名字稳定排列。
  const order = (target: TransferTarget) => (target.trusted && target.online ? 0 : target.trusted ? 1 : 2)
  const targets = [...seen.values()].sort((a, b) => order(a) - order(b) || a.name.localeCompare(b.name))
  // 票在界面这边：不传判定函数就当作「不关心」，保持老行为。
  return hasTicket ? targets.map((target) => ({ ...target, hasTicket: hasTicket(target.id) })) : targets
}

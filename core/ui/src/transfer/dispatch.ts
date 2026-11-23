/**
 * 发起一次互传：谁能收、用哪张票、命令叫什么。
 *
 * user:“发送入口：…选中后开始传输；对端离线/未配对给可读原因，不要静默失败”+
 * (桌面宿主不链 `sunday-p2p` crate（iroh 的 windows 依赖与桌面冲突），发送是让宿主起一个
 * `sunday-p2p send` 进程；因此界面必须把「对方的地址票」一起交出去——票只存在界面这边
 * （配对时记在 localStorage），宿主不知道它是谁)。
 *
 * 纯逻辑部分（选票、拼命令参数）都可单测；只有真正调用宿主时才有副作用。
 */
import { t } from '@/i18n/index.ts'
import type { PairedDevice } from '@/app/remoteSession.ts'
import { sendEligibility, type TransferPayload, type TransferTarget } from './send'

/** 一次发送要交给宿主的全部参数。 */
export interface SendRequest {
  /** 本机源文件绝对路径。 */
  path: string
  /** 对端显示用的文件名（可空，宿主按路径取名）。 */
  name?: string
  /** 对方的地址票（`sunday1:`）。 */
  ticket: string
}

/** 从记住的设备里取地址票：票是发送方拨号的唯一凭据。 */
export function ticketForDevice(devices: PairedDevice[], id: string): string {
  if (!id) return ''
  return devices.find((device) => device.id === id)?.ticket || ''
}

/** 这台设备能不能作为接收方：资格 + 本机是否握着它的票。 */
export function sendTargetReason(target: TransferTarget, payload: TransferPayload, ticket: string): string {
  const verdict = sendEligibility(target, payload)
  if (!verdict.allowed) return verdict.reason
  if (!ticket) {
    // 名单里有它、也真的在线，但本机没有可拨的票：诚实说明要重扫，而不是发出去再失败。
    return t('这台设备没有地址票，先在「设备连接」里重新扫码配对。')
  }
  return ''
}

/** 发送命令的参数：宿主据此起 `sunday-p2p send`。 */
export function sendArgs(request: SendRequest): Record<string, unknown> {
  const args: Record<string, unknown> = { path: request.path, ticket: request.ticket }
  const name = (request.name || '').trim()
  if (name) args.name = name
  return args
}

/**
 * 真正把请求交给宿主。
 *
 * user:“选中后开始传输”+(返回宿主给的 transferId，界面用它把这一行和源文件绑起来，
 * 失败之后才知道该重发哪一个)。
 */
export async function sendFileToDevice(
  invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>,
  request: SendRequest,
): Promise<{ transferId: string; name: string }> {
  const result = (await invoke('p2p_send_file', sendArgs(request))) as
    | { transferId?: unknown; name?: unknown; started?: unknown; reason?: unknown }
    | null
  const transferId = typeof result?.transferId === 'string' ? result.transferId : ''
  if (result && result.started === false) {
    const reason = typeof result.reason === 'string' && result.reason ? result.reason : t('发送没有开始。')
    throw new Error(t('发送没有开始：{0}', { 0: reason }))
  }
  return { transferId, name: typeof result?.name === 'string' ? result.name : (request.name || '') }
}

/** 当前窗口记住的「传输 id → 本机源文件」，面板据此决定重试能不能点。 */
export function rememberSendSource(sources: Record<string, string>, transferId: string, path: string): Record<string, string> {
  if (!transferId || !path) return sources
  return { ...sources, [transferId]: path }
}

/**
 * 本窗口所有发送入口共用的一张登记表：传输 id → 本机源文件。
 *
 * user:“失败可重试”+(源文件路径只有发起方知道，而发起可能是资料库、预览器或设备页；
 * 如果每个入口各记各的，面板就只知道设备页发出去的那几条。这里收成一张窗口级表，
 * 面板按它补上宿主没带回来的 source)。
 */
const WINDOW_SOURCES: Record<string, string> = {}

/** 记下一次发送（就地写入共享表），返回同一张表方便调用方直接绑定。 */
export function trackSendSource(transferId: string, path: string): Record<string, string> {
  if (!transferId || !path) return WINDOW_SOURCES
  WINDOW_SOURCES[transferId] = path
  return WINDOW_SOURCES
}

/** 面板取共享登记表（只读语义：不要直接改它，改走 trackSendSource）。 */
export function windowSendSources(): Record<string, string> {
  return WINDOW_SOURCES
}

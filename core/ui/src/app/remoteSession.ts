import { invoke } from '@tauri-apps/api/core'

/**
 * The one remembered pairing on this device.
 *
 * user:“自动发现与重连，网络切换后尽可能恢复连接及会话状态”+(票据记住一次，之后开机
 * 自动重连；连不上就老实回到本机 Core，不把界面卡在一个死掉的通道上)。
 */
const TICKET_KEY = 'sunday.p2p.ticket'

export function readTicket(): string {
  try {
    return localStorage.getItem(TICKET_KEY) || ''
  } catch {
    return ''
  }
}

export function saveTicket(ticket: string): void {
  try {
    if (ticket) localStorage.setItem(TICKET_KEY, ticket)
    else localStorage.removeItem(TICKET_KEY)
  } catch {
    // Storage unavailable: this session still works, only the auto-reconnect is lost.
  }
}

interface Status {
  connected?: boolean
  /** 正在拨号：宿主的 inner 锁被这次拨号占着，此时还没有可用隧道。 */
  connecting?: boolean
  peer?: string | null
}

export async function remoteStatus(): Promise<Status | null> {
  try {
    return (await invoke('p2p_status')) as Status
  } catch {
    return null
  }
}

/**
 * Makes sure the tunnel is up, re-dialing the remembered ticket when it is not.
 *
 * Returns the peer id when connected. The host keeps the connection for the whole process,
 * so a reconnect here also restores what the interface was doing: the same Core, the same
 * threads, the same events.
 */
export async function ensureRemote(budgetMs = 5000): Promise<string | null> {
  const status = await remoteStatus()
  if (status?.connected && !status.connecting) return status.peer ?? ''
  // user:“类似的时序问题不要再犯，检查”+(拨号中以前答「已连接」，界面拿着还没建好的
  // 隧道去读项目与模型，读一次空一次；现在如实报「正在连接」，这里等这一次的结果，
  // 而不是再拨一次把这一次顶掉)。
  if (status?.connecting) return await waitForTunnel(budgetMs)
  const ticket = readTicket()
  if (!ticket) return null
  try {
    // user:“进去的时候加载界面居然要加载 30 秒”+(记住的电脑不在线时，以前要等满
    // 45 秒的拨号超时才肯落到本机；启动路径只给它一个很短的预算，超时立刻用本机)。
    const args: Record<string, unknown> = { ticket, name: 'Phone', timeoutMs: budgetMs }
    const result = (await invoke('p2p_connect', args)) as { peer?: string }
    return result?.peer ?? ''
  } catch {
    return null
  }
}

/** 等正在进行的这次拨号出结果：连上返回对端，失败或超时返回 null。 */
async function waitForTunnel(budgetMs: number): Promise<string | null> {
  const deadline = Date.now() + Math.max(0, budgetMs)
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 250))
    const status = await remoteStatus()
    if (status?.connected && !status.connecting) return status.peer ?? ''
    if (!status?.connecting) return null
  }
  return null
}

/** 配对过的电脑。
 *
 * user:“假如说我有多个设备，我该怎么切换呢？我怎么从控制电脑切回手机？”+(所以记住的不再
 * 只是一张票据，而是一份设备清单：本机永远是第一项，每配一台电脑就多一项，切换就是选一项)。
 */
export interface PairedDevice {
  id: string
  name: string
  ticket: string
}

const DEVICES_KEY = 'sunday.p2p.devices'

/** 票据里带着对端端点 id，用它当设备标识，同一台电脑重复扫码只留一条。 */
export function ticketDeviceId(ticket: string): string {
  try {
    const body = ticket.trim().replace(/^sunday1:/, '')
    const padded = body.replace(/-/g, '+').replace(/_/g, '/')
      + '='.repeat((4 - (body.length % 4)) % 4)
    const parsed = JSON.parse(atob(padded)) as { id?: unknown }
    return typeof parsed.id === 'string' ? parsed.id : ''
  } catch {
    return ''
  }
}

export function readDevices(): PairedDevice[] {
  try {
    const raw = localStorage.getItem(DEVICES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is PairedDevice => (
      Boolean(item)
      && typeof (item as PairedDevice).id === 'string'
      && typeof (item as PairedDevice).ticket === 'string'
    ))
  } catch {
    return []
  }
}

function writeDevices(devices: PairedDevice[]): void {
  try {
    localStorage.setItem(DEVICES_KEY, JSON.stringify(devices))
  } catch {
    // Storage unavailable: the list is a convenience, not the source of truth.
  }
}

/** 记下一台电脑；同一台只留一条，名字随最近一次为准。 */
export function rememberDevice(ticket: string, name: string): void {
  const id = ticketDeviceId(ticket)
  if (!id) return
  const rest = readDevices().filter((device) => device.id !== id)
  writeDevices([{ id, name: name || '电脑', ticket }, ...rest].slice(0, 8))
}

export function forgetDevice(id: string): void {
  writeDevices(readDevices().filter((device) => device.id !== id))
  if (ticketDeviceId(readTicket()) === id) saveTicket('')
}

/** 切换当前使用的设备；空表示切回本机。 */
export function activateDevice(id: string | null): void {
  if (!id || id === 'local') {
    saveTicket('')
    return
  }
  const device = readDevices().find((item) => item.id === id)
  if (device) saveTicket(device.ticket)
}

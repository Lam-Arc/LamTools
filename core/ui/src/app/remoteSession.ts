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
export async function ensureRemote(): Promise<string | null> {
  const status = await remoteStatus()
  if (status?.connected) return status.peer ?? ''
  const ticket = readTicket()
  if (!ticket) return null
  try {
    const result = (await invoke('p2p_connect', { ticket, name: 'Phone' })) as { peer?: string }
    return result?.peer ?? ''
  } catch {
    return null
  }
}

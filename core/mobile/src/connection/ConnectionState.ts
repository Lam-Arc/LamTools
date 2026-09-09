export type ConnectionState =
  | 'idle'
  | 'discovering'
  | 'connecting_lan'
  | 'connected_lan'
  | 'connecting_remote'
  | 'connected_remote'
  | 'reconnecting'
  | 'offline'
  | 'error'

export type ConnectionPath = 'lan' | 'relay' | null

export interface ConnectionSnapshot {
  state: ConnectionState
  path: ConnectionPath
  message: string
  lastError?: string
}

export const CONNECTION_LABELS: Record<ConnectionState, string> = {
  idle: '未连接',
  discovering: '正在寻找电脑…',
  connecting_lan: '正在连接局域网…',
  connected_lan: '已连接 · 局域网',
  connecting_remote: '正在连接远程服务…',
  connected_remote: '已连接 · 远程',
  reconnecting: '正在重新连接…',
  offline: '电脑离线',
  error: '连接失败',
}

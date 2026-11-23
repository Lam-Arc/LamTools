// user:“交互测试”+(展厅通过隔离服务模拟设备连接及复制，不接触真实设备)。
export interface RemoteConnectionServices {
  invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>
  copy: (ticket: string) => Promise<void>
}

/**
 * 远程通道用到的纯函数：二进制编解码与「能不能重放」的判断。
 *
 * 单独放一个模块是为了能直接测：它们决定了附件能不能原样过去，以及断线之后会不会
 * 把一次写操作做两遍。
 */
import type { TransportRequest } from '@/transport/types.ts'

/**
 * 只在读操作上重放。
 *
 * user:“断联时不得静默丢消息”+(写操作可能已经在电脑上执行过，只是回包在断线里丢了；
 * 重发一次会做两遍。所以写操作失败就如实告诉用户，别偷偷重试)。
 */
const REPLAY_SAFE_METHODS = new Set([
  // user:“断线后恢复未确认的消息与任务状态……消息可靠且不会重复执行任务”+
  // (只重放真正的读操作。以前按 `config.` / `settings.` / `workspace/` 前缀判断，
  // 结果 `config.provider.create`、`config.model.*`、`settings.update` 这些写操作
  // 也被当成只读，半断线重试会重复创建 provider/模型)。
  'initialize',
  'thread/list',
  'thread/read',
  'thread/writeReceipts', // user:“全修”+(断线后这条只读查询可以安全重连)。
  'thread/outline',
  'thread/resume',
  'thread/history',
  'thread/pageAround',
  'interaction/list',
  'process/list',
  'process/log',
  'command/catalog',
  'attachment/list',
  'attachment/get',
  'attachment/preview',
  'attachment/open',
  'config.agents_md.get',
  'config.load_context.get',
  'config.loadtools.get',
  'config.models.list',
  'config.models.usage',
  'config.model_groups.list',
  'config.providers.list',
  'config.providers.probe',
  'config.providers.status',
  'config.subagent.guide.get',
  'config.subagent.settings.get',
  'settings.get',
  'workspace.search',
])

export function isReplaySafe(request: TransportRequest): boolean {
  if (request.kind === 'http') return (request.method || 'GET').toUpperCase() === 'GET'
  const method = request.method || ''
  return REPLAY_SAFE_METHODS.has(method)
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  // 一块一块拼，避免 String.fromCharCode 收到几万个参数把调用栈压爆。
  const chunk = 0x2000
  for (let index = 0; index < bytes.length; index += chunk) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunk))
  }
  return btoa(binary)
}

export function base64ToBytes(text: string | undefined): Uint8Array {
  if (!text) return new Uint8Array()
  const binary = atob(text)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

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
  'initialize',
  'thread/list',
  'thread/read',
  'thread/outline',
  'thread/resume',
])

export function isReplaySafe(request: TransportRequest): boolean {
  if (request.kind === 'http') return (request.method || 'GET').toUpperCase() === 'GET'
  const method = request.method || ''
  if (REPLAY_SAFE_METHODS.has(method)) return true
  return method.startsWith('config.') || method.startsWith('settings.') || method.startsWith('workspace/')
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

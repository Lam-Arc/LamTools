import { TransportRpcError, TransportRequestTimeoutError } from '@/transport/types.ts'

/**
 * user:“虽然消息发出去了，但是显示输入参数保存失败这个报错”+(一次「参数不被接受」被
 * 当成网络抖动重试了六次，界面等了三秒多才弹红字；服务器已经明确拒绝的请求，重试
 * 不会让答案变对，只会把一条错误放大成六条日志)。
 *
 * Retrying exists for failures that may pass on the second attempt: a timeout, a
 * dropped socket, an unparseable transport error. A JSON-RPC error is a deliberate
 * server answer, so it is returned to the caller immediately.
 */
const NON_RETRYABLE_RPC_CODES: ReadonlySet<number> = new Set([
  -32600, // invalid request: the method or its parameters were refused
  -32601, // method not found: a client/server build mismatch, not a hiccup
  -32602, // invalid params
])

export function isRetryableRpcError(error: unknown): boolean {
  if (error instanceof TransportRequestTimeoutError) return true
  if (error instanceof TransportRpcError) {
    const code = error.code
    if (typeof code === 'number' && NON_RETRYABLE_RPC_CODES.has(code)) return false
    return true
  }
  return true
}

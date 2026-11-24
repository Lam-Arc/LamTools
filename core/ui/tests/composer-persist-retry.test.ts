import { describe, expect, it } from 'vitest'
import { isRetryableRpcError } from '@/app/rpcRetry.ts'
import { TransportRpcError, TransportRequestTimeoutError } from '@/transport/types.ts'

/**
 * user:“虽然消息发出去了，但是显示输入参数保存失败这个报错”+(手机端会话参数写入被
 * 旧核心拒绝后，界面按网络故障重试了六次才报错；这类“服务器说我参数不对”的答复必须
 * 立刻交给调用方，只有超时/掉线才值得重试)。
 */
describe('isRetryableRpcError', () => {
  it('不再重试服务器明确拒绝的请求', () => {
    expect(isRetryableRpcError(new TransportRpcError(-32600, 'active_mode must be one of chat, work, auto'))).toBe(false)
    expect(isRetryableRpcError(new TransportRpcError(-32601, 'Unsupported method: session.composer.set'))).toBe(false)
    expect(isRetryableRpcError(new TransportRpcError(-32602, 'reasoning_level is not a supported level'))).toBe(false)
  })

  it('超时与普通传输故障仍然重试', () => {
    expect(isRetryableRpcError(new TransportRequestTimeoutError('session.composer.set', 30_000))).toBe(true)
    expect(isRetryableRpcError(new Error('the core connection is closed'))).toBe(true)
    expect(isRetryableRpcError(new TransportRpcError(undefined, 'session.composer.set failed over IPC (ipc-1): boom'))).toBe(true)
  })

  it('服务端内部错误保留重试余地', () => {
    expect(isRetryableRpcError(new TransportRpcError(-32603, 'Core app-server operation failed'))).toBe(true)
  })
})

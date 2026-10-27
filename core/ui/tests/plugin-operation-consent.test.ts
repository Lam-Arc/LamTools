// user:“继续”+(自绘页遇到后台审批时，只响应一次真实确认，关闭后不执行)。
import { expect, it, vi } from 'vitest'
import { consentRpc } from '../src/plugins/consent'

it('confirms the server-captured operation and never retries changed arguments', async () => {
  const rpc = vi.fn().mockRejectedValueOnce({ data: { approval: { id: 'one', operation: 'network.change', impact: '系统代理' } } }).mockResolvedValueOnce({ done: true })
  const confirm = vi.fn(async () => true)
  expect(await consentRpc(rpc, undefined, confirm)('network.change', { port: 8080 })).toEqual({ done: true })
  expect(rpc).toHaveBeenLastCalledWith('plugin.system.operation.respond', { id: 'one', decision: 'approve' })
  expect(confirm).toHaveBeenCalledWith('network.change', '系统代理', undefined)
})

it('sends denial without executing the operation again', async () => {
  const rpc = vi.fn().mockRejectedValueOnce({ data: { approval: { id: 'one', operation: 'change', impact: 'DNS' } } }).mockResolvedValueOnce({ cancelled: true })
  expect(await consentRpc(rpc, undefined, async () => false)('change')).toEqual({ cancelled: true })
  expect(rpc).toHaveBeenLastCalledWith('plugin.system.operation.respond', { id: 'one', decision: 'deny' })
})

it('does not approve after the page has closed', async () => {
  const controller = new AbortController()
  const rpc = vi.fn().mockRejectedValueOnce({ data: { approval: { id: 'one', operation: 'change', impact: 'DNS' } } })
  await expect(consentRpc(rpc, controller.signal, async () => { controller.abort(); return true })('change')).rejects.toThrow()
  expect(rpc).toHaveBeenCalledTimes(1)
})

it('preserves unrelated RPC failures', async () => {
  const cause = new Error('offline'), rpc = vi.fn().mockRejectedValue(cause), confirm = vi.fn()
  await expect(consentRpc(rpc, undefined, confirm)('status')).rejects.toBe(cause)
  expect(confirm).not.toHaveBeenCalled()
})

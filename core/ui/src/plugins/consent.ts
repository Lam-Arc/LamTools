// user:“继续”+(所有插件表面复用宿主确认组件；一次审批只响应后台捕获的请求)。
import { h, render } from 'vue'
import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'
import type { PluginRpc } from './types'

let confirmationQueue: Promise<unknown> = Promise.resolve()
export function confirmPluginOperation(title: string, detail: string, signal?: AbortSignal): Promise<boolean> {
  const result = confirmationQueue.then(() => showConfirmation(title, detail, signal))
  confirmationQueue = result.catch(() => false)
  return result
}
function showConfirmation(title: string, detail: string, signal?: AbortSignal): Promise<boolean> {
  if (signal?.aborted) return Promise.resolve(false)
  return new Promise(resolve => {
    const host = document.createElement('div')
    document.body.append(host)
    let settled = false
    const finish = (approved: boolean) => {
      if (settled) return
      settled = true; signal?.removeEventListener('abort', abort)
      render(null, host); host.remove(); resolve(approved)
    }
    const abort = () => finish(false)
    signal?.addEventListener('abort', abort, { once: true })
    render(h(CoreConfirmDialog, { open: true, title, detail, onConfirm: () => finish(true), onCancel: abort }), host)
  })
}

export function consentRpc(rpc: PluginRpc, signal?: AbortSignal, confirm = confirmPluginOperation): PluginRpc {
  return async (method, params) => {
    if (signal?.aborted) throw new Error('插件页面已关闭')
    let result: Record<string, unknown>
    try { result = await rpc(method, params) } catch (error) {
      const data = (error as { data?: Record<string, unknown> })?.data
      if (!data?.approval) throw error
      result = data
    }
    const approval = result.approval as { id?: string; operation?: string; impact?: string } | undefined
    if (!approval?.id) return result
    const approved = await confirm(String(approval.operation || method), String(approval.impact || ''), signal)
    if (signal?.aborted) throw new Error('插件页面已关闭')
    return rpc('plugin.system.operation.respond', { id: approval.id, decision: approved ? 'approve' : 'deny' })
  }
}

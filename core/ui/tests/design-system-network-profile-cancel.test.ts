import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import ImportProfile from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ImportProfile.vue'

// user:“确保视觉、功能和交互不退化”+(订阅操作取消时保留输入，不继续后续操作或假装保存成功)。
it.each(['stop', 'config'])('keeps the draft when %s is cancelled', async phase => {
  const run = vi.fn(async (method: string) => method === `proxy.${phase}` ? { cancelled: true } : {})
  const session = { state: { proxy: { running: true } }, accelerated: false, busy: '', notice: '', run, loadProxy: vi.fn(), toggleAcceleration: vi.fn() }
  const wrapper = mount(ImportProfile, { props: { session } })
  await wrapper.get('[aria-label="订阅链接"]').setValue('https://example.test/subscription')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect((wrapper.get('[aria-label="订阅链接"]').element as HTMLInputElement).value).toBe('https://example.test/subscription')
  expect(wrapper.emitted('close')).toBeUndefined()
  expect(run.mock.calls.some(([method]) => method === 'proxy.start')).toBe(phase === 'config')
  if (phase === 'stop') expect(run.mock.calls.some(([method]) => method === 'proxy.config')).toBe(false)
  wrapper.unmount()
})

it('restores a running proxy after a failed update without losing the error', async () => {
  const session: any = { state: { proxy: { running: true } }, accelerated: false, busy: '', notice: '', error: '', loadProxy: vi.fn(), toggleAcceleration: vi.fn() }
  session.run = vi.fn(async (method: string) => {
    session.error = method === 'proxy.config' ? '更新失败' : ''
    return method === 'proxy.config' ? null : {}
  })
  const wrapper = mount(ImportProfile, { props: { session } })
  await wrapper.get('[aria-label="订阅链接"]').setValue('https://example.test/subscription')
  await wrapper.get('form').trigger('submit'); await flushPromises()
  expect(session.run.mock.calls.map(([method]: string[]) => method)).toEqual(['proxy.stop', 'proxy.config', 'proxy.start'])
  expect(session.error).toBe('更新失败')
  expect(session.loadProxy).toHaveBeenCalledOnce()
  expect(wrapper.emitted('close')).toBeUndefined()
  wrapper.unmount()
})

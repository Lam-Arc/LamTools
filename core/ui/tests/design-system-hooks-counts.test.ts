import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import CoreHooksEditor from '../src/components/CoreHooksEditor.vue'

const hooks = [
  { id: 'a', event: 'PreToolUse', matcher: '*', source: 'user', source_name: 'config', handler_type: 'command', command: 'sample', trusted: false, status: 'pending_review' },
  { id: 'b', event: 'PostToolUse', matcher: '*', source: 'user', source_name: 'config', handler_type: 'command', command: 'sample', trusted: true, status: 'trusted' },
]
// user:“确保视觉、功能和交互不退化”+(同一钩子操作不能重复提交，删除后信任统计保持准确)。
it('prevents duplicate trust requests while one is pending', async () => {
  let finish!: (value: unknown) => void
  const rpc = vi.fn((method: string) => method === 'hook.list' ? Promise.resolve({ hooks: structuredClone(hooks), total_count: 2, trusted_count: 1, trustable_count: 1 }) : new Promise(resolve => { finish = resolve }))
  const wrapper = mount(CoreHooksEditor, { props: { requestRpc: rpc }, attachTo: document.body }); await flushPromises()
  const button = wrapper.get('[data-hook-card="a"] [data-hook-trust]')
  await button.trigger('click')
  expect(button.attributes('disabled')).toBeDefined()
  await button.trigger('click')
  expect(rpc.mock.calls.filter(([method]) => method === 'hook.trust')).toHaveLength(1)
  finish({}); await flushPromises()
  expect(wrapper.text()).toContain('已信任 2')
  wrapper.unmount()
})

it('keeps trusted and pending counts correct when deleting an untrusted hook', async () => {
  const rpc = vi.fn(async (method: string) => method === 'hook.list' ? { hooks: structuredClone(hooks), total_count: 2, trusted_count: 1, trustable_count: 1 } : {})
  const wrapper = mount(CoreHooksEditor, { props: { requestRpc: rpc }, attachTo: document.body }); await flushPromises()
  await wrapper.get('[data-hook-delete="a"]').trigger('click')
  const confirm = [...document.querySelectorAll<HTMLButtonElement>('.core-confirm__submit')][0]
  confirm.click(); await flushPromises()
  expect(wrapper.text()).toContain('共 1 个 · 已信任 1')
  expect(wrapper.text()).not.toContain('待审核 1')
  wrapper.unmount()
})

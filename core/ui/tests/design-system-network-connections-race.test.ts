import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import ConnectionsView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/ConnectionsView.vue'

// user:“确保视觉、功能和交互不退化”+(较早的连接查询不能覆盖新的搜索结果或提前结束加载)。
it('keeps the newest connections search when responses arrive out of order', async () => {
  const pending: Array<(value: unknown) => void> = []
  const read = vi.fn(() => new Promise(resolve => pending.push(resolve)))
  const wrapper = mount(ConnectionsView, { props: { session: { read } } })
  await wrapper.get('[aria-label="搜索连接"]').setValue('新应用')
  await wrapper.get('form').trigger('submit')
  expect(pending).toHaveLength(2)
  pending[0]({ connections: [{ process: '旧应用' }], total: 1 }); await flushPromises()
  expect(wrapper.find('.nx-table-loading').exists()).toBe(true)
  pending[1]({ connections: [{ process: '新应用' }], total: 1 }); await flushPromises()
  expect(wrapper.text()).toContain('新应用')
  expect(wrapper.text()).not.toContain('旧应用')
  wrapper.unmount()
})

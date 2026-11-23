import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import TransferView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/TransferView.vue'
import UiSelect from '../src/components/UiSelect.vue'

// user:“确保视觉、功能和交互不退化”+(限速失败或取消时保留原值，同一设置可重试)。
it('only shows a task limit after the operation succeeds', async () => {
  const run = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce({ cancelled: true }).mockResolvedValueOnce({})
  const session = { busy: '', state: { downloads: [], proxy: { running: false } }, tasks: [{ gid: 'one', filename: '示例', status: 'active', completedLength: 0, totalLength: 1, downloadSpeed: 0 }], run, loadTasks: vi.fn() }
  const wrapper = mount(TransferView, { props: { session } })
  await wrapper.get('[aria-label="展开下载详情"]').trigger('click')
  const select = wrapper.findAllComponents(UiSelect).find(item => item.attributes('data-transfer-task-limit') !== undefined)!
  for (let count = 1; count <= 3; count++) {
    select.vm.$emit('update:modelValue', '1048576')
    await flushPromises()
    expect(run).toHaveBeenCalledTimes(count)
    expect(select.props('modelValue')).toBe(count < 3 ? '0' : '1048576')
  }
  wrapper.unmount()
})

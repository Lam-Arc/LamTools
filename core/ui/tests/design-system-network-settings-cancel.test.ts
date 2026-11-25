import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import AdvancedView from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/AdvancedView.vue'
import NetworkSettings from '../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkSettings.vue'
import UiSelect from '../src/components/UiSelect.vue'

// user:“确保视觉、功能和交互不退化”+(取消或失败的设置不应显示为成功，可再次尝试)。
it('keeps the old sampling interval until saving succeeds', async () => {
  const run = vi.fn().mockResolvedValueOnce({ cancelled: true }).mockResolvedValueOnce({})
  const wrapper = mount(AdvancedView, { props: { session: { state: { settings: { sample_seconds: 5 }, revision: 1 }, run } } })
  const select = wrapper.findAllComponents(UiSelect).find(item => item.attributes('data-network-sampling') !== undefined)!
  select.vm.$emit('update:modelValue', '10'); await flushPromises()
  expect(select.props('modelValue')).toBe('5')
  select.vm.$emit('update:modelValue', '10'); await flushPromises()
  expect(run).toHaveBeenCalledTimes(2)
  expect(select.props('modelValue')).toBe('10')
  wrapper.unmount()
})

it('keeps DNS editing open when the operation is cancelled', async () => {
  const session = { busy: '', interfaces: [{ index: 1, name: '示例', ipv4: [], dns: [] }], state: { rules: [] }, run: vi.fn(async () => ({ cancelled: true })), read: vi.fn() }
  const wrapper = mount(NetworkSettings, { props: { session } })
  await wrapper.get('[data-dns-toggle]').trigger('click')
  const select = wrapper.findAllComponents(UiSelect).find(item => item.attributes('data-network-interface') !== undefined)!
  select.vm.$emit('update:modelValue', '1'); await flushPromises()
  await wrapper.get('[data-dns-apply]').trigger('click'); await flushPromises()
  expect(wrapper.find('[data-dns-apply]').exists()).toBe(true)
  expect(session.read).not.toHaveBeenCalled()
  wrapper.unmount()
})

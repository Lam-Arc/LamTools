import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

// user:“参数调整、变体对比及交互测试”+(权限模式与信任撤销仅修改本地示例)。
describe('permission settings gallery', () => {
  it('switches permission presets and revokes an example trust', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreSettings'); await flushPromises()
    await wrapper.get('[data-settings-preview-permissions]').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-default-permission-preset="full_access"]').exists()).toBe(true), { timeout: 10000 })
    await wrapper.get('[data-default-permission-preset="full_access"]').trigger('click')
    expect(wrapper.get('[data-default-permission-preset="full_access"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-allow-outside-workdir] input').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-trust-revoke]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂无已信任操作')
    wrapper.unmount()
  })
})

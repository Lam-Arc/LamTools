import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import CoreProjectCreate from '../src/components/CoreProjectCreate.vue'
describe('project creation visual picker', () => {
  it('submits the icon and color selected through the keyboard', async () => {
    const transport = { request: vi.fn() } as any
    const wrapper = mount(CoreProjectCreate, { props: { transport }, global: { stubs: { Teleport: true } } })
    await wrapper.get('[data-project-name]').setValue('示例')
    await wrapper.get('[data-project-root]').setValue('E:\\project')
    await wrapper.get('[data-project-icon-option="folder"]').trigger('keydown', { key: 'ArrowRight' })
    await wrapper.get('[data-project-color-option="gray"]').trigger('keydown', { key: 'ArrowRight' })
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toMatchObject({ name: '示例', icon_key: 'code', color_key: 'blue' })
    wrapper.unmount()
  })
})

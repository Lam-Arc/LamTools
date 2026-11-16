import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import ComputerUseCapsule from '../src/computerUse/ComputerUseCapsule.vue'
describe('computer use capsule gallery', () => {
  it('previews the real capsule and tests its stop interaction', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('ComputerUseCapsule')
    const capsule = wrapper.getComponent(ComputerUseCapsule)
    await capsule.get('button[aria-label="结束"]').trigger('click')
    expect(wrapper.text()).toContain('结束 1 次')
    await wrapper.get('[data-source="ComputerUseCapsule"]').trigger('click')
    expect(wrapper.get('[data-source-content="ComputerUseCapsule"]').text()).toContain('prefers-reduced-motion')
    wrapper.unmount()
  })
})

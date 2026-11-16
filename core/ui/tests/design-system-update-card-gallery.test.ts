import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'
import CoreUpdateCard from '../src/components/CoreUpdateCard.vue'
describe('update card gallery', () => {
  it('simulates updating and cancellation without real update actions', async () => {
    const wrapper = mount(Gallery, { global: { stubs: { Teleport: true } } })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreUpdateCard')
    await wrapper.get('[data-update-preview-open]').trigger('click')
    const card = wrapper.getComponent(CoreUpdateCard)
    expect(card.text()).toContain('发现新版本')
    await card.get('[data-update-confirm]').trigger('click')
    expect(card.text()).toContain('正在下载更新')
    await card.get('[data-update-cancel]').trigger('click')
    expect(wrapper.get('[data-update-preview-result]').text()).toContain('已取消')
    await wrapper.get('[data-source="CoreUpdateCard"]').trigger('click')
    expect(wrapper.get('[data-source-content="CoreUpdateCard"]').text()).toContain('trapDialogTab')
    wrapper.unmount()
  })
  it('can exit an installing-state preview without changing production controls', async () => {
    const wrapper = mount(Gallery, { global: { stubs: { Teleport: true } } })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreUpdateCard')
    await wrapper.get('[aria-label="更新预览状态"]').trigger('click')
    await wrapper.findAll('.ui-select-option').find(option => option.text() === '安装中')!.trigger('click')
    await wrapper.get('[data-update-preview-open]').trigger('click')
    const card = wrapper.getComponent(CoreUpdateCard)
    expect((card.get('[data-update-dismiss]').element as HTMLButtonElement).disabled).toBe(true)
    await card.get('[data-update-preview-exit]').trigger('click')
    expect(wrapper.findComponent(CoreUpdateCard).exists()).toBe(false)
    wrapper.unmount()
  })
})

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Gallery from '../src/design-system/Gallery.vue'

describe('gallery button and dialog specimens', () => {
  it('compares production button variants and respects the disabled setting', async () => {
    const wrapper = mount(Gallery)
    await wrapper.get('input[aria-label="搜索组件"]').setValue('SundayButton')
    // user:“UI 请按语义整理并展示”+(普通操作只显示四种语义和实际动作)。
    expect(wrapper.findAll('[data-button-role]').map(button => button.text())).toEqual(['保存', '取消', '刷新', '删除'])
    expect(wrapper.find('.preview .btn--ghost').exists()).toBe(false)
    await wrapper.get('input[aria-label="主题材质"]').setValue(true)
    await wrapper.get('input[aria-label="紧凑尺寸"]').setValue(true)
    expect(wrapper.get('.preview .btn--primary').classes()).toEqual(expect.arrayContaining(['btn--material', 'btn--sm']))
    expect((wrapper.get('.preview').element as HTMLElement).style.getPropertyValue('--theme-control-image')).toContain('linear-gradient')
    await wrapper.get('.preview .btn--primary').trigger('click')
    expect(wrapper.text()).toContain('示例操作：保存')
    await wrapper.get('input[type="checkbox"]').setValue(true)
    expect(wrapper.findAll('.preview .btn').every(button => (button.element as HTMLButtonElement).disabled)).toBe(true)
    wrapper.unmount()
  })
  it('opens a real confirmation dialog, edits the input and confirms', async () => {
    const wrapper = mount(Gallery, { attachTo: document.body })
    await wrapper.get('input[aria-label="搜索组件"]').setValue('CoreConfirmDialog')
    await wrapper.get('[data-open-confirm]').trigger('click')
    await wrapper.vm.$nextTick()
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    expect(dialog).toBeTruthy()
    const input = dialog.querySelector<HTMLInputElement>('input')!
    input.value = '示例名称'
    input.dispatchEvent(new Event('input', { bubbles: true }))
    dialog.querySelector<HTMLButtonElement>('.core-confirm__submit')!.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('已确认：示例名称')
    wrapper.unmount()
  })
})

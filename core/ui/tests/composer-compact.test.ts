import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

import ComposerBar from '@/components/ComposerBar.vue'

vi.mock('@/components/CoreSendStopButton.vue', () => ({
  default: { name: 'CoreSendStopButton', template: '<button class="stub-send" type="submit" />' },
}))

/**
 * user:“把胶囊做了…它只是现在输入栏的形态变体，不是新样式”+(同一个组件换形态：
 * 根节点带形态类、发送键仍在、插槽照旧；外观差异全部由 CSS 承接。)
 */
describe('ComposerBar compact variant', () => {
  it('marks the compact form on the same root element', () => {
    const wrapper = mount(ComposerBar, { props: { variant: 'compact', modelValue: '' } })
    expect(wrapper.classes()).toContain('composer-root--compact')
    wrapper.unmount()
  })

  it('keeps the floating form as the default', () => {
    const wrapper = mount(ComposerBar, { props: { modelValue: '' } })
    expect(wrapper.classes()).toContain('composer-root--floating')
    expect(wrapper.classes()).not.toContain('composer-root--compact')
    wrapper.unmount()
  })

  it('switches form in place without dropping slots', async () => {
    const wrapper = mount(ComposerBar, {
      props: { modelValue: '', variant: 'compact' },
      slots: { textarea: '<span data-slot-textarea>编辑器</span>' },
    })
    expect(wrapper.find('[data-slot-textarea]').exists()).toBe(true)
    await wrapper.setProps({ variant: 'floating' })
    expect(wrapper.classes()).toContain('composer-root--floating')
    expect(wrapper.find('[data-slot-textarea]').exists()).toBe(true)
    wrapper.unmount()
  })
})

// user:“把胶囊做了……它只是现在输入栏的形态变体，不是新样式”+
// (展厅里必须能看到这个形态，否则版本一合并它就会静默消失。)
it('shows the compact form in the design system gallery', async () => {
  const ComposerPreview = (await import('@/design-system/ComposerPreview.vue')).default
  const wrapper = mount(ComposerPreview)
  expect(wrapper.find('[data-gallery-composer-compact]').exists()).toBe(true)
  expect(wrapper.find('[data-gallery-composer-compact] .composer-root--compact').exists()).toBe(true)
  wrapper.unmount()
})

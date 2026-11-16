import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkflowSwitchGuard from '../../src/lamtools_core/plugins/bundled/workflow/ui/WorkflowSwitchGuard.vue'

// user:“确保视觉、功能和交互不退化”+(三种草稿操作保留且键盘焦点受控)。
describe('workflow draft switch guard', () => {
  it('focuses cancel, traps tab, restores focus and reports each choice', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus()
    const wrapper = mount(WorkflowSwitchGuard, { attachTo: document.body, props: { open: false } })
    await wrapper.setProps({ open: true }); await wrapper.vm.$nextTick()
    const buttons = wrapper.findAll('button')
    expect(document.activeElement).toBe(buttons[0].element)
    for (const button of buttons) Object.defineProperty(button.element, 'getClientRects', { value: () => [new DOMRect(0, 0, 20, 20)] })
    ;(buttons[2].element as HTMLElement).focus()
    await buttons[2].trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(buttons[0].element)
    await buttons[1].trigger('click'); expect(wrapper.emitted('choice')?.[0]).toEqual(['discard'])
    await wrapper.setProps({ open: false }); await wrapper.vm.$nextTick()
    expect(document.activeElement).toBe(opener)
    await wrapper.setProps({ open: true }); await wrapper.vm.$nextTick()
    await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('choice')?.[1]).toEqual(['cancel'])
    await wrapper.get('button:last-child').trigger('click'); expect(wrapper.emitted('choice')?.[2]).toEqual(['save'])
    wrapper.unmount(); opener.remove()
  })
})

import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryNameDialog from '../src/components/LibraryNameDialog.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'

describe('shared dialog keyboard behavior', () => {
  it('closes a name dialog from its action buttons and returns focus', async () => {
    const opener = document.createElement('button'); document.body.append(opener); opener.focus()
    const wrapper = mount(LibraryNameDialog, { attachTo: document.body, props: { title: '名称', fieldLabel: '名称', modelValue: '示例', submitLabel: '保存' } })
    const action = wrapper.get('.dialog-actions button')
    ;(action.element as HTMLButtonElement).focus()
    const outside = vi.fn(); document.addEventListener('keydown', outside)
    await action.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(outside).not.toHaveBeenCalled()
    wrapper.unmount()
    expect(document.activeElement).toBe(opener)
    document.removeEventListener('keydown', outside); opener.remove()
  })
  it('focuses an available action and keeps Escape within the confirmation', async () => {
    const wrapper = mount(CoreConfirmDialog, { attachTo: document.body, props: { open: true, title: '确认', confirmDisabled: true } })
    await wrapper.vm.$nextTick()
    const cancel = document.querySelector<HTMLButtonElement>('.core-confirm__cancel')!
    expect(document.activeElement).toBe(cancel)
    const outside = vi.fn(); document.addEventListener('keydown', outside)
    cancel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(outside).not.toHaveBeenCalled()
    document.removeEventListener('keydown', outside); wrapper.unmount()
  })
})

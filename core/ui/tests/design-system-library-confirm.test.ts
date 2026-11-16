import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryConfirmDialog from '../src/components/LibraryConfirmDialog.vue'

describe('library confirmation', () => {
  it('keeps full warning text, labels and actions for destructive operations', async () => {
    const wrapper = mount(LibraryConfirmDialog, { props: { open: true, title: '删除文件夹', ariaLabel: '确认删除', confirmLabel: '删除', cancelLabel: '继续编辑', confirmAttrs: { 'data-confirm-delete': '' } }, attrs: { 'data-dialog-delete': '' }, slots: { default: '文件夹里面的条目也会一起删掉，且无法恢复。' } })
    expect(wrapper.get('[data-dialog-delete]').text()).toContain('且无法恢复')
    expect(wrapper.get('[data-dialog-delete]').attributes('aria-label')).toBe('确认删除')
    await wrapper.get('[data-confirm-delete]').trigger('click')
    expect(wrapper.emitted('confirm')).toHaveLength(1)
    await wrapper.get('.library-button:not([data-confirm-delete])').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    await wrapper.get('.dialog-dimmer').trigger('click')
    expect(wrapper.emitted('cancel')).toHaveLength(2)
    wrapper.unmount()
  })
  it('dismisses on Escape and restores the prior focus', async () => {
    const previous = document.createElement('button')
    document.body.append(previous)
    previous.focus()
    const wrapper = mount(LibraryConfirmDialog, { attachTo: document.body, props: { open: false, title: '放弃修改', confirmLabel: '放弃修改' } })
    await wrapper.setProps({ open: true })
    await vi.waitFor(() => expect(document.activeElement?.textContent).toBe('取消'))
    await wrapper.get('.dialog-dimmer').trigger('keydown.esc')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    await wrapper.setProps({ open: false })
    expect(document.activeElement).toBe(previous)
    wrapper.unmount()
    previous.remove()
  })
})


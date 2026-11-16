import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LibraryNameDialog from '../src/components/LibraryNameDialog.vue'
describe('library name form', () => {
  it('handles editing, keyboard submission, errors, disabled and busy states', async () => {
    const wrapper = mount(LibraryNameDialog, { attachTo: document.body, props: { title: '新建文件夹', fieldLabel: '文件夹名称', modelValue: '', submitLabel: '创建', inputAttrs: { 'data-field': '' }, submitAttrs: { 'data-submit': '' } } })
    const input = wrapper.get('[data-field]')
    await vi.waitFor(() => expect(document.activeElement).toBe(input.element))
    expect((wrapper.get('[data-submit]').element as HTMLButtonElement).disabled).toBe(true)
    await input.setValue('文件夹')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['文件夹'])
    await wrapper.setProps({ modelValue: '文件夹' })
    await input.trigger('keydown.enter')
    expect(wrapper.emitted('submit')).toHaveLength(1)
    await wrapper.setProps({ busy: true, error: '失败' })
    expect((wrapper.get('[data-submit]').element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toBe('失败')
    const documentKeydown = vi.fn()
    document.addEventListener('keydown', documentKeydown)
    await input.trigger('keydown.escape')
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    expect(documentKeydown).not.toHaveBeenCalled()
    document.removeEventListener('keydown', documentKeydown)
    wrapper.unmount()
  })
})


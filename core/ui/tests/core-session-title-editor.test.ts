import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSessionTitleEditor from '../src/components/CoreSessionTitleEditor.vue'

// user:“会话标题需要先点击进入编辑才是正常文本”+
// (默认只渲染不可选中的显示文本；点一下才挂上输入框，Esc/失焦再退回显示态)。
async function startEditing(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('[data-session-title-display]').trigger('click')
  await wrapper.vm.$nextTick()
}

describe('CoreSessionTitleEditor', () => {
  it('renders the title as plain text and only becomes an input after a click', async () => {
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', sessionId: '1234567890', rename: vi.fn() },
    })

    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.get('[data-session-title-display]').text()).toBe('Draft')
    expect(wrapper.text()).toContain('#12345678')

    await startEditing(wrapper)
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Draft')
  })

  it('trims and saves a changed title on blur', async () => {
    const rename = vi.fn(async () => undefined)
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', rename },
    })

    await startEditing(wrapper)
    await wrapper.get('input').setValue('  Final title  ')
    await wrapper.get('input').trigger('blur')

    expect(rename).toHaveBeenCalledWith('Final title')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('input').exists()).toBe(false)
    expect(wrapper.get('[data-session-title-display]').text()).toBe('Final title')
  })

  it('restores the current title on Escape without saving', async () => {
    const rename = vi.fn(async () => undefined)
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', rename },
    })

    await startEditing(wrapper)
    await wrapper.get('input').setValue('Discard me')
    await wrapper.get('input').trigger('keydown.esc')

    expect(rename).not.toHaveBeenCalled()
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-session-title-display]').text()).toBe('Draft')
  })

  it('rolls back and reports a failed rename', async () => {
    const failure = new Error('rename failed')
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', rename: async () => { throw failure } },
    })

    await startEditing(wrapper)
    await wrapper.get('input').setValue('Broken')
    await wrapper.get('input').trigger('blur')
    await Promise.resolve()
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-session-title-display]').text()).toBe('Draft')
    expect(wrapper.emitted('error')).toEqual([[failure]])
  })
})

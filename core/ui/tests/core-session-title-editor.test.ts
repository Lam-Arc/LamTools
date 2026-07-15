import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSessionTitleEditor from '../src/components/CoreSessionTitleEditor.vue'

describe('CoreSessionTitleEditor', () => {
  it('renders the active title and short session id in the main header', () => {
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', sessionId: '1234567890', rename: vi.fn() },
    })

    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Draft')
    expect(wrapper.text()).toContain('#12345678')
  })

  it('trims and saves a changed title on blur', async () => {
    const rename = vi.fn(async () => undefined)
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', rename },
    })

    await wrapper.get('input').setValue('  Final title  ')
    await wrapper.get('input').trigger('blur')

    expect(rename).toHaveBeenCalledWith('Final title')
  })

  it('restores the current title on Escape without saving', async () => {
    const rename = vi.fn(async () => undefined)
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', rename },
    })

    await wrapper.get('input').setValue('Discard me')
    await wrapper.get('input').trigger('keydown.esc')

    expect(rename).not.toHaveBeenCalled()
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Draft')
  })

  it('rolls back and reports a failed rename', async () => {
    const failure = new Error('rename failed')
    const wrapper = mount(CoreSessionTitleEditor, {
      props: { title: 'Draft', rename: async () => { throw failure } },
    })

    await wrapper.get('input').setValue('Broken')
    await wrapper.get('input').trigger('blur')
    await Promise.resolve()

    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('Draft')
    expect(wrapper.emitted('error')).toEqual([[failure]])
  })
})

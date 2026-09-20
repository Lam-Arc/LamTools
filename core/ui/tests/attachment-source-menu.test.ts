import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AttachmentSourceMenu from '../src/components/AttachmentSourceMenu.vue'

describe('AttachmentSourceMenu', () => {
  it('opens categorized mobile sources and emits the selected source', async () => {
    const wrapper = mount(AttachmentSourceMenu, { props: { categorized: true } })

    await wrapper.get('.composer-attachment-button').trigger('click')
    expect(wrapper.get('[role="menu"]').text()).toContain('文件')
    expect(wrapper.get('[role="menu"]').text()).toContain('相册')
    expect(wrapper.get('[role="menu"]').text()).toContain('相机')

    const choices = wrapper.findAll('[role="menuitem"]')
    await choices[1].trigger('click')
    expect(wrapper.emitted('select')).toEqual([['photos']])
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps desktop attachment selection as a direct file action', async () => {
    const wrapper = mount(AttachmentSourceMenu)
    await wrapper.get('.composer-attachment-button').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['file']])
    expect(wrapper.find('[role="menu"]').exists()).toBe(false)
    wrapper.unmount()
  })
})

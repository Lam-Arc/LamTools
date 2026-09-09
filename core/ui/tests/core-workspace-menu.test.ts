// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CoreWorkspaceMenu from '../src/components/CoreWorkspaceMenu.vue'

describe('CoreWorkspaceMenu', () => {
  it('shows the current environment and emits a selection from its composer popover', async () => {
    const wrapper = mount(CoreWorkspaceMenu, {
      props: {
        activeId: 'desktop',
        options: [
          { id: 'desktop', label: '办公室电脑', online: true, platform: 'windows' },
          { id: 'phone', label: '本机', online: true, platform: 'android' },
        ],
      },
    })

    expect(wrapper.get('button').attributes('aria-label')).toContain('办公室电脑')
    await wrapper.get('.core-workspace-menu__trigger').trigger('click')
    expect(wrapper.findAll('[data-workspace-option]')).toHaveLength(2)
    await wrapper.get('[data-workspace-option="phone"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['phone']])
    expect(wrapper.find('.core-workspace-menu__card').exists()).toBe(false)
  })
})

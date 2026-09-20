import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MobileTopBar from '../src/components/MobileTopBar.vue'

describe('MobileTopBar', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn((query: string) => ({
        matches: query.includes('no-preference'),
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
  })

  it('opens both host surfaces and announces synchronization', async () => {
    const wrapper = mount(MobileTopBar, { props: { syncing: true } })

    expect(wrapper.get('[role="status"]').text()).toBe('正在同步')
    await wrapper.get('[data-mobile-sidebar-button]').trigger('click')
    await wrapper.get('[data-mobile-account-button]').trigger('click')
    expect(wrapper.emitted('open-sidebar')).toHaveLength(1)
    expect(wrapper.emitted('open-account')).toHaveLength(1)

    await wrapper.setProps({ syncing: false })
    expect(wrapper.get('[role="status"]').attributes('style')).toContain('display: none')

    await wrapper.setProps({ hidden: true })
    expect(wrapper.get('.mobile-top-bar').attributes('style')).toContain('display: none')
    wrapper.unmount()
  })

  it('exposes the current mobile plugin mode without restoring the desktop title bar', async () => {
    const wrapper = mount(MobileTopBar, {
      props: {
        canToggleMode: true,
        modeLabel: '工作流',
        modeTitle: '切换到 Agent',
      },
    })

    const button = wrapper.get('[data-mobile-mode-button]')
    expect(button.text()).toContain('工作流')
    expect(button.attributes('aria-label')).toBe('切换到 Agent')
    await button.trigger('click')
    expect(wrapper.emitted('cycle-mode')).toHaveLength(1)
    wrapper.unmount()
  })
})

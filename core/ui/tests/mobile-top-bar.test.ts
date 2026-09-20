import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MobileTopBar from '../src/components/MobileTopBar.vue'

describe('MobileTopBar', () => {
  beforeEach(() => {
    window.localStorage.clear()
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

  it('keeps the sidebar entry and announces synchronization', async () => {
    const wrapper = mount(MobileTopBar, { props: { syncing: true } })

    expect(wrapper.get('[role="status"]').text()).toBe('正在同步')
    await wrapper.get('[data-mobile-sidebar-button]').trigger('click')
    expect(wrapper.emitted('open-sidebar')).toHaveLength(1)

    await wrapper.setProps({ syncing: false })
    expect(wrapper.get('[role="status"]').attributes('style')).toContain('display: none')

    await wrapper.setProps({ hidden: true })
    expect(wrapper.get('.mobile-top-bar').attributes('style')).toContain('display: none')
    wrapper.unmount()
  })

  it('expands a glass command card and selects a mode directly', async () => {
    const wrapper = mount(MobileTopBar, {
      props: {
        activeModeId: 'workflow',
        modeOptions: [
          { id: 'agent', label: 'Agent' },
          { id: 'workflow', label: '工作流' },
        ],
      },
    })

    const trigger = wrapper.get('[data-mobile-command-button]')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[data-mobile-command-panel]').attributes('style')).not.toContain('display: none')
    expect(wrapper.get('[data-mobile-mode-option="workflow"]').attributes('aria-selected')).toBe('true')

    await wrapper.get('[data-mobile-mode-option="agent"]').trigger('click')
    expect(wrapper.emitted('select-mode')).toEqual([['agent']])
    expect(trigger.attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })

  it('routes search, settings, and account actions from the expanded card', async () => {
    const wrapper = mount(MobileTopBar, { props: { accountLabel: 'alice' } })

    for (const [selector, event] of [
      ['[data-mobile-search-button]', 'open-search'],
      ['[data-mobile-settings-button]', 'open-settings'],
      ['[data-mobile-account-button]', 'open-account'],
    ] as const) {
      await wrapper.get('[data-mobile-command-button]').trigger('click')
      const button = wrapper.get(selector)
      if (event === 'open-account') expect(button.text()).toContain('alice')
      await button.trigger('click')
      expect(wrapper.emitted(event)).toHaveLength(1)
    }

    wrapper.unmount()
  })

  it('closes the card when the host hides the mobile controls', async () => {
    const wrapper = mount(MobileTopBar)
    await wrapper.get('[data-mobile-command-button]').trigger('click')
    expect(wrapper.get('[data-mobile-command-button]').attributes('aria-expanded')).toBe('true')
    await wrapper.setProps({ hidden: true })
    expect(wrapper.get('[data-mobile-command-button]').attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })

  it('clamps the expanded card inside a narrow viewport after dragging the dock', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 844 })
    const wrapper = mount(MobileTopBar, {
      props: { modeOptions: [{ id: 'agent', label: 'Agent' }] },
    })
    const trigger = wrapper.get('[data-mobile-command-button]').element as HTMLElement
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      x: 200,
      y: 20,
      top: 20,
      right: 244,
      bottom: 64,
      left: 200,
      width: 44,
      height: 44,
      toJSON: () => ({}),
    })
    const panel = wrapper.get('[data-mobile-command-panel]').element as HTMLElement
    Object.defineProperty(panel, 'offsetWidth', { configurable: true, value: 286 })
    Object.defineProperty(panel, 'offsetHeight', { configurable: true, value: 340 })

    await wrapper.get('[data-mobile-command-button]').trigger('click')
    await new Promise((resolve) => window.setTimeout(resolve, 0))

    const dock = wrapper.get('.mobile-command-dock').element as HTMLElement
    const panelLeft = 200 + Number.parseFloat(dock.style.getPropertyValue('--mobile-command-panel-x'))
    expect(panelLeft).toBeGreaterThanOrEqual(12)
    expect(panelLeft + 286).toBeLessThanOrEqual(378)
    wrapper.unmount()
  })
})

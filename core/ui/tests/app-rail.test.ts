import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AppRail from '../src/components/AppRail.vue'

describe('AppRail', () => {
  it('renders the section entries icon-only and marks the active one', async () => {
    const wrapper = mount(AppRail, { props: { active: 'library' } })

    const entries = wrapper.findAll('[data-rail-entry]')
    expect(entries.map(entry => entry.attributes('data-rail-entry'))).toEqual([
      'chat', 'arrange', 'library', 'plugins', 'settings', 'account',
    ])
    // 仅图标：按钮内没有可见文字，靠 aria-label/title 说明。
    for (const entry of entries) {
      expect(entry.classes()).toContain('app-rail__button')
      expect(entry.attributes('aria-label')).toBeTruthy()
      expect(entry.text()).toBe('')
    }
    expect(wrapper.get('[data-rail-entry="library"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-rail-entry="chat"]').attributes('aria-pressed')).toBe('false')

    await wrapper.get('[data-rail-entry="arrange"]').trigger('click')
    expect(wrapper.emitted('open')?.[0]).toEqual(['arrange'])
  })

  it('keeps the account entry at the bottom after a spacer', async () => {
    const wrapper = mount(AppRail, { props: { active: 'chat' } })
    const children = Array.from(wrapper.get('[data-app-rail]').element.children)
    const spacerIndex = children.findIndex(child => child.classList.contains('app-rail__spacer'))
    const accountIndex = children.findIndex(child => child.getAttribute('data-rail-entry') === 'account')
    expect(spacerIndex).toBeGreaterThan(-1)
    expect(accountIndex).toBeGreaterThan(spacerIndex)

    await wrapper.get('[data-rail-entry="account"]').trigger('click')
    expect(wrapper.emitted('open')?.[0]).toEqual(['account'])
  })
})

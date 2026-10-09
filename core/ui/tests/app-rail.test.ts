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

  it('shows no update entry while the app is current', () => {
    const wrapper = mount(AppRail, { props: { active: 'chat' } })

    expect(wrapper.find('[data-rail-update]').exists()).toBe(false)
  })

  it('puts the update entry above the account entry, icon-only and explained', async () => {
    const wrapper = mount(AppRail, {
      props: {
        active: 'chat',
        updateAvailable: true,
        updateAction: 'download',
        updateLabel: '发现新版本 v9.9.9，点击下载',
      },
    })

    const button = wrapper.get('[data-rail-update]')
    expect(button.attributes('aria-label')).toBe('发现新版本 v9.9.9，点击下载')
    expect(button.attributes('title')).toBe('发现新版本 v9.9.9，点击下载')
    expect(button.text()).toBe('')
    expect(button.attributes('data-rail-update-action')).toBe('download')
    expect(button.attributes('data-rail-update-state')).toBe('ready')

    // 位置：夹在占位块与账号之间——就是「账号图标上面」。
    const children = Array.from(wrapper.get('[data-app-rail]').element.children)
    const spacerIndex = children.findIndex(child => child.classList.contains('app-rail__spacer'))
    const updateIndex = children.findIndex(child => child.hasAttribute('data-rail-update'))
    const accountIndex = children.findIndex(child => child.getAttribute('data-rail-entry') === 'account')
    expect(updateIndex).toBeGreaterThan(spacerIndex)
    expect(accountIndex).toBeGreaterThan(updateIndex)

    await button.trigger('click')
    expect(wrapper.emitted('update')).toHaveLength(1)
  })

  it('switches the update entry to install and marks a running download', () => {
    const installing = mount(AppRail, {
      props: { active: 'chat', updateAvailable: true, updateAction: 'install' },
    })
    expect(installing.get('[data-rail-update]').attributes('data-rail-update-action')).toBe('install')

    const downloading = mount(AppRail, {
      props: { active: 'chat', updateAvailable: true, updateBusy: true },
    })
    expect(downloading.get('[data-rail-update]').attributes('data-rail-update-state')).toBe('busy')
  })
})

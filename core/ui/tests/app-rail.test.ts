import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import AppRail from '../src/components/AppRail.vue'
import { setPluginPageEntries } from '../src/plugins/contributions'

function pluginPage(id: string, title: string, order = 50) {
  return {
    plugin: 'demo',
    id,
    title,
    entry_url: `/api/core/plugin-system/demo/assets/${id}.mjs`,
    navigation: true,
    order,
  }
}

function seedPluginPages(count: number) {
  setPluginPageEntries(Array.from({ length: count }, (_, index) => pluginPage(String.fromCharCode(97 + index), `页面 ${String.fromCharCode(97 + index)}`, index)))
}

afterEach(() => setPluginPageEntries([]))

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

  // user:“左竖栏多余的插件提供的按钮折叠进一个···，悬浮时再右侧弹一个透明抽屉”
  // +“一个都不常驻”+(插件导航按钮全部收进“更多”，竖栏不再逐个占用图标位；
  // 抽屉默认不出现在 DOM 里，避免空占位挡住左侧会话栏。)
  it('folds every plugin navigation page into a more entry', () => {
    seedPluginPages(5)
    const wrapper = mount(AppRail, { props: { active: 'chat' } })

    expect(wrapper.findAll('[data-plugin-rail]')).toHaveLength(0)
    const more = wrapper.get('[data-rail-plugin-more]')
    expect(more.attributes('aria-label')).toBe('更多插件')
    expect(more.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-rail-plugin-drawer]').exists()).toBe(false)
  })

  it('shows the more entry as soon as one plugin page is registered', () => {
    seedPluginPages(1)
    const single = mount(AppRail, { props: { active: 'chat' } })
    expect(single.findAll('[data-plugin-rail]')).toHaveLength(0)
    expect(single.find('[data-rail-plugin-more]').exists()).toBe(true)

    setPluginPageEntries([])
    const empty = mount(AppRail, { props: { active: 'chat' } })
    expect(empty.find('[data-rail-plugin-more]').exists()).toBe(false)
  })

  it('opens a transparent drawer on the right on hover and opens a folded page', async () => {
    seedPluginPages(5)
    const wrapper = mount(AppRail, { props: { active: 'chat' } })

    await wrapper.get('[data-rail-plugin-more-wrap]').trigger('mouseenter')

    const drawer = wrapper.get('[data-rail-plugin-drawer]')
    expect(drawer.classes()).toEqual(expect.arrayContaining(['app-rail__more-drawer', 'optical-glass']))
    expect(drawer.attributes('role')).toBe('menu')
    expect(wrapper.get('[data-rail-plugin-more]').attributes('aria-expanded')).toBe('true')
    expect(drawer.findAll('[data-rail-plugin-drawer-item]').map(item => item.attributes('data-rail-plugin-drawer-item'))).toEqual([
      'demo:a', 'demo:b', 'demo:c', 'demo:d', 'demo:e',
    ])
    expect(drawer.text()).toContain('页面 a')
    expect(drawer.text()).toContain('页面 e')

    await drawer.get('[data-rail-plugin-drawer-item="demo:a"]').trigger('click')
    expect(wrapper.emitted('open-plugin-page')?.[0]?.[0]).toMatchObject({ plugin: 'demo', id: 'a', title: '页面 a' })
    expect(wrapper.find('[data-rail-plugin-drawer]').exists()).toBe(false)
  })

  it('marks the more entry as pressed when the active plugin page is folded', () => {
    seedPluginPages(5)
    const wrapper = mount(AppRail, { props: { active: 'chat', activePluginPage: 'demo:e' } })

    expect(wrapper.get('[data-rail-plugin-more]').attributes('aria-pressed')).toBe('true')
  })
})

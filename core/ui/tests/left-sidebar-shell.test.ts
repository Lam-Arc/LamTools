import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LeftSidebarShell from '../src/components/LeftSidebarShell.vue'

const workspaceShellCss = readFileSync(
  resolve(import.meta.dirname, '../src/styles/workspace-shell.css'),
  'utf8',
)
const leftSidebarShellSource = readFileSync(
  resolve(import.meta.dirname, '../src/components/LeftSidebarShell.vue'),
  'utf8',
)

describe('LeftSidebarShell', () => {
  it('renders its four regions and supports the new slot names', () => {
    const wrapper = mount(LeftSidebarShell, {
      props: {
        id: 'left-drawer',
        open: true,
        pinned: true,
        title: '工作区',
      },
      slots: {
        'sidebar-header-action': '<button data-header-action>+</button>',
        primary: '<div data-primary>快捷入口</div>',
        'sidebar-body': '<div data-body>项目树</div>',
        'sidebar-footer': '<div data-footer>长期安排</div>',
      },
    })

    const drawer = wrapper.get('[data-workspace-left-drawer]')
    expect(drawer.attributes('id')).toBe('left-drawer')
    expect(drawer.classes()).toContain('open')
    expect(drawer.classes()).toContain('pinned')
    expect(wrapper.get('.sidebar-label').text()).toBe('工作区')
    expect(wrapper.find('[data-header-action]').exists()).toBe(true)
    expect(wrapper.get('[data-primary]').text()).toBe('快捷入口')
    expect(wrapper.get('[data-body]').text()).toBe('项目树')
    expect(wrapper.get('[data-footer]').text()).toBe('长期安排')
    expect(wrapper.get('.drawer-head')).toBeTruthy()
    expect(wrapper.get('.drawer-body')).toBeTruthy()
    expect(wrapper.get('.drawer-footer')).toBeTruthy()
  })

  it('marks a closed drawer inert and falls back to the default title', () => {
    const wrapper = mount(LeftSidebarShell, {
      props: {
        id: 'left-drawer',
        open: false,
        pinned: false,
      },
    })

    const drawer = wrapper.get('[data-workspace-left-drawer]')
    expect(drawer.classes()).not.toContain('open')
    expect(drawer.attributes('inert')).toBeDefined()
    expect(drawer.attributes('aria-hidden')).toBe('true')
    expect(wrapper.get('.sidebar-label').text()).toBe('项目')
  })

  it('can hide the optional header while keeping the drawer body and footer', () => {
    const wrapper = mount(LeftSidebarShell, {
      props: {
        id: 'left-drawer',
        open: true,
        pinned: false,
        showSidebarHeader: false,
      },
    })

    expect(wrapper.find('.drawer-head').exists()).toBe(false)
    expect(wrapper.get('.drawer-body')).toBeTruthy()
    expect(wrapper.get('.drawer-footer')).toBeTruthy()
  })

  it('emits host layout commands and keeps mouseleave at the shell root', async () => {
    const wrapper = mount(LeftSidebarShell, {
      props: {
        id: 'left-drawer',
        open: true,
        pinned: false,
      },
    })

    const exposed = wrapper.vm as unknown as {
      close: () => void
      togglePinned: () => void
    }
    exposed.close()
    exposed.togglePinned()
    await wrapper.get('[data-workspace-left-drawer]').trigger('mouseleave')

    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('toggle-pinned')).toHaveLength(1)
    expect(wrapper.emitted('mouseleave')).toHaveLength(1)
  })

  it('keeps only the left body scrollable', () => {
    expect(workspaceShellCss).toMatch(/--left-visible-width: min\(var\(--left-card-width\), var\(--main-left\)\);/)
    expect(workspaceShellCss).toMatch(/\.drawer-left \{[\s\S]*?width: var\(--left-visible-width\);/)
    expect(workspaceShellCss).toMatch(/\.drawer-left\.open \{[\s\S]*?width: var\(--left-card-width\);/)
    expect(workspaceShellCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?\.drawer-left \{[\s\S]*?width: var\(--sidebar-width\);[\s\S]*?\.drawer-left\.open \{[\s\S]*?transform: translateX\(0\);[\s\S]*?pointer-events: auto;/)
    expect(workspaceShellCss).toMatch(/\.drawer-left \{[\s\S]*?overflow: hidden;/)
    expect(workspaceShellCss).toMatch(/\.drawer-left \.drawer-head,[\s\S]*?\.drawer-left \.drawer-footer \{[\s\S]*?flex: 0 0 auto;/)
    expect(workspaceShellCss).toMatch(/\.drawer-left > \.sidebar-scroll-shell > \.drawer-body \{[\s\S]*?height: 100%;[\s\S]*?overflow-y: auto;[\s\S]*?overflow-x: hidden;/)
  })

  it('uses a keyboard-accessible custom scrollbar instead of the native one', () => {
    expect(leftSidebarShellSource).toContain('role="scrollbar"')
    expect(leftSidebarShellSource).toContain('@pointerdown="handleScrollbarPointerDown"')
    expect(leftSidebarShellSource).toContain('@keydown="handleScrollbarKeydown"')
    expect(workspaceShellCss).toMatch(/\.sidebar-body \{[\s\S]*?scrollbar-width: none;[\s\S]*?-ms-overflow-style: none;/)
    expect(workspaceShellCss).toMatch(/\.sidebar-body::-webkit-scrollbar \{[\s\S]*?display: none;/)
    expect(workspaceShellCss).toMatch(/\.sidebar-scrollbar \{[\s\S]*?position: absolute;[\s\S]*?pointer-events: none;/)
    expect(workspaceShellCss).toMatch(/\.sidebar-scrollbar\.is-visible \{[\s\S]*?pointer-events: auto;/)
  })

  it('uses the shared row recipe for fixed footer entries', () => {
    expect(workspaceShellCss).toMatch(/\.drawer-footer \{[\s\S]*?gap: var\(--sidebar-row-gap\);/)
    // 桌面页脚是一行图标入口；带文字的竖排行留给手机降级页脚。
    expect(workspaceShellCss).toMatch(/\.drawer-footer-row \{[\s\S]*?flex-direction: row;[\s\S]*?align-items: center;/)
    expect(workspaceShellCss).toMatch(/\.rail-action__button \{[\s\S]*?width: var\(--rail-action-size\);[\s\S]*?border-radius: var\(--sidebar-row-radius\);/)
    expect(workspaceShellCss).toMatch(/\.drawer-footer-account \{[\s\S]*?height: var\(--rail-action-size\);[\s\S]*?border-radius: var\(--sidebar-row-radius\);/)
    expect(workspaceShellCss).toMatch(/\.sidebar-action \{[\s\S]*?min-height: var\(--sidebar-row-height\);[\s\S]*?border-radius: var\(--sidebar-row-radius\);/)
  })

  it('can move search and settings out of the mobile sidebar without hiding plugins or slots', () => {
    const wrapper = mount(LeftSidebarShell, {
      props: {
        id: 'left-drawer',
        open: true,
        pinned: false,
        showSearchAction: false,
        showSettingsAction: false,
      },
      slots: {
        'sidebar-footer': '<div data-footer>长期安排</div>',
      },
    })

    expect(wrapper.find('[data-rail-action="search"]').exists()).toBe(false)
    expect(wrapper.find('[data-rail-action="settings"]').exists()).toBe(false)
    expect(wrapper.find('[data-rail-action="plugins"]').exists()).toBe(true)
    // 图标入口不带文字，标签只在悬浮提示里（提示行为由 DrawerFooterAction 提供）。
    expect(wrapper.get('[data-rail-action="plugins"]').text()).toBe('')
    expect(wrapper.get('[data-footer]').text()).toBe('长期安排')
  })

  it('omits the footer entirely when mobile actions and footer content are unavailable', () => {
    const wrapper = mount(LeftSidebarShell, {
      props: {
        id: 'left-drawer',
        open: true,
        pinned: false,
        showSearchAction: false,
        showPluginsAction: false,
        showSettingsAction: false,
      },
    })

    expect(wrapper.find('.drawer-footer').exists()).toBe(false)
  })
})

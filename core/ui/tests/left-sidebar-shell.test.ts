import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LeftSidebarShell from '../src/components/LeftSidebarShell.vue'

const workspaceShellCss = readFileSync(
  resolve(import.meta.dirname, '../src/styles/workspace-shell.css'),
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
        'header-actions': '<button data-header-action>+</button>',
        primary: '<div data-primary>快捷入口</div>',
        default: '<div data-body>项目树</div>',
        footer: '<div data-footer>长期安排</div>',
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
    expect(workspaceShellCss).toMatch(/\.drawer-left \{[\s\S]*?overflow: hidden;/)
    expect(workspaceShellCss).toMatch(/\.drawer-left \.drawer-head,[\s\S]*?\.drawer-left \.drawer-footer \{[\s\S]*?flex: 0 0 auto;/)
    expect(workspaceShellCss).toMatch(/\.drawer-left > \.drawer-body \{[\s\S]*?min-height: 0;[\s\S]*?overflow-y: auto;[\s\S]*?overflow-x: hidden;/)
  })

  it('uses the shared row recipe for fixed footer entries', () => {
    expect(workspaceShellCss).toMatch(/\.drawer-footer \{[\s\S]*?gap: var\(--sidebar-row-gap\);/)
    expect(workspaceShellCss).toMatch(/\.drawer-footer \.settings-entry \{[\s\S]*?min-height: var\(--sidebar-row-height\);[\s\S]*?border-radius: var\(--sidebar-row-radius\);/)
    expect(workspaceShellCss).toMatch(/\.sidebar-action \{[\s\S]*?min-height: var\(--sidebar-row-height\);[\s\S]*?border-radius: var\(--sidebar-row-radius\);/)
  })
})

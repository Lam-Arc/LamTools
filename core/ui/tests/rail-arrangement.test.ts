import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SettingsShell from '../src/components/SettingsShell.vue'
import SessionSidebar from '../src/components/SessionSidebar.vue'

const read = (relativePath: string): string => readFileSync(resolve(import.meta.dirname, '..', relativePath), 'utf8')
const appSource = read('src/app/LamToolsApp.vue')
const shellSource = read('src/components/LeftSidebarShell.vue')
const sidebarSource = read('src/components/SessionSidebar.vue')
const shellCss = read('src/styles/workspace-shell.css')
const sidebarCss = read('src/styles/session-sidebar.css')

const groups = [
  { id: 'docs', name: 'Docs', sessions: [{ id: 's1', title: 'Guide' }] },
]

describe('left rail entry arrangement', () => {
  it('renders no search chrome of its own on desktop and drops the empty slot row', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups: [], hasProjects: false },
      slots: { 'toolbar-actions': '<button data-toolbar-action>插件</button>' },
    })

    // 桌面：搜索是宿主放在侧栏顶部的图标入口，侧栏自己不再渲染。
    expect(wrapper.find('[data-sidebar-search]').exists()).toBe(false)
    expect(wrapper.find('[data-sidebar-search-action]').exists()).toBe(false)
    expect(wrapper.find('[data-sidebar-search-toggle]').exists()).toBe(false)

    // 有槽内容时工具栏行仍在；宿主不传槽时不再留空行。
    expect(wrapper.find('[data-toolbar-action]').exists()).toBe(true)
    expect(wrapper.get('.sidebar-toolbar').text()).toContain('插件')
    const bare = mount(SessionSidebar, { props: { projectGroups: groups } })
    expect(bare.find('.sidebar-toolbar').exists()).toBe(false)

    // 手机抽屉（local-filter）仍渲染可展开的过滤输入。
    const filtering = mount(SessionSidebar, { props: { projectGroups: groups, localFilter: true } })
    expect(filtering.find('[data-sidebar-search]').exists()).toBe(true)
    expect(filtering.find('[data-sidebar-search-action]').exists()).toBe(false)
  })

  it('keeps search in the sidebar top row and the four sections on the app rail', () => {
    expect(appSource).toContain(":local-filter=\"appRuntime.platform === 'mobile'\"")
    // 搜索入口在侧栏顶部（模式下拉同排）；工具栏槽只服务手机过滤输入。
    expect(appSource).toMatch(/data-sidebar-search-entry[\s\S]*?@click="openSearch"/)
    expect(appSource).not.toContain('#toolbar-actions')
    // 竖栏：聊天 + 四个整版分区（图标 only），底部账号。
    expect(appSource).toMatch(/#app-rail[\s\S]*?<AppRail[\s\S]*?@open="onRailOpen"/)
    const railSource = read('src/components/AppRail.vue')
    expect(railSource).toMatch(/\{ id: 'chat'[\s\S]*?\{ id: 'arrange'[\s\S]*?\{ id: 'library'[\s\S]*?\{ id: 'plugins'[\s\S]*?\{ id: 'settings'/)
    expect(railSource).toMatch(/data-rail-entry="account"/)
    expect(sidebarCss).toMatch(/\.sidebar-toolbar \{[\s\S]*?position: relative;/)
  })

  it('moves the account and settings entries off the desktop footer', () => {
    // 桌面页脚不再渲染：账号在竖栏底部，设置是竖栏里的一个图标。
    expect(appSource).toContain(':show-sidebar-search-action="showMobileFooterFallback"')
    expect(appSource).toContain(':show-sidebar-plugins-action="showMobileFooterFallback"')
    expect(appSource).toContain(':show-sidebar-settings-action="showMobileFooterFallback"')
    expect(appSource).toContain('const showSidebarFooter = computed(() => showMobileFooterFallback.value)')
    expect(appSource).not.toContain('class="drawer-footer-account"')
    const railSource = read('src/components/AppRail.vue')
    expect(railSource).toMatch(/data-rail-entry="account"[\s\S]*?@click="emit\('open', 'account'\)"/)
  })

  it('opens the account screen from the account entry, and settings from there', () => {
    expect(appSource).toMatch(/function openSettings\(section\?: string\): void \{[\s\S]*?settingsSection\.value = section/)
    // 账号有自己的界面（用户共识：内容先少放），竖栏底部入口直接开它。
    expect(appSource).toMatch(/function onRailOpen\(view: AppRailView\): void \{[\s\S]*?if \(view === 'account'\) \{[\s\S]*?openAccount\(\)/)
    expect(appSource).toMatch(/function openAccount\(\): void \{\s*openFullArea\('account'\)/)
    // 登录、注册、配对表单仍在设置里，由账号界面的链接过去。
    expect(appSource).toMatch(/function openAccountSettings\(\): void \{[\s\S]*?openSettings\('mobile-control'\)/)
    expect(appSource).toMatch(/<AccountShell[\s\S]*?:on-open-settings="openAccountSettings"/)
    expect(appSource).toContain(':section="settingsSection"')
  })

  it('leaves the mobile fallback footer on its labelled rows', () => {
    expect(appSource).toMatch(/class="drawer-footer-stack"[\s\S]*?data-mobile-footer-account[\s\S]*?data-mobile-footer-library[\s\S]*?data-mobile-footer-arrange/)
    expect(shellCss).toMatch(/\.drawer-footer-stack \{[\s\S]*?flex: 1 1 100%;[\s\S]*?flex-direction: column;/)
  })

  it('opens settings on the requested section and falls back to the first one', async () => {
    const sections = [
      { id: 'models', label: '模型与供应商' },
      { id: 'mobile-control', label: '手机控制' },
    ]
    const targeted = mount(SettingsShell, { props: { sections, initialSection: 'mobile-control' } })
    await targeted.vm.$nextTick()
    expect(targeted.get('[data-settings-section="mobile-control"]').classes()).toContain('active')

    // 未知 id 不能把设置开到一个空白页。
    const unknown = mount(SettingsShell, { props: { sections, initialSection: 'nope' } })
    await unknown.vm.$nextTick()
    expect(unknown.get('[data-settings-section="models"]').classes()).toContain('active')
  })

  it('exposes the rail action through the package entry', () => {
    expect(read('src/index.ts')).toContain("export { default as RailAction } from './components/RailAction.vue';")
    expect(sidebarSource).toContain('<slot name="toolbar-actions" />')
  })
})

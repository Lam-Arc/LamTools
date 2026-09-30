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
  it('renders no search chrome of its own on desktop and keeps the slot row', async () => {
    const wrapper = mount(SessionSidebar, {
      props: { projectGroups: [], hasProjects: false },
      slots: { 'toolbar-actions': '<button data-toolbar-action>插件</button>' },
    })

    // 桌面：搜索是宿主放在工具栏槽里的图标入口，侧栏自己不再渲染。
    expect(wrapper.find('[data-sidebar-search]').exists()).toBe(false)
    expect(wrapper.find('[data-sidebar-search-action]').exists()).toBe(false)
    expect(wrapper.find('[data-sidebar-search-toggle]').exists()).toBe(false)

    // 没有项目数据时这一行仍然在（入口属于应用级导航，不是列表装饰）。
    expect(wrapper.find('[data-toolbar-action]').exists()).toBe(true)
    expect(wrapper.get('.sidebar-toolbar').text()).toContain('插件')

    // 手机抽屉（local-filter）仍渲染可展开的过滤输入。
    const filtering = mount(SessionSidebar, { props: { projectGroups: groups, localFilter: true } })
    expect(filtering.find('[data-sidebar-search]').exists()).toBe(true)
    expect(filtering.find('[data-sidebar-search-action]').exists()).toBe(false)
  })

  it('keeps search, library, the long-term schedule and plugins in the rail toolbar row', () => {
    // 一排同规格图标：搜索、资料库、长期安排、插件都是工具栏槽里的 RailAction。
    expect(appSource).toContain(":local-filter=\"appRuntime.platform === 'mobile'\"")
    expect(appSource).toContain('#toolbar-actions')
    expect(appSource).toMatch(/action-id="search"[\s\S]*?action-id="library"[\s\S]*?action-id="arrange"[\s\S]*?action-id="plugins"/)
    expect(appSource).toMatch(/action-id="plugins"[\s\S]*?tip-placement="below"/)
    // 顶部行向下展开提示（向上会被 drawer 顶边裁掉），底部行向上展开。
    expect(shellCss).toContain('.rail-action__tip--below { top: 100%; }')
    expect(sidebarCss).toMatch(/\.sidebar-toolbar \{[\s\S]*?position: relative;/)
  })

  it('keeps the account display and settings as the only footer entries', () => {
    // 桌面：左栏自己的设置入口 + 宿主提供的账号条。
    expect(shellSource).toMatch(/class="drawer-footer-row"[\s\S]*?action-id="settings"/)
    expect(appSource).toContain('class="drawer-footer-account"')
    expect(appSource).toContain('data-sidebar-account')
    expect(appSource).toMatch(/class="drawer-footer-account"[\s\S]*?\{\{ accountLabel \}\}/)
    // 搜索与插件入口交给工具栏行，不再由左栏页脚渲染。
    expect(appSource).toContain(':show-sidebar-search-action="showMobileFooterFallback"')
    expect(appSource).toContain(':show-sidebar-plugins-action="showMobileFooterFallback"')
    expect(appSource).toContain(':show-sidebar-settings-action="appRuntime.platform !== \'mobile\' || showMobileFooterFallback"')
    expect(shellCss).toMatch(/\.drawer-footer-account \{[\s\S]*?height: var\(--rail-action-size\);[\s\S]*?text-overflow: ellipsis;/)
  })

  it('opens the account screen from the account entry, and settings from there', () => {
    expect(appSource).toMatch(/function openSettings\(section\?: string\): void \{[\s\S]*?settingsSection\.value = section/)
    // 账号有自己的界面（用户共识：内容先少放），页脚入口直接开它。
    expect(appSource).toContain('@click="openAccount"')
    expect(appSource).toMatch(/function openAccount\(\): void \{\s*openFullArea\('account'\)/)
    // 登录、注册、配对表单仍在设置里，由账号界面的链接过去。
    expect(appSource).toMatch(/function openAccountSettings\(\): void \{[\s\S]*?openSettings\('mobile-control'\)/)
    expect(appSource).toMatch(/<AccountShell[\s\S]*?:on-open-settings="openAccountSettings"/)
    expect(appSource).toContain(':section="settingsSection"')
  })

  it('leaves the mobile fallback footer on its labelled rows', () => {
    expect(appSource).toMatch(/v-if="showMobileFooterFallback" class="drawer-footer-stack"[\s\S]*?data-mobile-footer-account[\s\S]*?data-mobile-footer-library[\s\S]*?data-mobile-footer-arrange/)
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

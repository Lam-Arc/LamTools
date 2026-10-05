import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import CoreArrangeManager from '../src/components/CoreArrangeManager.vue'
import SearchShell from '../src/components/SearchShell.vue'

const read = (relativePath: string): string => readFileSync(resolve(import.meta.dirname, '..', relativePath), 'utf8')
const appSource = read('src/app/LamToolsApp.vue')
const topBarSource = read('src/components/MobileTopBar.vue')
const shellCss = read('src/styles/layout.css')

/**
 * 整版界面（搜索 / 资料库 / 定时任务）：三个入口互斥地占住聊天区域，
 * 不再是悬浮卡片；桌面与手机都是同一套。
 */
describe('full-area views (搜索 / 资料库 / 定时任务)', () => {
  it('switches one full-area view at a time and hides the composer while open', () => {
    expect(appSource).toMatch(/type FullAreaViewId = 'library' \| 'search' \| 'arrange' \| 'settings' \| 'plugins' \| 'account' \| 'project'/)
    expect(appSource).toMatch(/const fullAreaView = ref<FullAreaViewId \| null>\(null\)/)
    expect(appSource).toMatch(/function openFullArea\(view: FullAreaViewId\): void \{[\s\S]*?fullAreaView\.value = fullAreaView\.value === view \? null : view/)
    expect(appSource).toMatch(/function closeFullArea\(\): void \{\s*fullAreaView\.value = null/)

    // The views mount inside #main-content, mutually exclusive by the ref.
    expect(appSource).toMatch(/<template v-if="fullAreaView">[\s\S]*?<CoreArrangeManager[\s\S]*?v-if="showArrange"[\s\S]*?<SearchShell[\s\S]*?v-else-if="showSearch"[\s\S]*?<LibraryHomeView[\s\S]*?v-else-if="showLibrary"[\s\S]*?<CoreSettings[\s\S]*?v-else-if="showSettings"[\s\S]*?<PluginsShell[\s\S]*?v-else-if="showPlugins"[\s\S]*?<AccountShell[\s\S]*?v-else-if="showAccount"/)
    // Each one's back path closes the full-area state.
    expect(appSource).toMatch(/<CoreArrangeManager[\s\S]*?@back="closeFullArea"/)
    expect(appSource).toMatch(/<SearchShell[\s\S]*?@close="closeFullArea"/)
    // 资料库是一个入口三个分区（资料 / 记忆 / 方案），壳视图承担整版机制与返回路径。
    expect(appSource).toMatch(/<LibraryHomeView[\s\S]*?v-else-if="showLibrary"[\s\S]*?@back="closeFullArea"/)

    // A full-area view owns the area: the composer and plugin surface step aside.
    expect(appSource).toMatch(/shouldHideComposer = computed\(\(\) => Boolean\(fullAreaView\.value\) \|\|/)
    expect(appSource).toMatch(/v-show="!pluginUsesCoreThread && !fullAreaView"/)
    expect(appSource).toMatch(/v-if="!fullAreaView && !activePluginMode && showCoreStartPage"/)
    expect(shellCss).toMatch(/\.full-area-view \{[\s\S]*?overflow-y: auto;/)
  })

  it('routes the app rail and the mobile entries to the three openers', () => {
    // 最左竖栏：主页回聊天，四个分区走同一族整版界面，账号进账号页。
    expect(appSource).toMatch(/#app-rail[\s\S]*?<AppRail :active="railActiveView" @open="onRailOpen" \/>/)
    expect(appSource).toMatch(/function onRailOpen\(view: AppRailView\): void \{[\s\S]*?closeFullArea\(\)[\s\S]*?openAccount\(\)[\s\S]*?openFullArea\(view\)/)
    expect(appSource).toMatch(/const railActiveView = computed<AppRailView>\(\(\) => \{/)

    expect(appSource).toMatch(/data-mobile-footer-library @click="openLibrary"/)
    // 设置 / 插件 / 账号也走同一族整版界面。
    expect(appSource).toMatch(/function openSettings\(section\?: string\): void \{[\s\S]*?openFullArea\('settings'\)/)
    expect(appSource).toMatch(/function openPlugins\(section\?: string\): void \{[\s\S]*?openFullArea\('plugins'\)/)
    expect(appSource).toMatch(/function openAccount\(\): void \{[\s\S]*?openFullArea\('account'\)/)
    expect(topBarSource).toMatch(/data-mobile-library-button @click="runAction\('open-library'\)"/)
    expect(topBarSource).toMatch(/emit\('open-library'\)/)
  })

  it('imports every icon the rail and the dock render', () => {
    // 一个未导入的图标会渲染成空组件：入口在 DOM 里、但完全看不见。
    const lucideBlock = appSource.slice(0, appSource.indexOf("} from 'lucide-vue-next'"))
    const searchEntry = appSource.slice(
      appSource.indexOf('data-sidebar-search-entry'),
      appSource.indexOf('</button>', appSource.indexOf('data-sidebar-search-entry')),
    )
    const searchIcons = [...searchEntry.matchAll(/<([A-Z][A-Za-z0-9]*)\s+:size=/g)].map(match => match[1])
    expect(searchIcons).toEqual(['Search'])
    for (const icon of searchIcons) {
      expect(lucideBlock, `${icon} is rendered in the sidebar top row but not imported`).toMatch(
        new RegExp(`(^|\r?\n)  ${icon},(\r?\n|$)`),
      )
    }

    // 竖栏自带图标：渲染用到的每一个都要在它自己的导入里。
    // 竖栏现在跨两家图标库（lucide 的线性 + IconPark 的 book-one），所以两边都要查。
    const appRailSource = read('src/components/AppRail.vue')
    const railImports = appRailSource.slice(0, appRailSource.indexOf('export type AppRailView'))
    const railEntryIcons = [...appRailSource.matchAll(/\{ id: '[a-z]+'[\s\S]*?icon: ([A-Z][A-Za-z0-9]*)/g)].map(match => match[1])
    expect(railEntryIcons).toEqual(expect.arrayContaining(['House', 'CalendarClock', 'BookOne', 'Receive', 'Settings']))
    for (const icon of [...railEntryIcons, 'UserRound']) {
      expect(railImports.includes(icon), `${icon} is used in AppRail but not imported`).toBe(true)
    }

    const topBarLucide = topBarSource.slice(0, topBarSource.indexOf("} from 'lucide-vue-next'"))
    const dockIcons = [...topBarSource.matchAll(/<([A-Z][A-Za-z0-9]*)\s+:size=/g)].map(match => match[1])
    expect(dockIcons).toEqual(expect.arrayContaining(['Search', 'Library']))
    for (const icon of dockIcons) {
      expect(topBarLucide.includes(icon), `${icon} is rendered in the dock but not imported`).toBe(true)
    }
  })

  it('carries the view title and the back button in the header band', () => {
    // 顶部标题跟着界面走（不再停留在会话标题上），返回键就在标题原来的位置。
    // 设置 / 插件例外：页名与会话栏里的分区列表已经说明一切，不再重复标题条；
    // 整版界面这一层仍然独占顶部，不会被插件自带的头部顶替。
    expect(appSource).toMatch(/v-if="appRuntime\.platform !== 'mobile' && fullAreaView"[\s\S]*?v-if="!sidebarNavView"[\s\S]*?data-full-area-header/)
    expect(appSource).toMatch(/data-full-area-back[\s\S]*?@click="onFullAreaBack"/)
    expect(appSource).toMatch(/data-full-area-title/)
    expect(appSource).toMatch(/case 'search':[\s\S]*?title: '搜索'/)
    expect(appSource).toMatch(/case 'library':[\s\S]*?title: '资料库'/)
    expect(appSource).toMatch(/case 'arrange':[\s\S]*?title: '定时任务'/)

    // 桌面不再在界面内部重复标题与返回键（手机没有顶部条，保留内部的）。
    expect(read('src/components/CoreArrangeManager.vue')).toMatch(/@media \(min-width: 641px\) \{[\s\S]*?\.arrange-mobile-head/)
    expect(read('src/components/SearchShell.vue')).toMatch(/@media \(min-width: 641px\) \{[\s\S]*?\.search-back/)
    expect(read('src/components/AccountShell.vue')).toMatch(/@media \(min-width: 641px\) \{[\s\S]*?\.account-back/)
    expect(read('src/components/PlanLibraryView.vue')).toContain('FullAreaActions')
  })

  it('no longer teleports the arrange manager or the search shell as overlays', () => {
    const arrangeSource = read('src/components/CoreArrangeManager.vue')
    const searchSource = read('src/components/SearchShell.vue')
    for (const source of [arrangeSource, searchSource]) {
      expect(source).not.toContain('<Teleport')
      expect(source).not.toContain('useOutsidePointerDismiss')
      expect(source).not.toContain('settings-overlay')
    }
    // 各自的页内返回键：定时任务是返回（子页先回列表），搜索是返回会话。
    expect(arrangeSource).toMatch(/aria-label="返回"/)
    expect(searchSource).toContain('返回会话')
    // 各自的退出键：安排是文档级 Esc，搜索是输入框上的 Esc。
    expect(arrangeSource).toContain("key === 'Escape'")
    expect(searchSource).toContain('@keydown.esc')
  })

  it('closes the arrange view with Esc and keeps the search input inside the page', async () => {
    const arrange = mount(CoreArrangeManager, {
      props: { requestRpc: async () => ({ jobs: [], scheduler_notice: '' }) },
      global: { stubs: { UiSelect: true } },
    })
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(arrange.emitted('back')).toHaveLength(1)

    const search = mount(SearchShell, {
      props: {
        requestRpc: async () => ({}),
        sessions: [],
        onJump: () => {},
        commands: [],
      },
    })
    // 输入框在页内，而不是悬浮卡片里；返回按钮同排。
    expect(search.find('.search-view').exists()).toBe(true)
    expect(search.get('input').attributes('placeholder')).toContain('搜索')
    await search.get('.search-back').trigger('click')
    expect(search.emitted('close')).toHaveLength(1)
  })
})

describe('settings/plugins/project borrow the session drawer as their left nav', () => {
  it('keeps the drawer open for settings/plugins/project and hosts the vertical section nav there', () => {
    // 会话栏只在搜索/资料库/定时任务/账号时收起；这三个页面让给它当侧栏。
    expect(appSource).toContain(':collapse-left-sidebar="Boolean(fullAreaView && !sidebarNavView)"')
    expect(appSource).toMatch(/const sidebarNavView = computed<'settings' \| 'plugins' \| 'project' \| null>\(\(\) => \{[\s\S]*?return null[\s\S]*?\}\)/)
    // 页名顶替模式下拉的位置；搜索入口与新建项目行同时让位。
    expect(appSource).toMatch(/data-sidebar-nav-title[\s\S]*?>\{\{ sidebarNavTitle \}\}<\/span>/)
    expect(appSource).toMatch(/const sidebarNavTitle = computed\(\(\) => \{[\s\S]*?case 'settings':[\s\S]*?return '设置'[\s\S]*?case 'plugins':[\s\S]*?return '插件'[\s\S]*?case 'project':[\s\S]*?return '项目'/)
    expect(appSource).toMatch(/v-if="!sidebarNavView && appRuntime.platform !== 'mobile'"[\s\S]*?class="core-sidebar-search-entry"/)
    expect(appSource).toContain('<div v-if="!sidebarNavView" class="core-project-primary-row">')
    // 会话栏主体换成竖排分区导航（同一份分区清单，不带描述小字）。
    expect(appSource).toMatch(/<FullAreaSidebarNav[\s\S]*?v-if="sidebarNavView === 'settings'"[\s\S]*?:sections="CORE_SETTINGS_SECTIONS"[\s\S]*?:active-id="settingsSection"[\s\S]*?@select="settingsSection = \$event"/)
    expect(appSource).toMatch(/<FullAreaSidebarNav[\s\S]*?v-else-if="sidebarNavView === 'plugins'"[\s\S]*?:sections="PLUGIN_SHELL_SECTIONS"[\s\S]*?:active-id="pluginsSection"/)
    expect(appSource).toMatch(/<FullAreaSidebarNav[\s\S]*?v-else-if="sidebarNavView === 'project'"[\s\S]*?:sections="PROJECT_SETTINGS_SECTIONS"[\s\S]*?:active-id="projectSettingsSection"[\s\S]*?@select="projectSettingsSection = \$event"/)
  })

  it('drives the shells from one shared section list and hides their built-in nav on desktop', () => {
    const shellSource = read('src/components/SettingsShell.vue')
    const settingsSource = read('src/components/CoreSettings.vue')
    const pluginsSource = read('src/components/PluginsShell.vue')
    const projectSource = read('src/components/CoreProjectSettings.vue')
    const registrySource = read('src/components/settingsSections.ts')
    // 唯一权威清单：三套壳与导航组件同源。
    expect(registrySource).toMatch(/export const CORE_SETTINGS_SECTIONS: SettingsSection\[\]/)
    expect(registrySource).toMatch(/export const PLUGIN_SHELL_SECTIONS: SettingsSection\[\]/)
    expect(registrySource).toMatch(/export const PROJECT_SETTINGS_SECTIONS: SettingsSection\[\]/)
    expect(settingsSource).toContain('const sections = CORE_SETTINGS_SECTIONS')
    expect(pluginsSource).toContain('const sections = PLUGIN_SHELL_SECTIONS')
    expect(projectSource).toContain('const sections = PROJECT_SETTINGS_SECTIONS')
    // 桌面上内置导航退场，分区状态与宿主会话栏双向同步。
    expect(shellSource).toMatch(/<aside v-if="!props.hideNav" class="settings-sidebar">/)
    expect(shellSource).toMatch(/watch\(\(\) => props\.activeSection, \(id\) => \{[\s\S]*?activeSection\.value = id/)
    expect(shellSource).toMatch(/if \(activeSection\.value\) emit\('section-change', activeSection\.value\)/)
    for (const pageSource of [settingsSource, pluginsSource, projectSource]) {
      expect(pageSource).toContain(':hide-nav="props.hideNav"')
      expect(pageSource).toContain("@section-change=\"$emit('section-change', $event)\"")
    }
    // 主卡不再为标题条留那条高度：内容直接顶到页面顶部（只留一点上沿留白）。
    expect(appSource).toContain(':hide-main-header="Boolean(sidebarNavView)"')
    expect(read('src/styles/layout.css')).toMatch(/\.workspace-main--no-header \{\s*padding-top: var\(--space-4\);\s*\}/)
    expect(read('src/components/WorkspaceShell.vue')).toContain("'workspace-main--no-header': hideMainHeader")
    // 打开一页 / 换分区都回到顶部：滚动容器保留的旧位置会让人以为内容被裁掉了。
    expect(shellSource).toContain('ref="settingsMainEl"')
    expect(shellSource).toMatch(/function resetScrollPosition\(\) \{[\s\S]*?scrollTop = 0[\s\S]*?\}/)
    expect(shellSource).toMatch(/watch\(activeSection, async \(\) => \{[\s\S]*?resetScrollPosition\(\)/)
    expect(shellSource).toMatch(/onMounted\(async \(\) => \{[\s\S]*?resetScrollPosition\(\)[\s\S]*?await nextTick\(\)[\s\S]*?resetScrollPosition\(\)/)
    // 导航行只有名称与图标，没有描述小字。
    const navSource = read('src/components/FullAreaSidebarNav.vue')
    expect(navSource).toContain('data-nav-section')
    expect(navSource).not.toMatch(/description/)
  })

  it('opens 项目设置 as a full-area page instead of a floating window', () => {
    const projectSource = read('src/components/CoreProjectSettings.vue')
    // 浮窗的皮全部剥掉：没有传送、没有遮罩卡片、没有点外关闭。
    expect(projectSource).not.toContain('<Teleport')
    expect(projectSource).not.toContain('settings-overlay')
    expect(projectSource).not.toContain('useOutsidePointerDismiss')
    expect(projectSource).toContain('class="full-area-column full-area-surface"')
    // 入口变成整版界面：不再有独立的浮窗开关，打开即切走整个界面。
    expect(appSource).toMatch(/v-else-if="showProjectView && selectedProject && !activePluginMode"/)
    expect(appSource).not.toContain('showProjectSettings')
    expect(appSource).toMatch(/function openProjectActions\(projectId: string\) \{[\s\S]*?openFullArea\('project'\)/)
    // 项目设置是聊天项目的内页：竖栏仍停在聊天区。
    expect(appSource).toMatch(/view === 'search' \|\| view === 'project'\) return 'chat'/)
  })
})

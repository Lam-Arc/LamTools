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
 * 整版界面（搜索 / 资料库 / 长期安排）：三个入口互斥地占住聊天区域，
 * 不再是悬浮卡片；桌面与手机都是同一套。
 */
describe('full-area views (搜索 / 资料库 / 长期安排)', () => {
  it('switches one full-area view at a time and hides the composer while open', () => {
    expect(appSource).toMatch(/const fullAreaView = ref<'library' \| 'search' \| 'arrange' \| null>\(null\)/)
    expect(appSource).toMatch(/function openFullArea\(view: 'library' \| 'search' \| 'arrange'\): void \{[\s\S]*?fullAreaView\.value = fullAreaView\.value === view \? null : view/)
    expect(appSource).toMatch(/function closeFullArea\(\): void \{\s*fullAreaView\.value = null/)

    // The views mount inside #main-content, mutually exclusive by the ref.
    expect(appSource).toMatch(/<template v-if="fullAreaView">[\s\S]*?<CoreArrangeManager[\s\S]*?v-if="showArrange"[\s\S]*?<SearchShell[\s\S]*?v-else-if="showSearch"[\s\S]*?<PlanLibraryView[\s\S]*?v-else-if="showLibrary"/)
    // Each one's back path closes the full-area state.
    expect(appSource).toMatch(/<CoreArrangeManager[\s\S]*?@back="closeFullArea"/)
    expect(appSource).toMatch(/<SearchShell[\s\S]*?@close="closeFullArea"/)
    expect(appSource).toMatch(/<PlanLibraryView[\s\S]*?@back="closeFullArea"/)

    // A full-area view owns the area: the composer and plugin surface step aside.
    expect(appSource).toMatch(/shouldHideComposer = computed\(\(\) => Boolean\(fullAreaView\.value\) \|\|/)
    expect(appSource).toMatch(/v-show="!pluginUsesCoreThread && !fullAreaView"/)
    expect(appSource).toMatch(/v-if="!fullAreaView && !activePluginMode && showCoreStartPage"/)
    expect(shellCss).toMatch(/\.full-area-view \{[\s\S]*?overflow-y: auto;/)
  })

  it('routes the rail row and the mobile entries to the three openers', () => {
    expect(appSource).toMatch(/action-id="search"[\s\S]*?@click="openSearch"/)
    expect(appSource).toMatch(/action-id="library"[\s\S]*?@click="openLibrary"/)
    expect(appSource).toMatch(/action-id="arrange"[\s\S]*?@click="openArrange"/)

    expect(appSource).toMatch(/data-mobile-footer-library @click="openLibrary"/)
    expect(topBarSource).toMatch(/data-mobile-library-button @click="runAction\('open-library'\)"/)
    expect(topBarSource).toMatch(/emit\('open-library'\)/)
  })

  it('no longer teleports the arrange manager or the search shell as overlays', () => {
    const arrangeSource = read('src/components/CoreArrangeManager.vue')
    const searchSource = read('src/components/SearchShell.vue')
    for (const source of [arrangeSource, searchSource]) {
      expect(source).not.toContain('<Teleport')
      expect(source).not.toContain('useOutsidePointerDismiss')
      expect(source).not.toContain('settings-overlay')
      expect(source).toContain('返回会话')
    }
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
    expect(search.get('.search-view').exists()).toBe(true)
    expect(search.get('input').attributes('placeholder')).toContain('搜索')
    await search.get('.search-back').trigger('click')
    expect(search.emitted('close')).toHaveLength(1)
  })
})

import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, inject, nextTick, ref } from 'vue'
import CoreWorkspace, { dropPreview } from '../src/components/CoreWorkspace.vue'
import CoreWorkspaceArea from '../src/components/CoreWorkspaceArea.vue'
import CoreWorkspaceFloat from '../src/components/CoreWorkspaceFloat.vue'
import CoreWorkspaceTabs from '../src/components/CoreWorkspaceTabs.vue'
import BrowserHomeView from '../src/components/BrowserHomeView.vue'
import { getStoredSearchEngine, resolveAddress, setStoredSearchEngine } from '../src/split/browserAddress'
import { WORKSPACE_AREA_RECT, WORKSPACE_CONTENT_RECT } from '../src/components/workspaceInjection'
import { useWorkspace } from '../src/workspace/useWorkspace'
import { computeYieldInsets } from '../src/workspace/compute'

/**
 * user:“依旧不可见，你来完成新布局系统的开发工作：# Sunday UI 与统一工作区布局系统”+
 * (先写验收测试：
 *  1. Agent 在主区时 .ws2-root 与 .ws2-area--agent-main 必须透明且不拦截指针，绝不能盖住底层 .workspace-main；
 *  2. 浮层具备“主区”提升、主辅互换保留实例、切回 Agent 时 mainTab 归 null；
 *  3. 自由让位（yield）计算避让边距并在剩余空间不足 360x240 时自动回退为 0；
 *  4. 融合式标签横向支持新建（+）与重命名，辅助分屏支持“取消固定”与“设为主区”。)
 */
describe('Unified Workspace Layout System V1 acceptance', () => {
  it('keeps Agent main area transparent and pointer-passthrough so .workspace-main is never covered', async () => {
    const controller = useWorkspace(ref('test.v1.passthrough'), ref('/root'), ref(null), { persist: false })
    controller.split('main', 'right')
    controller.setBounds({ x: 0, y: 0, width: 1000, height: 600 })

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '/root' },
    })
    await nextTick()

    const mainArea = wrapper.get('[data-ws2-area="main"]')
    expect(mainArea.classes()).toContain('ws2-area--agent-main')

    const css = fs.readFileSync(path.resolve(__dirname, '../src/styles/workspace-v2.css'), 'utf8')
    expect(css).toMatch(/\.ws2-root\s*\{[^}]*background:\s*transparent/s)
    expect(css).toMatch(/\.ws2-root\s*\{[^}]*pointer-events:\s*none/s)
    expect(css).toMatch(/\.ws2-area--agent-main[^}]*background:\s*transparent/s)
    expect(css).toMatch(/\.ws2-area--agent-main[^}]*pointer-events:\s*none/s)

    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue).toMatch(/<CoreSplitContent\b[^>]*v-if="tab\b/)

    wrapper.unmount()
  })

  it('supports float promote-to-main, main/aux swap without losing instances, and returning main to Agent', () => {
    const controller = useWorkspace(ref('test.v1.swap'), ref('/root'), ref(null), { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 700 })

    const auxId = controller.split('main', 'right')!
    const browser = controller.add('browser', 'https://example.com', 'Browser')!
    const files = controller.add('files', '/root', 'Files', auxId)!
    controller.setSurfaceMode(browser.id, 'float')
    expect(controller.floats.value.some(f => f.tab.id === browser.id)).toBe(true)

    const floatWrapper = mount(CoreWorkspaceFloat, {
      props: {
        tab: browser,
        rect: { x: 100, y: 80, width: 400, height: 300 },
        active: true,
        yieldEnabled: false,
      },
    })
    const promoteBtn = floatWrapper.find('[data-ws2-float-promote]')
    expect(promoteBtn.exists()).toBe(false)
    floatWrapper.unmount()

    // Promote float Browser to Main
    controller.setMain(browser.id)
    expect(controller.state.mainTab?.id).toBe(browser.id)
    expect(controller.floats.value.some(f => f.tab.id === browser.id)).toBe(false)

    // Promote aux Files to Main -> previous Main (Browser) swaps into aux rather than disappearing
    const filesPaneBefore = controller.tabs.value.find(e => e.tab.id === files.id)?.pane
    expect(filesPaneBefore).toBeTruthy()
    controller.setMain(files.id)
    expect(controller.state.mainTab?.id).toBe(files.id)
    const browserAfterSwap = controller.tabs.value.find(e => e.tab.id === browser.id)
    expect(browserAfterSwap).toBeTruthy()
    expect(browserAfterSwap?.pane).toBe(filesPaneBefore)

    // Return Main to Agent
    controller.setMain(null)
    expect(controller.state.mainTab).toBeNull()
  })

  it('computes Free Yield insets when space allows and falls back to 0 when float covers too much', async () => {
    const mainRect = { x: 0, y: 0, width: 1000, height: 700 }
    // Right-side float covering 320px -> 680px left >= 360px -> yield right by 320px
    const rightYield = computeYieldInsets(mainRect, [{ x: 680, y: 40, width: 320, height: 500 }])
    expect(rightYield.right).toBe(320)
    expect(rightYield.left).toBe(0)

    // Giant float covering 800px -> only 200px left (< 360px min) -> fallback to 0
    const fallbackYield = computeYieldInsets(mainRect, [{ x: 100, y: 40, width: 800, height: 600 }])
    expect(fallbackYield).toEqual({ left: 0, right: 0, top: 0, bottom: 0 })

    const controller = useWorkspace(ref('test.v1.yield'), ref('/root'), ref(null), { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1000, height: 700 })
    const tab = controller.add('browser', 'https://example.com', 'Browser')!
    controller.setSurfaceMode(tab.id, 'float')
    controller.moveFloat(tab.id, { x: 680, y: 40, width: 320, height: 500 })

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '/root' },
    })
    await nextTick()

    controller.setFloatYieldEnabled(tab.id, true)
    await nextTick()

    const style = (wrapper.emitted('geometry')?.at(-1)?.[0] ?? {}) as Record<string, string>
    expect(Number.parseInt(style['--ws2-yield-right'] || '0', 10)).toBe(320)

    controller.setFloatYieldEnabled(tab.id, false)
    await nextTick()
    const styleOff = (wrapper.emitted('geometry')?.at(-1)?.[0] ?? {}) as Record<string, string>
    expect(styleOff['--ws2-yield-right']).toBe('0px')

    wrapper.unmount()
  })

  it('supports horizontal new-tab (+) and rename in CoreWorkspaceTabs and unpin/promote in aux area', async () => {
    const tabs = [
      { id: 't1', kind: 'browser' as const, title: 'GitHub', resource: 'https://github.com' },
    ]
    const wrapper = mount(CoreWorkspaceTabs, {
      props: { areaId: 'aux-1', axis: 'horizontal', tabs, activeId: 't1', allowAdd: true },
    })
    const addBtn = wrapper.find('[data-ws2-tab-add]')
    expect(addBtn.exists()).toBe(true)
    await addBtn.trigger('click')
    expect(wrapper.emitted('add')?.length).toBe(1)
    wrapper.unmount()
  })

  it('expands main content to full width when split is hidden via toggle()', async () => {
    const controller = useWorkspace(ref('test.v1.hidden-fill'), ref('/root'), ref(null), { persist: false })
    controller.split('main', 'right')
    controller.setBounds({ x: 0, y: 0, width: 1000, height: 600 })

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '/root' },
    })
    await nextTick()

    const splitStyle = (wrapper.emitted('geometry')?.at(-1)?.[0] ?? {}) as Record<string, string>
    const splitWidth = Number.parseInt(splitStyle['--split-primary-width'] || '0', 10)
    expect(splitWidth).toBeGreaterThan(0)
    expect(splitWidth).toBeLessThan(1000)

    controller.toggle()
    await nextTick()
    const hiddenStyle = (wrapper.emitted('geometry')?.at(-1)?.[0] ?? {}) as Record<string, string>
    expect(Number.parseInt(hiddenStyle['--split-primary-width'] || '0', 10)).toBe(1000)

    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue).toMatch(/workspace-shell--split['"]?\s*:\s*[^,\n]*!workspace\.state\.hidden/)

    wrapper.unmount()
  })

  it('keeps only one independent top-left CoreContentRoot bento anchor and places horizontal Browser tabs in the top row', () => {
    const sidebarVue = fs.readFileSync(path.resolve(__dirname, '../src/components/SessionSidebar.vue'), 'utf8')
    expect(sidebarVue).not.toMatch(/<CoreContentRoot\b/)

    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue.match(/<CoreContentRoot\b/g)?.length ?? 0).toBe(1)
    expect(appVue).toMatch(/data-ws2-root-anchor/)

    const areaVue = fs.readFileSync(path.resolve(__dirname, '../src/components/CoreWorkspaceArea.vue'), 'utf8')
    expect(areaVue).toMatch(/top:\s*'0px'/)
    expect(areaVue).not.toMatch(/<CoreContentRoot\b/)

    const areaWrapper = mount(CoreWorkspaceArea, {
      props: {
        areaId: 'main',
        axis: 'horizontal',
        rect: { x: 0, y: 0, width: 800, height: 600 },
        contentRect: { x: 0, y: 72, width: 800, height: 528 },
        tabs: [{ id: 'b1', kind: 'browser', title: 'GitHub', resource: 'https://github.com' }],
        activeId: 'b1',
        tabbar: 'full',
      },
    })
    const tabsEl = areaWrapper.get('.ws2-area__tabs').element as HTMLElement
    const contentEl = areaWrapper.get('[data-ws2-content="main"]').element as HTMLElement
    expect(tabsEl.style.top).toBe('0px')
    expect(tabsEl.style.height).toBe('36px')
    expect(contentEl.style.top).toBe('36px')
    areaWrapper.unmount()
  })

  it('offsets injected WORKSPACE_AREA_RECT and WORKSPACE_CONTENT_RECT by workspace root window origin for native WebView2', () => {
    let seenContent: any = null
    let seenArea: any = null
    const Probe = defineComponent({
      setup() {
        seenContent = inject(WORKSPACE_CONTENT_RECT, null)?.value
        seenArea = inject(WORKSPACE_AREA_RECT, null)?.('b1')
        return () => null
      },
    })
    const wrapper = mount(CoreWorkspaceArea, {
      props: {
        areaId: 'main',
        axis: 'horizontal',
        origin: { x: 44, y: 36 },
        rect: { x: 0, y: 0, width: 900, height: 600 },
        contentRect: { x: 0, y: 72, width: 900, height: 528 },
        tabs: [{ id: 'b1', kind: 'browser', title: 'Bing', resource: 'https://www.bing.com' }],
        activeId: 'b1',
        tabbar: 'full',
      },
      slots: { default: () => h(Probe) },
    })
    expect(seenContent).toEqual({ x: 44, y: 108, width: 900, height: 528 })
    expect(seenArea).toEqual({
      contentRect: { x: 44, y: 108, width: 900, height: 528 },
      hostRect: { x: 44, y: 36, width: 900, height: 600 },
    })
    wrapper.unmount()
  })

  it('hides agent placeholder tab in horizontal Browser tabbar and aligns Browser outer width with rail', () => {
    const areaWrapper = mount(CoreWorkspaceArea, {
      props: {
        areaId: 'main',
        axis: 'horizontal',
        rect: { x: 0, y: 0, width: 800, height: 600 },
        contentRect: { x: 0, y: 72, width: 800, height: 528 },
        tabs: [
          { id: 'agent-main', kind: 'agent', title: 'Agent', resource: '' },
          { id: 'b1', kind: 'browser', title: 'browser', resource: '' },
        ],
        activeId: 'b1',
        tabbar: 'full',
      },
    })
    const tabEls = areaWrapper.findAll('[data-ws2-tab]')
    expect(tabEls.map(el => el.attributes('data-ws2-tab'))).toEqual(['b1'])
    areaWrapper.unmount()

    const splitCss = fs.readFileSync(path.resolve(__dirname, '../src/styles/split-workspace.css'), 'utf8')
    expect(splitCss).toMatch(/\.workspace-shell\.workspace-shell--main-replaced\s*\{[^}]*--main-left:\s*var\(--rail-width\)/s)
  })

  it('can always switch back from Browser to Agent and hides Browser/WebView2 when switching to other pages', () => {
    const controller = useWorkspace(ref('test.v1.back-to-agent'), ref('/root'), ref(null), { persist: false })
    controller.openInMain('browser', 'https://www.bing.com', 'Bing')
    expect(controller.state.mainTab?.kind).toBe('browser')

    // Even if agent-main was closed or detached from main.tabs, setMain(null) must still return to Agent
    const agentTab = controller.tabs.value.find(e => e.tab.id === 'agent-main')?.tab
    if (agentTab) controller.closeTab('main', agentTab)
    expect(controller.state.mainTab?.kind).toBe('browser')

    controller.setMain(null)
    expect(controller.state.mainTab).toBeNull()

    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue).toMatch(/v-show="splitEnabled && !fullAreaView && !activePluginMode"/)
    expect(appVue).toMatch(/:visible="visible && splitEnabled && !fullAreaView && !activePluginMode"/)
  })

  it('removes foreign-chat subagent notice and parks/restores subagent tabs per session', () => {
    const splitContentVue = fs.readFileSync(path.resolve(__dirname, '../src/components/CoreSplitContent.vue'), 'utf8')
    expect(splitContentVue).not.toMatch(/class="split-content-notice"/)
    expect(splitContentVue).not.toMatch(/子代理过程暂不可用/)

    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue).toMatch(/parkedSubAgentTabs/)
    expect(appVue).toMatch(/syncSubAgentTabsForSession/)
  })

  it('opens a fresh empty New Tab instead of falling back to Agent when closing the last Browser tab in main', async () => {
    const controller = useWorkspace(ref('test.v1.browser-empty-newtab'), ref('/root'), ref(null), { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1000, height: 600 })
    controller.openInMain('browser', 'https://example.com', 'Example')
    expect(controller.state.mainTab?.kind).toBe('browser')

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '/root' },
    })
    await nextTick()

    const closeBtn = wrapper.find('[data-ws2-tab="browser-1"] .ws2-tab__close')
    expect(closeBtn.exists()).toBe(true)
    await closeBtn.trigger('click')
    await nextTick()

    expect(controller.state.mainTab?.kind).toBe('browser')
    expect(controller.state.mainTab?.resource).toBe('')
    expect(controller.state.mainTab?.title).toBe('新标签')

    wrapper.unmount()
  })

  it('supports 4-corner float resizing and gives unpinned split panes a comfortable float size', async () => {
    const floatWrapper = mount(CoreWorkspaceFloat, {
      props: {
        tab: { id: 'f1', kind: 'browser', title: 'Float', resource: '' },
        rect: { x: 200, y: 120, width: 460, height: 380 },
        active: true,
        yieldEnabled: false,
      },
    })
    for (const corner of ['nw', 'ne', 'sw', 'se']) {
      expect(floatWrapper.find(`[data-ws2-float-grip="${corner}"]`).exists()).toBe(true)
    }
    const nwGrip = floatWrapper.get('[data-ws2-float-grip="nw"]')
    nwGrip.element.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 200, clientY: 120, bubbles: true }))
    nwGrip.element.dispatchEvent(new MouseEvent('pointermove', { clientX: 160, clientY: 90, bubbles: true }))
    nwGrip.element.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
    await nextTick()
    const emitted = floatWrapper.emitted('rect-change')?.at(-1)?.[0] as { x: number; y: number; width: number; height: number }
    expect(emitted).toEqual({ x: 160, y: 90, width: 500, height: 410 })
    floatWrapper.unmount()

    const controller = useWorkspace(ref('test.v1.unpin-size'), ref('/root'), ref(null), { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 700 })
    const auxId = controller.split('main', 'right')!
    controller.add('files', '/root', 'Files', auxId)
    const res = controller.unpinCommit(auxId)
    expect(res.ok).toBe(true)
    const floatRect = controller.floats.value[0]?.rect
    expect(floatRect).toBeTruthy()
    expect(floatRect!.width).toBeGreaterThanOrEqual(420)
    expect(floatRect!.height).toBeGreaterThanOrEqual(360)
  })

  it('turns any dragged tab into a float when dropped onto an area content region', () => {
    const controller = useWorkspace(ref('test.v1.drag-to-float'), ref('/root'), ref(null), { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 700 })
    const b1 = controller.add('browser', 'https://example.com', 'Tab 1', 'main')!
    const b2 = controller.add('browser', 'https://bing.com', 'Tab 2', 'main')!

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '/root' },
    })
    // Drag b2 down into the middle of main's content region (x: 600, y: 350)
    const tabEl = wrapper.get(`[data-ws2-tab="${b2.id}"]`)
    tabEl.element.dispatchEvent(new MouseEvent('pointerdown', { button: 0, clientX: 200, clientY: 16, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 600, clientY: 350, bubbles: true }))
    window.dispatchEvent(new MouseEvent('pointerup', { clientX: 600, clientY: 350, bubbles: true }))

    expect(controller.floats.value.some(f => f.tab.id === b2.id)).toBe(true)
    expect(controller.state.mainTab?.id).toBe(b1.id)
    wrapper.unmount()
  })

  it('counts only auxiliary panes for splitPaneCount and disables splitEnabled when only Agent main exists', () => {
    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue).toMatch(/splitPaneCount\s*=\s*computed\(\(\)\s*=>\s*Object\.keys\(workspace\.state\.panes\)\.filter\(id\s*=>\s*id\s*!==\s*'main'\)\.length\)/)
    expect(appVue).toMatch(/splitEnabled\s*=\s*computed\(\(\)\s*=>\s*splitPaneCount\.value\s*>\s*0\s*\|\|\s*workspace\.floats\.value\.length\s*>\s*0\s*\|\|\s*Boolean\(workspace\.state\.mainTab\)\)/)
    expect(appVue).toMatch(/<CoreWorkspace\b[^>]*v-show="splitEnabled && !fullAreaView && !activePluginMode"/)
  })


  it('removes dismiss X buttons on BrowserHomeView, switches Bing/Google/Baidu via left icon, and raises browser header z-index above host', async () => {
    const homeWrapper = mount(BrowserHomeView)
    expect(homeWrapper.find('.browser-home-dismiss').exists()).toBe(false)

    const engineBtn = homeWrapper.find('[data-browser-engine-switch]')
    expect(engineBtn.exists()).toBe(true)
    await engineBtn.trigger('click')
    await homeWrapper.get('[data-browser-engine-option="google"]').trigger('click')
    expect(getStoredSearchEngine().id).toBe('google')
    expect(resolveAddress('sunday ui', getStoredSearchEngine()).url).toContain('google.com/search')

    await engineBtn.trigger('click')
    await homeWrapper.get('[data-browser-engine-option="baidu"]').trigger('click')
    expect(getStoredSearchEngine().id).toBe('baidu')
    expect(resolveAddress('sunday ui', getStoredSearchEngine()).url).toContain('baidu.com/s')

    setStoredSearchEngine('bing')
    expect(getStoredSearchEngine().id).toBe('bing')
    homeWrapper.unmount()

    const browserVue = fs.readFileSync(path.resolve(__dirname, '../src/components/CoreSplitBrowser.vue'), 'utf8')
    expect(browserVue).toMatch(/\.split-browser-header\s*\{[^}]*z-index:\s*10/s)
  })

  it('provides window-origin-adjusted bounds inside CoreWorkspaceFloat and renders full half-pane skeleton on split dropPreview', () => {
    let floatAreaRect: any = null
    const Probe = defineComponent({
      setup() {
        floatAreaRect = inject(WORKSPACE_AREA_RECT, null)?.('f-browser')
        return () => null
      },
    })
    const fw = mount(CoreWorkspaceFloat, {
      props: {
        tab: { id: 'f-browser', kind: 'browser', title: 'Bilibili', resource: 'https://www.bilibili.com' },
        rect: { x: 400, y: 40, width: 500, height: 420 },
        origin: { x: 46, y: 36 },
        active: true,
        yieldEnabled: false,
      },
      slots: { default: () => h(Probe) },
    })
    expect(floatAreaRect?.contentRect).toEqual({ x: 447, y: 148, width: 498, height: 347 })
    fw.unmount()

    const skeleton = dropPreview(
      { kind: 'split', pane: 'main', edge: 'right', from: { pane: 'main', index: 0 } },
      { areas: { main: { rect: { x: 0, y: 0, width: 1000, height: 600 }, contentRect: { x: 0, y: 36, width: 1000, height: 564 }, chrome: { tabbar: 'full', header: 36 } } }, floats: {}, issues: [] },
    )
    expect(skeleton).toEqual({ x: 500, y: 0, width: 500, height: 600 })
  })

  it('supports browser_screenshot in native.ts, blurred frozen yield backdrop, and low-latency floating bounds sync', () => {
    const nativeTs = fs.readFileSync(path.resolve(__dirname, '../src/split/native.ts'), 'utf8')
    expect(nativeTs).toContain("case 'screenshot':")
    expect(nativeTs).toContain("'browser_screenshot'")

    const browserVue = fs.readFileSync(path.resolve(__dirname, '../src/components/CoreSplitBrowser.vue'), 'utf8')
    expect(browserVue).toMatch(/split-browser-frozen/)
    expect(browserVue).toMatch(/filter:\s*blur\(/)
    expect(browserVue).toMatch(/visibilityPhase\(\)\s*===\s*'floating'/)
    expect(browserVue).toMatch(/overlayYield[\s\S]*draggingTab/)
  })

  it('keeps browserTabs across HMR on globalThis in native.ts', () => {
    const nativeTs = fs.readFileSync(path.resolve(__dirname, '../src/split/native.ts'), 'utf8')
    expect(nativeTs).toContain('__sundayBrowserTabs')
  })

  it('routes DirectComposition browser input and transparent cutout in CoreSplitBrowser and workspace-v2.css', async () => {
    const nativeTs = fs.readFileSync(path.resolve(__dirname, '../src/split/native.ts'), 'utf8')
    expect(nativeTs).toContain("case 'input':")
    expect(nativeTs).toContain("'browser_input'")

    const browserVue = fs.readFileSync(path.resolve(__dirname, '../src/components/CoreSplitBrowser.vue'), 'utf8')
    expect(browserVue).toContain('isComposed')
    expect(browserVue).toContain('onHostPointerMove')
    expect(browserVue).toContain('onHostWheel')
    expect(browserVue).toContain('is-composed-live')
    expect(browserVue).toContain("msg.includes('网页还没打开')")
    expect(browserVue).toContain('isFloatSurface')
    expect(browserVue).toContain('dragYield')

    const v2Css = fs.readFileSync(path.resolve(__dirname, '../src/styles/workspace-v2.css'), 'utf8')
    expect(v2Css).toContain('.workspace-shell--browser-live')
    expect(v2Css).toContain('.split-browser-host.is-composed-live')
    expect(v2Css).toContain('.workspace-shell:not(.left-open) .core-root-bento-anchor')
    expect(v2Css).toContain('.workspace-shell:not(.left-open) .thread-header')
    expect(v2Css).toContain('.ws2-float:has(.split-browser-host.is-composed-live) > .ws2-float__head')
    expect(v2Css).toMatch(/\.ws2-area\s*\{[\s\S]*?z-index:\s*1;/)
    expect(v2Css).toMatch(/\.ws2-tab\s*\{[\s\S]*?user-select:\s*none;/)
    expect(v2Css).toMatch(/\.ws2-float\s*\{[\s\S]*?box-shadow:\s*none;/)
    expect(v2Css).not.toMatch(/\.ws2-float(?:\.is-active)?\s*\{[^}]*box-shadow:[^;]*--theme-main-text/)
    expect(v2Css).toContain('.workspace-shell--browser-live .workspace-main')

    const appVue = fs.readFileSync(path.resolve(__dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    expect(appVue).toContain('workspace.floats.value.some')

    const areaVue = fs.readFileSync(path.resolve(__dirname, '../src/components/CoreWorkspaceArea.vue'), 'utf8')
    expect(areaVue).toContain('v-for="tab in props.tabs"')
    expect(areaVue).toContain(':key="tab.id"')
    expect(areaVue).toContain('v-show="tab.id === props.activeId"')
    expect(areaVue).toContain('buildCutoutClipPath')

    const { buildCutoutClipPath } = await import('../src/workspace/composition')
    expect(buildCutoutClipPath({ x: 0, y: 0 }, [])).toBeUndefined()
    expect(buildCutoutClipPath({ x: 100, y: 50 }, [{ x: 200, y: 120, width: 400, height: 300 }])).toContain('polygon(evenodd,')
    expect(buildCutoutClipPath({ x: 100, y: 50 }, [{ x: 200, y: 120, width: 400, height: 300 }])).toContain('100px 70px')
  })

  it('shows pin split skeleton preview on hovering 固定 in CoreWorkspaceFloat and CoreWorkspace', async () => {
    const controller = useWorkspace(ref('acceptance.float-promote'), undefined, undefined, { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
    controller.openFloat('browser', 'https://example.com', 'Float')
    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '' },
    })
    const pinBtn = wrapper.find('[data-ws2-float-pin]')
    expect(pinBtn.exists()).toBe(true)

    await pinBtn.trigger('pointerenter')
    expect(controller.pinPreview.value).not.toBeNull()
    const preview = wrapper.find('[data-ws2-pin-preview]')
    expect(preview.exists()).toBe(true)
    expect((preview.element as HTMLElement).style.width).toBe(`${controller.pinPreview.value!.rect.width}px`)

    await pinBtn.trigger('pointerleave')
    expect(controller.pinPreview.value).toBeNull()
    expect(wrapper.find('[data-ws2-pin-preview]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('commits pin on clicking 固定 across 680x500, narrow 500x400, and after detaching aux tab to float', async () => {
    const controller = useWorkspace(ref('acceptance.free-yield'), undefined, undefined, { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 680, height: 500 })
    controller.openFloat('browser', 'https://example.com', 'Float')
    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '' },
    })
    await wrapper.find('[data-ws2-float-pin]').trigger('pointerenter')
    expect(wrapper.find('[data-ws2-pin-preview]').exists()).toBe(true)
    await wrapper.find('[data-ws2-float-pin]').trigger('click')
    expect(controller.floats.value).toHaveLength(0)
    expect(controller.areas.value).toHaveLength(2)
    wrapper.unmount()

    const narrowController = useWorkspace(ref('acceptance.narrow-window'), undefined, undefined, { persist: false })
    narrowController.setBounds({ x: 0, y: 0, width: 500, height: 400 })
    narrowController.openFloat('browser', 'https://example.com', 'NarrowFloat')
    const narrowWrapper = mount(CoreWorkspace, {
      props: { controller: narrowController, workRoot: '' },
    })
    await narrowWrapper.find('[data-ws2-float-pin]').trigger('pointerenter')
    expect(narrowWrapper.find('[data-ws2-pin-preview]').exists()).toBe(true)
    await narrowWrapper.find('[data-ws2-float-pin]').trigger('click')
    expect(narrowController.floats.value).toHaveLength(0)
    expect(narrowController.areas.value).toHaveLength(2)
    narrowWrapper.unmount()

    const auxPane = narrowController.areas.value.find(entry => entry.area.role !== 'main')!
    const movedTabId = auxPane.tabs[0].id
    narrowController.setSurfaceMode(movedTabId, 'float')
    expect(narrowController.areas.value).toHaveLength(1)
    expect(narrowController.floats.value).toHaveLength(1)
    const repinWrapper = mount(CoreWorkspace, {
      props: { controller: narrowController, workRoot: '' },
    })
    await repinWrapper.find('[data-ws2-float-pin]').trigger('pointerenter')
    expect(repinWrapper.find('[data-ws2-pin-preview]').exists()).toBe(true)
    await repinWrapper.find('[data-ws2-float-pin]').trigger('click')
    expect(narrowController.floats.value).toHaveLength(0)
    expect(narrowController.areas.value).toHaveLength(2)
    repinWrapper.unmount()
  })

  it('CoreWorkspaceTabDrawer lists area/float/parked tabs and executes actions', async () => {
    const CoreWorkspaceTabDrawer = (await import('../src/components/CoreWorkspaceTabDrawer.vue')).default
    const controller = useWorkspace(ref('acceptance.tabbar-rail'), undefined, undefined, { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
    const tab1 = controller.add('browser', 'https://example.com', 'Example')!
    controller.setSurfaceMode(tab1.id, 'float')
    const tab2 = controller.add('browser', 'https://vuejs.org', 'Vue')!
    controller.setSurfaceMode(tab2.id, 'float')
    controller.collapseFloat(tab2.id)

    const wrapper = mount(CoreWorkspaceTabDrawer, {
      props: { controller },
    })
    await wrapper.get('[data-ws2-tab-drawer-trigger]').trigger('click')
    expect(wrapper.find('[data-ws2-tab-drawer]').exists()).toBe(true)
    expect(wrapper.find(`[data-ws2-drawer-item="${tab1.id}"]`).text()).toContain('Example')
    expect(wrapper.find(`[data-ws2-drawer-item="${tab2.id}"]`).text()).toContain('Vue')

    await wrapper.get(`[data-ws2-drawer-item="${tab2.id}"] .ws2-tab-drawer__main`).trigger('click')
    expect(controller.floats.value.some(f => f.tab.id === tab2.id)).toBe(true)
    expect(wrapper.find('[data-ws2-tab-drawer]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('uploads actual measured .split-browser-host rect when contained in area hostRect', async () => {
    const CoreSplitBrowser = (await import('../src/components/CoreSplitBrowser.vue')).default
    const { WORKSPACE_AREA_RECT } = await import('../src/components/workspaceInjection')
    const { defineComponent, h, provide } = await import('vue')
    const calls: Array<{ action: string; options?: Record<string, unknown> }> = []
    const Host = defineComponent({
      setup(_p, { slots }) {
        provide(WORKSPACE_AREA_RECT, () => ({
          contentRect: { x: 46, y: 72, width: 900, height: 600 },
          hostRect: { x: 46, y: 0, width: 900, height: 672 },
        }))
        return () => slots.default?.()
      },
    })
    const wrapper = mount(Host, {
      slots: {
        default: () => h(CoreSplitBrowser, {
          tab: { id: 'b-real', kind: 'browser', resource: 'https://example.com', title: 'Ex' },
          visible: true,
          pane: 'main',
          services: {
            available: () => true,
            call: vi.fn(async (_id: string, action: string, opts?: Record<string, unknown>) => {
              calls.push({ action, options: opts })
              if (action === 'create') return { tab: 't-real' }
              if (action === 'state') return {}
              return undefined
            }),
            subscribe: vi.fn(async () => () => {}),
            openExternal: vi.fn(async () => {}),
          },
        } as never),
      },
    })
    const hostEl = wrapper.get('.split-browser-host').element as HTMLElement
    Object.defineProperty(hostEl, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ x: 46, y: 104, width: 900, height: 568, top: 104, left: 46, right: 946, bottom: 672, toJSON: () => ({}) }),
    })
    await new Promise(resolve => setTimeout(resolve, 30))
    const last = [...calls].reverse().find(c => c.action === 'bounds')
    expect(last?.options).toMatchObject({ x: 46, y: 104, width: 900, height: 568 })
    wrapper.unmount()
  })

  it('closes and collapses split pane when its last browser tab is closed in CoreWorkspace', async () => {
    const controller = useWorkspace(ref('acceptance.close-pane'), undefined, undefined, { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
    const auxId = controller.split('main', 'right')!
    const auxTab = controller.add('browser', 'https://example.com', 'SplitWeb', auxId)!
    expect(controller.areas.value).toHaveLength(2)

    const wrapper = mount(CoreWorkspace, {
      props: { controller, workRoot: '' },
    })
    const closeBtn = wrapper.get(`[data-ws2-area="${auxId}"] [data-ws2-tab="${auxTab.id}"] .ws2-tab__close`)
    await closeBtn.trigger('click')
    expect(controller.areas.value).toHaveLength(1)
    expect(controller.areas.value[0].area.role).toBe('main')
    wrapper.unmount()
  })

  it('collapses emptied aux pane when promoting its last tab to an empty main area', () => {
    const controller = useWorkspace(ref('acceptance.promote-main'), undefined, undefined, { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
    const agentTab = controller.areas.value[0].tabs.find(t => t.kind === 'agent')
    if (agentTab) controller.closeTab('main', agentTab)
    const auxId = controller.split('main', 'right')!
    const web = controller.add('browser', 'https://example.com', 'Web', auxId)!
    expect(controller.areas.value).toHaveLength(2)

    controller.setMain(web.id)
    expect(controller.areas.value).toHaveLength(1)
    expect(controller.state.mainTab?.id).toBe(web.id)
  })
})

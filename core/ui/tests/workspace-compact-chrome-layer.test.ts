// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { h, ref } from 'vue'
import CoreSplitBrowser from '@/components/CoreSplitBrowser.vue'
import CoreWorkspace from '@/components/CoreWorkspace.vue'
import CoreWorkspaceTabDrawer from '@/components/CoreWorkspaceTabDrawer.vue'
import WorkspaceShell from '@/components/WorkspaceShell.vue'
import WindowControls from '@/components/TitleBar.vue'
import { disjointCutouts, workspaceFloatCutouts } from '@/workspace/composition'
import { useWorkspace } from '@/workspace/useWorkspace'
import type { SplitTab } from '@/workspace/types'

const actions = vi.hoisted(() => ({
  minimize: vi.fn(async () => {}),
  toggleMaximize: vi.fn(async () => {}),
  close: vi.fn(async () => {}),
}))
vi.mock('@tauri-apps/api/core', async importOriginal => ({
  ...await importOriginal<typeof import('@tauri-apps/api/core')>(),
  isTauri: () => true,
}))
vi.mock('@tauri-apps/api/window', () => ({ getCurrentWindow: () => actions }))

describe('Sunday compact window chrome', () => {
  it('keeps only three native window buttons and publishes no titlebar offset', async () => {
    const wrapper = mount(WindowControls)
    expect(wrapper.find('.titlebar').exists()).toBe(false)
    expect(wrapper.findAll('button')).toHaveLength(3)
    expect(wrapper.find('[data-tauri-drag-region]').exists()).toBe(true)
    expect(document.documentElement.style.getPropertyValue('--titlebar-native-height')).toBe('')
    for (const [button, command] of Object.entries({ minimize: 'minimize', maximize: 'toggleMaximize', close: 'close' }) as [string, keyof typeof actions][]) {
      await wrapper.get(`[data-window-control="${button}"]`).trigger('click')
      expect(actions[command]).toHaveBeenCalledOnce()
    }
    wrapper.unmount()
  })

  it('keeps the project sidebar open until manually toggled and offers a visible reopen button', async () => {
    const wrapper = mount(WorkspaceShell, {
      attachTo: document.body,
      props: { productName: 'Sunday', platform: 'desktop', compactChrome: true, hideComposer: true },
      slots: { 'app-rail': '<nav data-app-rail><button>导航</button></nav>', 'root-entry': 'Agent' },
    })
    expect(wrapper.classes()).toContain('left-open')
    const toggle = wrapper.get('[data-project-sidebar-toggle]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    await wrapper.get('.drawer-left').trigger('mouseleave', { relatedTarget: wrapper.get('main').element })
    await wrapper.get('main').trigger('pointerdown')
    await wrapper.get('main').trigger('keydown', { key: 'Escape' })
    expect(wrapper.classes()).toContain('left-open')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.classes()).not.toContain('left-open')
    await wrapper.get('.edge-left').trigger('mouseenter')
    await wrapper.get('.edge-left').trigger('focus')
    expect(wrapper.classes()).not.toContain('left-open')
    await wrapper.setProps({ collapseLeftSidebar: true })
    expect(wrapper.find('[data-project-sidebar-toggle]').exists()).toBe(false)
    await wrapper.setProps({ collapseLeftSidebar: false })
    expect(wrapper.get('[data-project-sidebar-toggle]').attributes('aria-expanded')).toBe('false')
    await wrapper.get('[data-project-sidebar-toggle]').trigger('click')
    expect(wrapper.classes()).toContain('left-open')
    wrapper.unmount()
  })
})

describe('native webpage and float stacking', () => {
  const web = { x: 120, y: 85, width: 200, height: 160 }
  const second = { x: 200, y: 120, width: 170, height: 80 }
  it('opens webpage holes only in surfaces behind each live webpage', () => {
    const live = new Map([['web', web], ['second', second]])
    expect(workspaceFloatCutouts(['files', 'web', 'front', 'second'], live, 'files')).toEqual([web, second])
    expect(workspaceFloatCutouts(['files', 'web', 'front', 'second'], live, 'web')).toEqual([second])
    expect(workspaceFloatCutouts(['files', 'web', 'front', 'second'], live, 'second')).toEqual([])
    expect(workspaceFloatCutouts(['web', 'files'], live, 'files')).toEqual([])
  })

  it('cuts the union: intersecting webpage rectangles never fill each other back in', () => {
    const holes = disjointCutouts([web, second])
    for (const [x, y, expected] of [[150, 100, 1], [220, 150, 1], [350, 150, 1], [370, 150, 0]]) {
      expect(holes.filter(r => x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height)).toHaveLength(expected)
    }
  })

  it('keeps the tab drawer outside the workspace and switches the whole webpage above or below the files float', async () => {
    const controller = useWorkspace(ref('compact-stack'), undefined, undefined, { persist: false })
    controller.setBounds({ x: 0, y: 0, width: 1200, height: 800 })
    const files = controller.add('files', '', 'Files', 'main')!
    controller.setSurfaceMode(files.id, 'float')
    const web = controller.add('browser', 'https://example.test', 'Web', 'main')!
    controller.setSurfaceMode(web.id, 'float')
    controller.moveFloat(files.id, { x: 150, y: 100, width: 600, height: 470 })
    controller.moveFloat(web.id, { x: 220, y: 160, width: 600, height: 470 })
    const call = vi.fn(async (_id: string, _action: string, _args?: Record<string, unknown>) => undefined)
    const services = { available: () => true, call, subscribe: async () => () => {}, openExternal: async () => {} }
    vi.stubGlobal('__TAURI_INTERNALS__', {})
    const wrapper = mount(WorkspaceShell, {
      attachTo: document.body,
      props: { productName: 'Sunday', platform: 'desktop', compactChrome: true, hideComposer: true },
      slots: {
        'workspace-overlays': () => h(CoreWorkspaceTabDrawer, { controller }),
        'main-content': () => h(CoreWorkspace, { controller, workRoot: '' }, {
          default: (slot: { tab: SplitTab; pane: string; visible: boolean }) => slot.tab.kind === 'browser'
            ? h(CoreSplitBrowser, { ...slot, controller, services }) : h('div', 'Files'),
        }),
      },
    })
    const float = (id: string) => wrapper.get<HTMLElement>(`[data-ws2-float="${id}"]`)
    try {
      await flushPromises()
      await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
      await flushPromises()
      await wrapper.get('.ws2-tab-drawer-trigger').trigger('click')
      expect(wrapper.get('.workspace-chrome-overlays .ws2-tab-drawer').element.closest('main')).toBeNull()
      expect(float(files.id).element.style.clipPath).toContain('evenodd')
      expect(float(web.id).element.style.clipPath).toBe('')
      expect(call.mock.calls.some(([id, action, args]) => id === web.id && action === 'bounds' && args?.stackIndex === 2)).toBe(true)

      controller.focusFloat(files.id)
      await flushPromises()
      expect(float(files.id).element.style.clipPath).toBe('')
      expect(call.mock.calls.some(([id, action, args]) => id === web.id && action === 'bounds' && args?.stackIndex === 1)).toBe(true)
    } finally {
      wrapper.unmount()
      vi.unstubAllGlobals()
    }
  })

  it('forwards the same stacking rank to the native compositor', () => {
    const source = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')
    expect(source('../src/components/CoreSplitBrowser.vue')).toContain('stackIndex')
    expect(source('../src/split/native.ts')).toContain('stackIndex')
    expect(source('../../desktop/src-tauri/src/browser/mod.rs')).toContain('set_stacked_bounds')
    // user:“浮层网页层级不对，被分屏遮挡了”+(合成层改成“总序重排 + 加到最上层”的显式方向，
    //  reorder_visual 的相对插入已下线：这里断言当前真正决定层级的两个入口)。
    expect(source('../../desktop/src-tauri/src/browser/compositor.rs')).toContain('stack_order')
    expect(source('../../desktop/src-tauri/src/browser/compositor.rs')).toContain('add_visual_on_top')
  })
})

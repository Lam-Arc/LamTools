import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'
import CoreWorkspaceArea from '@/components/CoreWorkspaceArea.vue'
import CoreWorkspaceTabs from '@/components/CoreWorkspaceTabs.vue'
import { useShellLayout } from '@/composables/useShellLayout'
import { useWorkspace } from '@/workspace/useWorkspace'
import type { SplitTab } from '@/workspace/types'

// user:“找出 3 个及以上优化，并给出下三个候选”+(验收桌面标签导航、溢出和侧栏宽度)。
const tabs: SplitTab[] = Array.from({ length: 8 }, (_, index) => ({
  id: `tab-${index}`, title: `Tab ${index + 1}`, kind: 'editor', resource: '',
}))
const cleanups: (() => void)[] = []

afterEach(() => {
  for (const cleanup of cleanups.splice(0).reverse()) cleanup()
  localStorage.clear()
})

function mountTabs(axis: 'horizontal' | 'vertical') {
  const wrapper = mount(CoreWorkspaceTabs, {
    attachTo: document.body,
    props: { axis, tabs, areaId: 'test', activeId: tabs[0].id },
  })
  cleanups.push(() => wrapper.unmount())
  return wrapper
}

describe('desktop workspace tabs', () => {
  it('uses one tab stop and keeps close separate from the selectable tab', async () => {
    const wrapper = mountTabs('horizontal')
    const controls = wrapper.findAll<HTMLElement>('[role="tab"]')
    expect(controls.filter(tab => tab.element.tabIndex === 0)).toHaveLength(1)
    const close = wrapper.get<HTMLButtonElement>('.ws2-tab__close')
    expect(close.element.closest('[role="tab"]')).toBeNull()
    expect(close.element.tabIndex).toBe(0)
    expect(wrapper.findAll('.ws2-tab__close[tabindex="0"]')).toHaveLength(1)
    controls[0].element.focus()
    await controls[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('select')?.at(-1)).toEqual([tabs[1].id])
    expect(document.activeElement).toBe(controls[1].element)
    await wrapper.setProps({ activeId: tabs[1].id })
    expect(controls[1].element.tabIndex).toBe(0)
    await controls[1].trigger('keydown', { key: 'End' })
    expect(wrapper.emitted('select')?.at(-1)).toEqual([tabs.at(-1)?.id])
    await controls.at(-1)?.trigger('keydown', { key: 'Home' })
    expect(document.activeElement).toBe(controls[0].element)
    await wrapper.setProps({ activeId: tabs[0].id })
    close.element.focus()
    await close.trigger('click')
    expect(wrapper.emitted('close')?.at(-1)).toEqual([tabs[0].id])
    await wrapper.setProps({ tabs: tabs.slice(1), activeId: tabs[1].id })
    await nextTick()
    expect(document.activeElement).toBe(controls[1].element)
  })

  it('gives sub-agent split tabs and pane actions a visible header above the content', async () => {
    const wrapper = mount(defineComponent({
      setup() {
        const workspace = useWorkspace(ref('test'), undefined, undefined, { persist: false })
        workspace.setBounds({ x: 0, y: 0, width: 1200, height: 700 })
        const pane = workspace.split('main', 'right')!
        workspace.add('editor', '', 'Notes', pane)
        workspace.add('agent', 'child-session', 'Sub-agent', pane)
        return () => {
          const { area, geometry } = workspace.areas.value.find(entry => entry.area.id === pane)!
          return h(CoreWorkspaceArea, {
            areaId: pane, axis: area.axis, activeId: area.active, tabs: workspace.state.panes[pane].tabs,
            rect: geometry!.rect, contentRect: geometry!.contentRect, tabbar: geometry!.chrome.tabbar,
            onSelect: id => workspace.activate(pane, id),
          })
        }
      },
    }))
    cleanups.push(() => wrapper.unmount())
    const header = wrapper.get<HTMLElement>('.ws2-area__tabs')
    const content = wrapper.get<HTMLElement>('.ws2-area__content')
    expect(header.classes()).toContain('ws2-area__tabs--horizontal')
    expect(Number.parseFloat(header.element.style.height)).toBeGreaterThan(0)
    expect(content.element.style.top).toBe(header.element.style.height)
    expect(header.find('[data-ws2-area-close]').exists()).toBe(true)
    await wrapper.get('[aria-label="Notes"]').trigger('click')
    expect(wrapper.get('[aria-label="Notes"]').attributes('aria-selected')).toBe('true')
    expect(header.classes()).toContain('ws2-area__tabs--horizontal')
  })
})

describe('desktop sidebar width', () => {
  it('constrains a saved width in a narrow window and restores it as the window grows', async () => {
    const originalWidth = window.innerWidth
    cleanups.push(() => { window.innerWidth = originalWidth })
    const resize = async (width: number) => {
      window.innerWidth = width
      window.dispatchEvent(new Event('resize'))
      await nextTick()
    }
    await resize(700)
    localStorage.setItem('desktop-layout-test', JSON.stringify({ leftWidth: 480 }))
    let layout!: ReturnType<typeof useShellLayout>
    const wrapper = mount(defineComponent({
      setup() {
        layout = useShellLayout({ platform: 'desktop', storageKey: 'desktop-layout-test' })
        return () => h('div', { style: layout.shellStyle.value })
      },
    }))
    cleanups.push(() => wrapper.unmount())
    await nextTick()
    const sidebarWidth = () => Number.parseFloat(wrapper.element.style.getPropertyValue('--sidebar-width'))
    expect(sidebarWidth()).toBe(340)
    layout.saveSettings()
    expect(JSON.parse(localStorage.getItem('desktop-layout-test')!).leftWidth).toBe(480)
    await resize(1200)
    expect(sidebarWidth()).toBe(480)
    await resize(650)
    expect(sidebarWidth()).toBe(290)
    await resize(1200)
    expect(sidebarWidth()).toBe(480)
  })
})

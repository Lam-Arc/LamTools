// @vitest-environment jsdom
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { expect, it, vi } from 'vitest'
import CoreWorkspaceTabs from '@/components/CoreWorkspaceTabs.vue'
import type { SplitTab } from '@/workspace/types'

it('switches from titles to icons, pages over overflow, and closes the selected tab only', async () => {
  let width = 840
  let onResize: () => void = () => {}
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { onResize = callback }
    observe() {}
    disconnect() {}
  })
  const geometry = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    () => new DOMRect(0, 0, width, 36),
  )
  const tabs = Array.from({ length: 8 }, (_, index): SplitTab => ({
    id: `tab-${index}`, kind: 'browser', title: `Page ${index}`, resource: '',
  }))
  const wrapper = mount(CoreWorkspaceTabs, { props: { areaId: 'main', axis: 'horizontal', tabs, activeId: tabs[0].id } })
  try {
    await nextTick()
    expect(wrapper.findAll('.ws2-tab__title')).toHaveLength(8)
    expect(wrapper.find('[data-ws2-tab-page="next"]').exists()).toBe(false)
    width = 310
    onResize()
    await nextTick()
    expect(wrapper.findAll('.ws2-tab__title')).toHaveLength(0)
    expect(wrapper.findAll('.ws2-tab__icon')).toHaveLength(7)
    expect(wrapper.findAll('.ws2-tab__close')).toHaveLength(1)
    wrapper.get('.ws2-tab__close').element.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, button: 0 }))
    await wrapper.get('.ws2-tab__close').trigger('click')
    expect(wrapper.emitted('close')).toEqual([[tabs[0].id]])
    expect(wrapper.emitted('tab-pointerdown')).toBeUndefined()
    expect(wrapper.emitted('select')).toBeUndefined()

    const viewport = wrapper.get<HTMLElement>('.ws2-tabs__viewport')
    Object.defineProperties(viewport.element, {
      scrollWidth: { value: 268 },
      clientWidth: { value: 70 },
    })
    width = 132
    onResize()
    await nextTick()
    const previous = wrapper.get('[data-ws2-tab-page="previous"]')
    const next = wrapper.get('[data-ws2-tab-page="next"]')
    expect(previous.attributes('disabled')).toBeDefined()
    await next.trigger('click')
    expect(viewport.element.scrollLeft).toBeGreaterThan(0)
    expect(previous.attributes('disabled')).toBeUndefined()
    await previous.trigger('click')
    expect(viewport.element.scrollLeft).toBe(0)

    width = 840
    onResize()
    await nextTick()
    expect(wrapper.findAll('.ws2-tab__title')).toHaveLength(8)
    expect(wrapper.find('[data-ws2-tab-page="next"]').exists()).toBe(false)
  } finally {
    wrapper.unmount()
    geometry.mockRestore()
    vi.unstubAllGlobals()
  }
})

import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceShell from '../src/components/WorkspaceShell.vue'

/**
 * user:“手机抽屉里的会话侧栏”+(手机不再有左侧栏：抽屉 DOM、左上角抽屉键、遮罩和左滑手势
 * 一起收口。否则会留下“点了只出黑罩、没有内容”的死入口；桌面端必须继续有抽屉)。
 */
type MediaListener = (event: MediaQueryListEvent) => void

function installMatchMedia(matches: boolean) {
  const listeners = new Set<MediaListener>()
  const mediaQuery = {
    matches,
    media: '(max-width: 640px)',
    onchange: null,
    addEventListener: (_type: string, listener: MediaListener) => listeners.add(listener),
    removeEventListener: (_type: string, listener: MediaListener) => listeners.delete(listener),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  } as unknown as MediaQueryList
  const setMatches = (next: boolean) => {
    Object.defineProperty(mediaQuery, 'matches', { configurable: true, value: next })
    listeners.forEach((listener) => listener({ matches: next, media: '(max-width: 640px)' } as MediaQueryListEvent))
  }
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn(() => mediaQuery),
  })
  return { setMatches }
}

function dispatchPointerEvent(
  element: Element,
  type: string,
  init: { pointerId: number; clientX: number; clientY: number },
): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: init.pointerId },
    pointerType: { configurable: true, value: 'touch' },
    button: { configurable: true, value: 0 },
    clientX: { configurable: true, value: init.clientX },
    clientY: { configurable: true, value: init.clientY },
  })
  element.dispatchEvent(event)
}

describe('WorkspaceShell on mobile without a left drawer', () => {
  beforeEach(() => {
    localStorage.clear()
    installMatchMedia(true)
  })

  it('renders neither the drawer DOM nor the hamburger', () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', platform: 'mobile', showDrawerToggle: true },
      slots: { 'sidebar-body': '<div data-mobile-sidebar-body>会话列表</div>' },
    })

    expect(wrapper.find('.drawer-left').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-drawer-toggle]').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-sidebar-body]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('never puts the drawer backdrop over the page, even if the drawer is asked to open', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', platform: 'mobile', showDrawerToggle: true },
    })
    const shell = wrapper.vm as unknown as { openLeftDrawer: () => void }

    shell.openLeftDrawer()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.mobile-drawer-backdrop').exists()).toBe(false)
    wrapper.unmount()
  })

  it('ignores the right swipe that used to pull the mobile drawer out', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', platform: 'mobile', showDrawerToggle: true },
    })
    const element = wrapper.get('.workspace-shell').element

    dispatchPointerEvent(element, 'pointerdown', { pointerId: 7, clientX: 60, clientY: 400 })
    dispatchPointerEvent(element, 'pointermove', { pointerId: 7, clientX: 120, clientY: 402 })
    dispatchPointerEvent(element, 'pointerup', { pointerId: 7, clientX: 120, clientY: 402 })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.drawer-left').exists()).toBe(false)
    expect(wrapper.find('.mobile-drawer-backdrop').exists()).toBe(false)
    expect(wrapper.get('.workspace-shell').classes()).not.toContain('left-open')
    wrapper.unmount()
  })

  it('keeps the drawer for desktop', () => {
    const wrapper = mount(WorkspaceShell, { props: { productName: 'Sunday', platform: 'desktop' } })

    expect(wrapper.find('.drawer-left').exists()).toBe(true)
    wrapper.unmount()
  })
})

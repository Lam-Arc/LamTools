import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceShell from '../src/components/WorkspaceShell.vue'

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
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: vi.fn(() => mediaQuery),
  })
}

describe('WorkspaceShell responsive drawers', () => {
  beforeEach(() => {
    localStorage.clear()
    installMatchMedia(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps both mobile navigation surfaces reachable without leaving closed drawers focusable', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sage', errorText: '连接失败' },
      slots: {
        'sidebar-body': '<button data-left-action>会话</button>',
        'right-panel': '<button data-right-action>运行状态</button>',
      },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()

    const leftDrawer = wrapper.get('[data-workspace-left-drawer]')
    const rightDrawer = wrapper.get('[data-workspace-right-drawer]')
    const leftToggle = wrapper.get('[data-mobile-left-toggle]')
    const rightToggle = wrapper.get('[data-mobile-right-toggle]')

    expect(leftDrawer.attributes('inert')).toBeDefined()
    expect(rightDrawer.attributes('inert')).toBeDefined()
    expect(leftToggle.attributes('aria-expanded')).toBe('false')
    expect(rightToggle.attributes('aria-expanded')).toBe('false')

    await leftToggle.trigger('click')
    expect(leftDrawer.attributes('inert')).toBeUndefined()
    expect(leftToggle.attributes('aria-expanded')).toBe('true')
    expect(leftToggle.attributes('aria-label')).toBe('关闭会话与导航')

    const leftAction = wrapper.get('[data-left-action]')
    ;(leftAction.element as HTMLElement).focus()
    await wrapper.get('.mobile-drawer-backdrop').trigger('click')
    await wrapper.vm.$nextTick()
    expect(leftDrawer.attributes('inert')).toBeDefined()
    expect(document.activeElement).toBe(leftToggle.element)

    await rightToggle.trigger('click')
    expect(rightDrawer.attributes('inert')).toBeUndefined()
    expect(rightToggle.attributes('aria-expanded')).toBe('true')
    expect(rightToggle.attributes('aria-label')).toBe('关闭运行状态')

    const rightAction = wrapper.get('[data-right-action]')
    ;(rightAction.element as HTMLElement).focus()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(rightDrawer.attributes('inert')).toBeDefined()
    expect(document.activeElement).toBe(rightToggle.element)

    const error = wrapper.get('.error-toast')
    expect(error.attributes('role')).toBe('alert')
    expect(error.attributes('aria-atomic')).toBe('true')

    wrapper.unmount()
  })

  it('leaves mobile visibility to the shared responsive stylesheet', () => {
    const source = readFileSync(resolve(import.meta.dirname, '../src/components/WorkspaceShell.vue'), 'utf8')
    const scopedStyle = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? ''

    expect(scopedStyle).not.toMatch(/\.mobile-shell-nav[\s\S]*?display:\s*none/)
    expect(scopedStyle).not.toMatch(/\.mobile-drawer-backdrop[\s\S]*?display:\s*none/)
  })
})

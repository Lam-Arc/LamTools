import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceShell from '../src/components/WorkspaceShell.vue'

const STORAGE_KEY = 'lamtools.test.sidebar-resize'

function dispatchPointer(target: EventTarget, type: string, clientX: number, pointerId = 1): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: pointerId },
    pointerType: { configurable: true, value: 'mouse' },
    button: { configurable: true, value: 0 },
    clientX: { configurable: true, value: clientX },
    clientY: { configurable: true, value: 240 },
  })
  target.dispatchEvent(event)
}

// user:“会话栏与主内容区，它们中间那条分界线需要可以拖拽滑移”+
// (分界线是会话栏与聊天区之间那条 3px 缝：拖它改会话栏宽度，松手后记住。)
describe('sidebar divider resizing', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
    document.body.className = ''
  })

  it('drags the divider to change the sidebar width and remembers it', async () => {
    vi.useFakeTimers()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ leftWidth: 240 }))
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', storageKey: STORAGE_KEY },
      attachTo: document.body,
    })
    await nextTick()

    const shell = wrapper.get('.workspace-shell')
    expect(shell.attributes('style')).toContain('--sidebar-width: 240px')

    const handle = wrapper.get('[data-sidebar-resize-handle]')
    dispatchPointer(handle.element, 'pointerdown', 300)
    expect(document.body.classList.contains('sidebar-is-resizing')).toBe(true)

    dispatchPointer(window, 'pointermove', 364)
    await nextTick()
    expect(shell.attributes('style')).toContain('--sidebar-width: 304px')

    dispatchPointer(window, 'pointerup', 364)
    expect(document.body.classList.contains('sidebar-is-resizing')).toBe(false)

    vi.advanceTimersByTime(600)
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}').leftWidth).toBe(304)
    wrapper.unmount()
  })

  it('supports keyboard resizing and restores the default on reset', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ leftWidth: 240 }))
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', storageKey: STORAGE_KEY },
      attachTo: document.body,
    })
    await nextTick()

    const shell = wrapper.get('.workspace-shell')
    const handle = wrapper.get('[data-sidebar-resize-handle]')

    await handle.trigger('keydown', { key: 'ArrowRight' })
    expect(shell.attributes('style')).toContain('--sidebar-width: 256px')

    await handle.trigger('keydown', { key: 'ArrowLeft' })
    expect(shell.attributes('style')).toContain('--sidebar-width: 240px')

    await handle.trigger('dblclick')
    expect(shell.attributes('style')).not.toContain('--sidebar-width')
    wrapper.unmount()
  })

  it('hides the divider when the sidebar is not part of the layout', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', storageKey: STORAGE_KEY },
      attachTo: document.body,
    })
    expect(wrapper.find('[data-sidebar-resize-handle]').exists()).toBe(true)

    await wrapper.setProps({ collapseLeftSidebar: true })
    expect(wrapper.find('[data-sidebar-resize-handle]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('pins the divider to the seam between the sidebar and the main card', () => {
    const css = readFileSync(resolve(import.meta.dirname, '../src/styles/workspace-shell.css'), 'utf8')
    expect(css).toMatch(/\.sidebar-resize-handle\s*\{[\s\S]*?cursor: col-resize;/)
    expect(css).toContain('left: calc(var(--rail-width) + var(--left-card-width)')
    expect(css).toMatch(/\.sidebar-is-resizing[\s\S]*?user-select: none/)
  })
})

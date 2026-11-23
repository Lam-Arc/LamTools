import { afterEach, describe, expect, it } from 'vitest'

import {
  browserEntryAvailability,
  firstHttpLink,
  openBrowserPane,
  openInBrowser,
  openLinkInCurrentPage,
  registerBrowserEntry,
} from '../src/browser/entry'

// user:“入口都要能在「浏览器不可用」时给出明确原因（例如子 webview 创建失败），不能点了没反应”+
// (这里钉的就是「不能静默」：不可用时一定有一句可读的原因，可用时 opener 拿到的参数形状正确)。
const cleanups: Array<() => void> = []

function simulateDesktop(): void {
  ;(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = {}
}

function clearDesktop(): void {
  delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
}

function register(opener: Parameters<typeof registerBrowserEntry>[0]): void {
  cleanups.push(registerBrowserEntry(opener))
}

afterEach(() => {
  while (cleanups.length) cleanups.pop()?.()
  clearDesktop()
})

describe('browser entry', () => {
  it('explains that the built-in browser needs the desktop app', () => {
    const state = browserEntryAvailability()
    expect(state.available).toBe(false)
    expect(state.reason).toContain('桌面应用')
    const result = openInBrowser('https://example.com')
    expect(result.ok).toBe(false)
    expect(result.reason).toContain('桌面应用')
  })

  it('explains that the host has not registered an opener yet', () => {
    simulateDesktop()
    const state = browserEntryAvailability()
    expect(state.available).toBe(false)
    expect(state.reason).toContain('还没就绪')
    expect(openBrowserPane().ok).toBe(false)
  })

  it('opens http(s) links through the registered opener', () => {
    simulateDesktop()
    const calls: Array<{ url: string; title?: string; reuse?: boolean }> = []
    register(target => {
      calls.push(target)
      return { ok: true, reason: '' }
    })
    expect(browserEntryAvailability().available).toBe(true)

    expect(openInBrowser('https://example.com/a', 'example.com').ok).toBe(true)
    expect(calls[0]).toEqual({ url: 'https://example.com/a', title: 'example.com' })
  })

  it('refuses non-http links with the classification reason instead of opening', () => {
    simulateDesktop()
    let called = 0
    register(() => {
      called += 1
      return { ok: true, reason: '' }
    })

    const local = openInBrowser('C:\\work\\a.md')
    expect(local.ok).toBe(false)
    expect(local.reason).toContain('预览器/编辑器')
    expect(called).toBe(0)
    expect(openInBrowser('mailto:a@b.com').ok).toBe(false)
  })

  it('surfaces an opener failure instead of reporting success', () => {
    simulateDesktop()
    register(() => ({ ok: false, reason: '窗口放不下分屏' }))
    const result = openBrowserPane()
    expect(result.ok).toBe(false)
    expect(result.reason).toBe('窗口放不下分屏')
  })

  it('surfaces a thrown error as a readable reason', () => {
    simulateDesktop()
    register(() => {
      throw new Error('子 webview 创建失败')
    })
    const result = openInBrowser('https://example.com')
    expect(result.ok).toBe(false)
    expect(result.reason).toContain('子 webview 创建失败')
  })

  it('unregisters without leaving an entry that cannot open', () => {
    simulateDesktop()
    const offline = registerBrowserEntry(() => ({ ok: true, reason: '' }))
    offline()
    expect(browserEntryAvailability().available).toBe(false)
    expect(openInBrowser('https://example.com').ok).toBe(false)
  })

  it('picks the first http link out of clipboard text for the current page', () => {
    expect(firstHttpLink('看这个 https://example.com/x?y=1 挺好')).toBe('https://example.com/x?y=1')
    expect(firstHttpLink('C:\\work\\a.md')).toBe('')

    simulateDesktop()
    const calls: Array<{ url: string; title?: string; reuse?: boolean }> = []
    register(target => {
      calls.push(target)
      return { ok: true, reason: '' }
    })
    const result = openLinkInCurrentPage('https://example.com/x?y=1')
    expect(result.ok).toBe(true)
    expect(calls[0]).toEqual({ url: 'https://example.com/x?y=1', reuse: true })
    expect(openLinkInCurrentPage('没有链接').ok).toBe(false)
  })
})

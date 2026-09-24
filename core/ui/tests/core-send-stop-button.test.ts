import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import CoreSendStopButton from '../src/components/CoreSendStopButton.vue'

const componentPath = resolve(process.cwd(), 'src/components/CoreSendStopButton.vue')

function mediaQuery(matches: boolean): MediaQueryList {
  return {
    matches,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }
}

describe('CoreSendStopButton composer action colors', () => {
  beforeEach(() => {
    vi.stubGlobal('getComputedStyle', window.getComputedStyle.bind(window))
    vi.spyOn(window, 'matchMedia').mockReturnValue(mediaQuery(true))
    document.documentElement.style.setProperty('--theme-composer-text', '#f0e6d2')
    document.documentElement.style.setProperty('--theme-composer-background', 'linear-gradient(90deg, #242831, #343942)')
    document.documentElement.style.setProperty('--theme-control-text', '#control-text')
    document.documentElement.style.setProperty('--theme-control-solid', '#control-solid')
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.documentElement.style.removeProperty('--theme-composer-text')
    document.documentElement.style.removeProperty('--theme-composer-background')
    document.documentElement.style.removeProperty('--theme-control-text')
    document.documentElement.style.removeProperty('--theme-control-solid')
    document.body.innerHTML = ''
  })

  it('uses the composer text surface and composer background glyph in both CSS states', () => {
    const source = readFileSync(componentPath, 'utf8')
    expect(source).not.toContain('--theme-control')
    expect(source).not.toContain('var(--red)')
    expect(source).toMatch(/\.core-send-stop-button\s*\{[\s\S]*?background:\s*var\(--theme-composer-text\);/)
    expect(source).toMatch(/\.core-send-stop-button--stop\s*\{[\s\S]*?background:\s*var\(--theme-composer-text\);/)
    expect(source).toMatch(/\.core-send-stop-button::before\s*\{[\s\S]*?background:\s*var\(--theme-composer-background\);/)
    expect(source).toMatch(/\.core-send-stop-button::after\s*\{[\s\S]*?background:\s*var\(--theme-composer-background\);/)
    expect(source).not.toMatch(/color:\s*var\(--theme-composer-background\)/)
    expect(source).not.toContain('backgroundColor:')
  })

  it('keeps both send and stop transitions on the composer token pair', async () => {
    const wrapper = mount(CoreSendStopButton, {
      attachTo: document.body,
      props: { actionMode: 'send' },
    })
    const button = wrapper.get('button').element as HTMLButtonElement

    expect(getComputedStyle(button).getPropertyValue('--theme-composer-text').trim()).toBe('#f0e6d2')
    expect(getComputedStyle(button).getPropertyValue('--theme-composer-background').trim()).toBe('linear-gradient(90deg, #242831, #343942)')
    expect(button.style.backgroundColor).toBe('')

    await wrapper.setProps({ actionMode: 'stop' })
    expect(button.dataset.state).toBe('stop')
    expect(button.classList.contains('core-send-stop-button--stop')).toBe(true)
    expect(button.style.backgroundColor).toBe('')
    expect(getComputedStyle(button).getPropertyValue('--theme-composer-text').trim()).toBe('#f0e6d2')
    expect(getComputedStyle(button).getPropertyValue('--theme-composer-background').trim()).toBe('linear-gradient(90deg, #242831, #343942)')

    await wrapper.setProps({ actionMode: 'send' })
    expect(button.dataset.state).toBe('send')
    expect(button.classList.contains('core-send-stop-button--stop')).toBe(false)
    expect(button.style.backgroundColor).toBe('')
    wrapper.unmount()
  })

  it('follows composer theme tokens after a theme change without a stale inline color', async () => {
    const wrapper = mount(CoreSendStopButton, {
      attachTo: document.body,
      props: { actionMode: 'send' },
    })
    const button = wrapper.get('button').element as HTMLButtonElement

    document.documentElement.style.setProperty('--theme-composer-text', '#1b2634')
    document.documentElement.style.setProperty('--theme-composer-background', 'linear-gradient(90deg, #f7f1e8, #eee7db)')
    expect(getComputedStyle(button).getPropertyValue('--theme-composer-text').trim()).toBe('#1b2634')
    expect(getComputedStyle(button).getPropertyValue('--theme-composer-background').trim()).toBe('linear-gradient(90deg, #f7f1e8, #eee7db)')
    expect(button.style.backgroundColor).toBe('')

    await wrapper.setProps({ actionMode: 'stop' })
    expect(button.style.backgroundColor).toBe('')
    wrapper.unmount()
  })
})

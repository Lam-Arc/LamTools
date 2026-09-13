import { defineComponent, h, nextTick, ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import {
  calculateKeyboardInset,
  useComposerLayout,
} from '../src/composables/useComposerLayout'

describe('useComposerLayout', () => {
  it('calculates only the visual viewport area covered by the keyboard', () => {
    expect(calculateKeyboardInset(800, { height: 480, offsetTop: 0 })).toBe(320)
    expect(calculateKeyboardInset(800, { height: 840, offsetTop: 0 })).toBe(0)
    expect(calculateKeyboardInset(800, { height: 480, offsetTop: 24 })).toBe(296)
    expect(calculateKeyboardInset(800, { height: 700, offsetTop: 0 })).toBe(100)
    expect(calculateKeyboardInset(800, { height: 480, offsetTop: 0, scale: 1.2 })).toBe(320)
    // With Android adjustResize the layout viewport is already reduced, so no
    // second keyboard inset is added.
    expect(calculateKeyboardInset(480, { height: 480, offsetTop: 0 })).toBe(0)
    expect(calculateKeyboardInset(800, null)).toBe(0)
  })

  it('updates on visual viewport changes and clears the inset when the keyboard closes', async () => {
    const listeners = new Map<string, Set<() => void>>()
    const visualViewport = {
      height: 800,
      offsetTop: 0,
      addEventListener(type: string, listener: () => void) {
        const current = listeners.get(type) ?? new Set<() => void>()
        current.add(listener)
        listeners.set(type, current)
      },
      removeEventListener(type: string, listener: () => void) {
        listeners.get(type)?.delete(listener)
      },
    }
    const originalViewport = Object.getOwnPropertyDescriptor(window, 'visualViewport')
    const originalInnerHeight = Object.getOwnPropertyDescriptor(window, 'innerHeight')
    Object.defineProperty(window, 'visualViewport', {
      configurable: true,
      value: visualViewport,
    })
    Object.defineProperty(window, 'innerHeight', {
      configurable: true,
      value: 800,
    })

    const Harness = defineComponent({
      setup() {
        const root = ref<HTMLElement | null>(null)
        const emptySession = ref(false)
        const viewportOpen = ref(false)
        const sessionKey = ref<string | null>('session-a')
        const sessionReady = ref(true)
        const layout = useComposerLayout({
          root,
          emptySession,
          viewportOpen,
          sessionKey,
          sessionReady,
        })
        return { root, sessionKey, layout }
      },
      render() {
        return h('div', { ref: 'root' }, [
          h('div', { class: 'floating-composer' }, [h('textarea')]),
        ])
      },
    })

    const wrapper = mount(Harness, { attachTo: document.body })
    const input = wrapper.get('textarea').element as HTMLTextAreaElement
    input.focus()

    visualViewport.height = 480
    listeners.get('resize')?.forEach((listener) => listener())
    await nextTick()
    expect(wrapper.vm.layout.state.value.keyboardInset).toBe(320)

    visualViewport.height = 800
    listeners.get('scroll')?.forEach((listener) => listener())
    await nextTick()
    expect(wrapper.vm.layout.state.value.keyboardInset).toBe(0)

    visualViewport.height = 480
    listeners.get('resize')?.forEach((listener) => listener())
    await nextTick()
    expect(wrapper.vm.layout.state.value.keyboardInset).toBe(320)
    wrapper.vm.sessionKey = 'session-b'
    await nextTick()
    expect(wrapper.vm.layout.state.value.keyboardInset).toBe(0)

    wrapper.unmount()
    if (originalViewport) Object.defineProperty(window, 'visualViewport', originalViewport)
    else Reflect.deleteProperty(window, 'visualViewport')
    if (originalInnerHeight) Object.defineProperty(window, 'innerHeight', originalInnerHeight)
  })

  it('keeps the mobile native host on the resize path', () => {
    const manifest = readFileSync(
      resolve(process.cwd(), '../mobile/android/app/src/main/AndroidManifest.xml'),
      'utf8',
    )
    expect(manifest).toContain('android:windowSoftInputMode="adjustResize"')
  })

  it('keeps working-state placement after keyboard and viewport changes', async () => {
    const Harness = defineComponent({
      setup() {
        const root = ref<HTMLElement | null>(null)
        const emptySession = ref(true)
        const viewportOpen = ref(false)
        const sessionKey = ref<string | null>('session-a')
        const sessionReady = ref(true)
        const layout = useComposerLayout({
          root,
          emptySession,
          viewportOpen,
          sessionKey,
          sessionReady,
        })
        return { root, emptySession, viewportOpen, sessionKey, sessionReady, layout }
      },
      render() {
        return h('div', { ref: 'root' }, [h('div', { class: 'floating-composer' })])
      },
    })

    const wrapper = mount(Harness)
    expect(wrapper.vm.layout.placement.value).toBe('center')

    wrapper.vm.layout.enterBottom()
    await nextTick()
    expect(wrapper.vm.layout.placement.value).toBe('bottom')

    wrapper.vm.viewportOpen = true
    await nextTick()
    wrapper.vm.viewportOpen = false
    await nextTick()
    expect(wrapper.vm.layout.placement.value).toBe('bottom')

    wrapper.vm.emptySession = false
    await nextTick()
    wrapper.vm.emptySession = true
    await nextTick()
    expect(wrapper.vm.layout.placement.value).toBe('bottom')
    expect(wrapper.vm.layout.state.value.hasEnteredWorkMode).toBe(true)
    expect(wrapper.vm.layout.style.value['--composer-bottom-offset']).toBe(
      'max(var(--keyboard-inset), var(--safe-area-bottom))',
    )

    wrapper.vm.sessionReady = false
    wrapper.vm.sessionKey = 'session-b'
    await nextTick()
    wrapper.vm.sessionReady = true
    await nextTick()
    expect(wrapper.vm.layout.placement.value).toBe('center')

    wrapper.vm.sessionReady = false
    wrapper.vm.sessionKey = 'session-a'
    await nextTick()
    expect(wrapper.vm.layout.placement.value).toBe('bottom')
    wrapper.vm.sessionReady = true
    await nextTick()
    expect(wrapper.vm.layout.placement.value).toBe('bottom')

    wrapper.unmount()
  })

  it('re-measures the composer when a start page adds it after mount', async () => {
    const heightSpy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        return {
          height: this.classList.contains('floating-composer') ? 88 : 0,
          width: 0,
          top: 0,
          right: 0,
          bottom: 0,
          left: 0,
          x: 0,
          y: 0,
          toJSON: () => ({}),
        } as DOMRect
      })

    const showComposer = ref(false)
    const Harness = defineComponent({
      setup() {
        const root = ref<HTMLElement | null>(null)
        const emptySession = ref(true)
        const viewportOpen = ref(false)
        const sessionKey = ref<string | null>('session-a')
        const sessionReady = ref(true)
        const layout = useComposerLayout({
          root,
          emptySession,
          viewportOpen,
          sessionKey,
          sessionReady,
        })
        return { root, showComposer, layout }
      },
      render() {
        return h('div', { ref: 'root' }, [
          showComposer.value ? h('div', { class: 'floating-composer' }) : null,
        ])
      },
    })

    const wrapper = mount(Harness)
    await nextTick()
    expect(wrapper.vm.layout.state.value.composerHeight).toBe(0)

    wrapper.vm.showComposer = true
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(wrapper.vm.layout.state.value.composerHeight).toBe(88)

    heightSpy.mockRestore()
    wrapper.unmount()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })
})

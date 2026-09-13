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

function dispatchPointerEvent(
  element: Element,
  type: string,
  init: { pointerId: number; pointerType: string; clientX: number; clientY: number },
): void {
  const event = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: init.pointerId },
    pointerType: { configurable: true, value: init.pointerType },
    button: { configurable: true, value: 0 },
    clientX: { configurable: true, value: init.clientX },
    clientY: { configurable: true, value: init.clientY },
  })
  element.dispatchEvent(event)
}

describe('WorkspaceShell responsive drawers', () => {
  beforeEach(() => {
    localStorage.clear()
    installMatchMedia(true)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('lets a modular right panel own its header without the legacy title', () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sunday', showRightPanelHeader: false },
      slots: { 'right-panel': '<div data-modular-right-panel>模块区</div>' },
    })

    expect(wrapper.find('.drawer-right .drawer-head').exists()).toBe(false)
    expect(wrapper.find('[data-modular-right-panel]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('opens the mobile drawers from a horizontal swipe starting anywhere', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sage' },
      slots: {
        'sidebar-body': '<button data-left-action>会话</button>',
        'right-panel': '<button data-right-action>运行状态</button>',
      },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()

    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const leftDrawer = wrapper.get('[data-workspace-left-drawer]')
    const rightDrawer = wrapper.get('[data-workspace-right-drawer]')
    const shell = wrapper.get('.workspace-shell')

    expect(leftDrawer.attributes('inert')).toBeDefined()
    expect(rightDrawer.attributes('inert')).toBeDefined()
    expect(wrapper.find('[data-mobile-left-toggle]').exists()).toBe(false)
    expect(wrapper.find('[data-mobile-right-toggle]').exists()).toBe(false)

    dispatchPointerEvent(shell.element, 'pointerdown', {
      pointerId: 1,
      pointerType: 'touch',
      clientX: 195,
      clientY: 280,
    })
    dispatchPointerEvent(shell.element, 'pointermove', {
      pointerId: 1,
      pointerType: 'touch',
      clientX: 231,
      clientY: 284,
    })
    dispatchPointerEvent(shell.element, 'pointerup', {
      pointerId: 1,
      pointerType: 'touch',
      clientX: 231,
      clientY: 284,
    })
    await wrapper.vm.$nextTick()
    expect(leftDrawer.attributes('inert')).toBeUndefined()

    await wrapper.get('.mobile-drawer-backdrop').trigger('click')
    await wrapper.vm.$nextTick()
    expect(leftDrawer.attributes('inert')).toBeDefined()

    dispatchPointerEvent(shell.element, 'pointerdown', {
      pointerId: 2,
      pointerType: 'mouse',
      clientX: 195,
      clientY: 280,
    })
    dispatchPointerEvent(shell.element, 'pointermove', {
      pointerId: 2,
      pointerType: 'mouse',
      clientX: 159,
      clientY: 284,
    })
    dispatchPointerEvent(shell.element, 'pointerup', {
      pointerId: 2,
      pointerType: 'mouse',
      clientX: 159,
      clientY: 284,
    })
    await wrapper.vm.$nextTick()
    expect(rightDrawer.attributes('inert')).toBeUndefined()

    wrapper.unmount()
  })

  it('does not treat mouse text selection as a drawer gesture', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Sage' },
      slots: {
        default: '<p data-selectable>可选择的正文内容</p>',
        'right-panel': '<button>运行状态</button>',
      },
      attachTo: document.body,
    })
    await wrapper.vm.$nextTick()

    const shell = wrapper.get('.workspace-shell')
    dispatchPointerEvent(shell.element, 'pointerdown', {
      pointerId: 3,
      pointerType: 'mouse',
      clientX: 240,
      clientY: 280,
    })
    shell.element.dispatchEvent(new Event('selectstart', { bubbles: true, cancelable: true }))
    dispatchPointerEvent(shell.element, 'pointerup', {
      pointerId: 3,
      pointerType: 'mouse',
      clientX: 160,
      clientY: 282,
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.get('[data-workspace-right-drawer]').attributes('inert')).toBeDefined()
    wrapper.unmount()
  })

  it('leaves mobile visibility to the shared responsive stylesheet', () => {
    const source = readFileSync(resolve(import.meta.dirname, '../src/components/WorkspaceShell.vue'), 'utf8')
    const scopedStyle = source.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? ''

    expect(scopedStyle).not.toMatch(/\.mobile-shell-nav[\s\S]*?display:\s*none/)
    expect(scopedStyle).not.toMatch(/\.mobile-drawer-backdrop[\s\S]*?display:\s*none/)
  })

  it('keeps the mobile sidebar within the viewport and gives actions touch targets', () => {
    const shellCss = readFileSync(resolve(import.meta.dirname, '../src/styles/workspace-shell.css'), 'utf8')
    const sidebarCss = readFileSync(resolve(import.meta.dirname, '../src/styles/session-sidebar.css'), 'utf8')
    const variablesCss = readFileSync(resolve(import.meta.dirname, '../src/styles/variables.css'), 'utf8')

    expect(variablesCss).toContain('--sidebar-width: 232px')
    expect(shellCss).toMatch(/--sidebar-width: min\(86vw, 320px\)/)
    expect(shellCss).toContain('--right-panel-gap: 2px')
    expect(shellCss).toMatch(/\.sidebar-create-project\s*\{[\s\S]*?border-radius: var\(--radius\)/)
    expect(shellCss).toMatch(/\.drawer-right\s*\{[\s\S]*?right: 0;[\s\S]*?width: calc\(var\(--right-drawer-width\) - var\(--right-panel-gap\)\);/)
    expect(shellCss).toMatch(/\.drawer-right\s*\{[\s\S]*?border: 1px solid color-mix\(in srgb, var\(--theme-backdrop-text\) 18%, transparent\);[\s\S]*?border-radius: var\(--radius-lg\) 0 0 var\(--radius-lg\);[\s\S]*?background: transparent;/)
    expect(shellCss).toMatch(/\.drawer-right::before\s*\{[\s\S]*?border-radius: inherit;[\s\S]*?-webkit-mask-image:[\s\S]*?linear-gradient\(to right,[\s\S]*?linear-gradient\(to bottom,[\s\S]*?mask-composite: intersect;/)
    expect(shellCss).toMatch(/\.drawer-right\s*\{[\s\S]*?transition: transform 240ms var\(--ease-out\), opacity 240ms var\(--ease-out\);/)
    expect(shellCss).toMatch(/\.drawer-right:not\(\.open\)\s*\{[\s\S]*?transition-duration: var\(--dur-base\), var\(--dur-base\);/)
    expect(shellCss).toMatch(/\.workspace-shell \.workspace-drawer,[\s\S]*?transition: none !important;/)
    expect(shellCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?\.drawer-right\s*\{[\s\S]*?left: var\(--space-2\);[\s\S]*?right: var\(--space-2\);[\s\S]*?width: auto;/)
    expect(shellCss).toMatch(/\.sidebar-root \.sidebar-pin-button \{[\s\S]*?width: 44px;[\s\S]*?height: 44px;/)
    expect(shellCss).toMatch(/\.drawer-footer \.settings-entry,[\s\S]*?\.drawer-footer \.sidebar-action,[\s\S]*?\.sidebar-create-project \{[\s\S]*?min-height: 44px;/)
    expect(sidebarCss).toMatch(/\.sidebar-search,[\s\S]*?\.sidebar-search-clear,[\s\S]*?\.sidebar-project-empty-action \{[\s\S]*?min-height: 44px;/)
    expect(sidebarCss).toMatch(/\.project-action \{[\s\S]*?min-width: 44px;[\s\S]*?min-height: 44px;/)
    const contextMenuCss = readFileSync(resolve(import.meta.dirname, '../src/components/context-menu/ContextMenuPanel.vue'), 'utf8')
    expect(contextMenuCss).toMatch(/@media \(max-width: 640px\)[\s\S]*?\.context-menu-panel \{[\s\S]*?max-width: calc\(100vw - var\(--space-6\)\);[\s\S]*?max-height: calc\(100dvh - var\(--space-6\)\);[\s\S]*?\.context-menu-item \{[\s\S]*?min-height: 44px;/)
  })

  it('renders the configured sidebar title and keeps the default fallback', () => {
    const configured = mount(WorkspaceShell, {
      props: { productName: 'Sage', sidebarTitle: '工作区' },
    })
    expect(configured.get('.sidebar-label').text()).toBe('工作区')

    const fallback = mount(WorkspaceShell, { props: { productName: 'Sage' } })
    expect(fallback.get('.sidebar-label').text()).toBe('项目')
  })

  it('allows a host to remove the sidebar title and pin control', () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Core', sidebarTitle: 'Core', showSidebarHeader: false },
    })

    expect(wrapper.find('.sidebar-header').exists()).toBe(false)
    expect(wrapper.find('.sidebar-pin-button').exists()).toBe(false)
  })

  it('exposes the sidebar pin state and keeps the host state synchronized', async () => {
    const wrapper = mount(WorkspaceShell, { props: { productName: 'Sage' } })
    const pin = wrapper.get('.sidebar-pin-button')
    await wrapper.vm.$nextTick()

    expect(pin.classes()).not.toContain('is-active')
    expect(pin.attributes('aria-pressed')).toBe('false')

    await pin.trigger('click')

    expect(pin.classes()).toContain('is-active')
    expect(pin.attributes('aria-pressed')).toBe('true')
    expect(wrapper.emitted('update:left-pinned')).toEqual([[true]])
  })

  it('exposes a mobile drawer opener for host-level controls', async () => {
    const wrapper = mount(WorkspaceShell, { props: { productName: 'Core' } })
    const shell = wrapper.vm as unknown as { openLeftDrawer: () => void }
    const leftDrawer = wrapper.get('[data-workspace-left-drawer]')
    await wrapper.vm.$nextTick()

    expect(leftDrawer.attributes('inert')).toBeDefined()
    shell.openLeftDrawer()
    await wrapper.vm.$nextTick()
    expect(leftDrawer.attributes('inert')).toBeUndefined()
    expect(wrapper.emitted('update:left-open')?.at(-1)).toEqual([true])

    await wrapper.get('.mobile-drawer-backdrop').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:left-open')?.at(-1)).toEqual([false])

    wrapper.unmount()
  })

  it('marks the shared shell and composer for an empty Core session', () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Core', emptySession: true },
    })

    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--empty-session')
    expect(wrapper.get('.composer-root').classes()).toContain('composer-root--empty-session')
    expect(wrapper.find('.floating-composer').exists()).toBe(true)
  })

  it('keeps the empty-session composer centered on focus and docks it only after submit', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Core', emptySession: true },
    })

    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-center')

    await wrapper.get('.floating-composer textarea').trigger('focusin')
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-center')

    await wrapper.get('.floating-composer').trigger('drop')
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-center')

    await wrapper.get('.floating-composer').trigger('submit')
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-bottom')

    await wrapper.setProps({ stageOpen: true })
    await wrapper.setProps({ stageOpen: false })
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-bottom')

    wrapper.unmount()
  })

  it('renders workflow composer as a compact, observable textarea/send pill', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Core', workflowMode: true },
      slots: {
        'composer-preamble': '<div data-workflow-preamble>preamble</div>',
        'composer-status': '<div data-workflow-status>status</div>',
        'composer-tools': '<button data-workflow-tool type="button">tool</button>',
      },
    })

    const shell = wrapper.get('.workspace-shell')
    const composer = wrapper.get('.composer-root')
    expect(shell.classes()).toContain('workspace-shell--workflow')
    expect(shell.attributes('data-workflow-composer-state')).toBe('send')
    expect(composer.attributes('data-workflow-composer')).toBe('true')
    expect(composer.attributes('data-workflow-composer-has-value')).toBe('false')
    expect(wrapper.find('[data-workflow-preamble]').exists()).toBe(false)
    expect(wrapper.find('[data-workflow-status]').exists()).toBe(false)
    expect(wrapper.find('[data-workflow-tool]').exists()).toBe(false)
    expect(wrapper.find('.floating-composer textarea').exists()).toBe(true)
    expect(wrapper.find('.core-send-stop-button').exists()).toBe(true)

    await wrapper.get('.floating-composer textarea').setValue('编辑节点')
    expect(composer.classes()).toContain('composer-root--workflow-has-value')
    expect(composer.attributes('data-workflow-composer-has-value')).toBe('true')
    expect(shell.classes()).toContain('workspace-shell--workflow-composer-has-value')

    await wrapper.setProps({ composerActionMode: 'stop' })
    expect(composer.classes()).toContain('composer-root--workflow-stop')
    expect(composer.attributes('data-workflow-composer-state')).toBe('stop')
    expect(shell.classes()).toContain('workspace-shell--workflow-composer-stop')

    wrapper.unmount()
  })

  it('exposes full-bleed central surface rules for workflow canvas content', () => {
    const css = readFileSync(resolve(process.cwd(), 'src/styles/layout.css'), 'utf8')
    expect(css).toMatch(/\.workspace-shell--full-bleed \.workspace-main\s*\{[\s\S]*?padding:\s*0;/)
    expect(css).toMatch(/\.workspace-shell--full-bleed \.workspace-main > :not\(\.workspace-runtime-overlay\):not\(\.workspace-plugin-header\)/)
  })

  it('animates placement changes with a transform tween and reduced-motion fallback', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/WorkspaceShell.vue'), 'utf8')

    expect(source).toContain("watch(composerLayout.placement")
    expect(source).toContain("gsap.fromTo(")
    expect(source).toContain("{ y: offsetY, willChange: 'transform' }")
    expect(source).toContain("ease: 'power3.inOut'")
    expect(source).toContain("'(prefers-reduced-motion: reduce)'")
    expect(source).toContain('composerMotionContext?.revert()')
  })

  it('syncs the keyboard inset immediately when the composer receives focus', async () => {
    const resizeListeners = new Set<() => void>()
    const visualViewport = {
      height: 480,
      offsetTop: 0,
      addEventListener(type: string, listener: () => void) {
        if (type === 'resize') resizeListeners.add(listener)
      },
      removeEventListener(type: string, listener: () => void) {
        if (type === 'resize') resizeListeners.delete(listener)
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

    const wrapper = mount(WorkspaceShell, {
      props: { productName: 'Core' },
      attachTo: document.body,
    })
    const textarea = wrapper.get('.floating-composer textarea').element as HTMLTextAreaElement
    textarea.focus()
    await wrapper.vm.$nextTick()

    expect(wrapper.get('.workspace-shell').attributes('style')).toContain('--keyboard-inset: 320px')

    visualViewport.height = 800
    resizeListeners.forEach((listener) => listener())
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.workspace-shell').attributes('style')).toContain('--keyboard-inset: 0px')

    wrapper.unmount()
    if (originalViewport) Object.defineProperty(window, 'visualViewport', originalViewport)
    else Reflect.deleteProperty(window, 'visualViewport')
    if (originalInnerHeight) Object.defineProperty(window, 'innerHeight', originalInnerHeight)
  })

  it('resets placement only when the host starts another session', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: {
        productName: 'Core',
        emptySession: true,
        composerSessionKey: 'session-a',
      },
    })

    await wrapper.get('.floating-composer').trigger('submit')
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-bottom')

    await wrapper.setProps({ composerSessionKey: 'session-b' })
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-center')

    wrapper.unmount()
  })

  it('restores bottom placement when returning to a session that already entered work mode', async () => {
    const wrapper = mount(WorkspaceShell, {
      props: {
        productName: 'Core',
        emptySession: true,
        composerSessionKey: 'session-a',
      },
    })

    await wrapper.get('.floating-composer').trigger('submit')
    await wrapper.setProps({ composerSessionKey: 'session-b' })
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-center')

    await wrapper.setProps({ composerSessionKey: 'session-a' })
    expect(wrapper.get('.workspace-shell').classes()).toContain('workspace-shell--composer-bottom')

    wrapper.unmount()
  })
})

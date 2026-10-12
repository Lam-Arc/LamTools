import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ContextMenuHost from '../src/components/context-menu/ContextMenuHost.vue'
import ContextMenuPanel from '../src/components/context-menu/ContextMenuPanel.vue'
import {
  closeContextMenu,
  contextMenuState,
  isMenuGroupCollapsed,
  isNativeContextTarget,
  LONG_PRESS_CONTEXT_MENU_DELAY_MS,
  openContextMenu,
  registerTextSelectionMenuContributor,
  resetMenuGroupMemoryForTests,
  setMenuGroupCollapsed,
} from '../src/components/context-menu/context-menu'
import type { ContextMenuEntry } from '../src/components/context-menu/types'

const contextMenuPanelSource = readFileSync(
  resolve(import.meta.dirname, '../src/components/context-menu/ContextMenuPanel.vue'),
  'utf8',
)
const opticalGlassCss = readFileSync(
  resolve(import.meta.dirname, '../src/styles/optical-glass.css'),
  'utf8',
)

const defaultViewport = {
  width: window.innerWidth,
  height: window.innerHeight,
}

async function settleRender(): Promise<void> {
  for (let index = 0; index < 4; index += 1) await nextTick()
}

function contextEvent(clientX = 40, clientY = 48): MouseEvent {
  return new MouseEvent('contextmenu', {
    bubbles: true,
    cancelable: true,
    clientX,
    clientY,
  })
}

function touchPointerEvent(
  type: string,
  clientX: number,
  clientY: number,
  pointerId = 1,
): PointerEvent {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    clientX,
    clientY,
    button: 0,
  })
  Object.defineProperties(event, {
    pointerId: { configurable: true, value: pointerId },
    pointerType: { configurable: true, value: 'touch' },
    isPrimary: { configurable: true, value: true },
  })
  return event as unknown as PointerEvent
}

function menuPanel(level = 0): HTMLElement | null {
  // 退场中的面板（关闭动效未播完）不算数：查询一律排除。
  return document.querySelector<HTMLElement>(`[data-context-menu-level="${level}"]:not(.context-menu-leave-active)`)
}

function menuButton(index: number, level = 0): HTMLButtonElement {
  const panel = menuPanel(level)
  const button = panel?.querySelector<HTMLButtonElement>(`[data-context-menu-index="${index}"]`)
  expect(button).not.toBeNull()
  return button!
}

describe('ContextMenuHost', () => {
  let host: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    host = mount(ContextMenuHost, { attachTo: document.body })
  })

  afterEach(() => {
    closeContextMenu()
    host?.unmount()
    host = null
    vi.restoreAllMocks()
    resetMenuGroupMemoryForTests()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: defaultViewport.width })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: defaultViewport.height })
  })

  it('keeps every root and submenu card on the stable liquid-glass substrate', () => {
    expect(contextMenuPanelSource).toContain('class="context-menu-panel optical-glass optical-glass--low-trans"')
    expect(opticalGlassCss).toMatch(/\.optical-glass\s*\{[\s\S]*?blur\(var\(--optical-glass-blur\)\)[\s\S]*?saturate\(var\(--optical-glass-saturation\)\)[\s\S]*?brightness\(var\(--optical-glass-brightness\)\)[\s\S]*?contrast\(var\(--optical-glass-contrast\)\)/)
    // New glass: no inset edge pseudo at all — the pane keeps only the lower refraction.
    expect(opticalGlassCss).not.toContain('.optical-glass::before')
    expect(opticalGlassCss).toMatch(/\.optical-glass::after\s*\{[\s\S]*?radial-gradient[\s\S]*?optical-glass-refraction-color/)
    expect(opticalGlassCss).not.toContain('conic-gradient')
    expect(opticalGlassCss).not.toContain('mask-composite')
    expect(contextMenuPanelSource).toMatch(/\.context-menu-panel-content\s*\{[\s\S]*?animation: popover-in var\(--dur-base\) var\(--ease-out\);/)
    expect(contextMenuPanelSource).not.toMatch(/\.context-menu-panel\s*\{[^}]*animation:/)
  })

  it('inherits menu text from the chat surface instead of control text', () => {
    expect(contextMenuPanelSource).toContain('--text: var(--theme-main-text);')
    expect(contextMenuPanelSource).not.toContain('--text: var(--theme-control-text);')
  })

  it('marks the focused row with the row highlight instead of a blue focus ring', () => {
    expect(contextMenuPanelSource).toMatch(
      /\.context-menu-item:focus-visible:not\(:disabled\)::before\s*\{[^}]*var\(--alpha-hover\)/,
    )
    const focusRingRule = contextMenuPanelSource.match(/\.context-menu-item:focus-visible\s*\{[^}]*\}/)?.[0] || ''
    expect(focusRingRule).toContain('outline: none')
    expect(contextMenuPanelSource).not.toMatch(/\.context-menu-item[^{}]*\{[^}]*outline:\s*2px/)
  })

  it('renders at the pointer, clamps to the viewport, and flips upward near the bottom-right edge', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 300 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 200 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('context-menu-panel')) {
        return { left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100 } as DOMRect
      }
      return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 } as DOMRect
    })

    const event = contextEvent(299, 199)
    const preventDefault = vi.spyOn(event, 'preventDefault')
    openContextMenu({
      event,
      items: [{ id: 'open', label: '打开', action: vi.fn() }],
    })
    await settleRender()

    const panel = menuPanel()
    expect(preventDefault).toHaveBeenCalled()
    expect(panel?.style.left).toBe('92px')
    expect(panel?.style.top).toBe('92px')
    expect(panel?.dataset.placement).toBe('up')
    expect(document.activeElement).toBe(menuButton(0))
  })

  it('renders an explicit anchor and a two-line description for switcher entries', async () => {
    const event = contextEvent(300, 300)
    openContextMenu({
      event,
      anchor: { type: 'point', x: 24, y: 96 },
      items: [
        { id: 'agent', label: 'Agent', description: '处理您的日常任务', action: vi.fn() },
        { id: 'study', label: 'Study', description: '学习、探索、温习', action: vi.fn() },
      ],
    })
    await settleRender()

    // 锚点生效：菜单不出现在鼠标点（300,300），而是贴着锚点。
    const panel = menuPanel()
    expect(panel?.style.left).toBe('24px')
    expect(panel?.style.top).toBe('96px')

    const item = menuButton(0)
    expect(item?.textContent).toContain('Agent')
    expect(item?.querySelector('.context-menu-item-description')?.textContent).toBe('处理您的日常任务')
    expect(contextMenuState.anchor).toEqual({ type: 'point', x: 24, y: 96 })
  })

  it('recognizes native editing, media, link, and control targets', () => {
    const input = document.createElement('input')
    const button = document.createElement('button')
    const image = document.createElement('img')
    const link = document.createElement('a')
    const editable = document.createElement('div')
    editable.setAttribute('contenteditable', 'plaintext-only')
    const codeMirror = document.createElement('div')
    codeMirror.className = 'cm-editor'
    const text = document.createElement('span')

    expect(isNativeContextTarget(input)).toBe(true)
    expect(isNativeContextTarget(button)).toBe(false)
    expect(isNativeContextTarget(image)).toBe(true)
    expect(isNativeContextTarget(link)).toBe(true)
    expect(isNativeContextTarget(editable)).toBe(true)
    expect(isNativeContextTarget(codeMirror)).toBe(true)
    expect(isNativeContextTarget(text)).toBe(false)
  })

  it('turns a stationary touch long-press into a desktop contextmenu at the held point', () => {
    vi.useFakeTimers()
    const target = document.createElement('button')
    const contextHandler = vi.fn((event: MouseEvent) => event.preventDefault())
    const clickHandler = vi.fn()
    target.addEventListener('contextmenu', contextHandler)
    target.addEventListener('click', clickHandler)
    document.body.appendChild(target)

    try {
      target.dispatchEvent(touchPointerEvent('pointerdown', 72, 96))
      vi.advanceTimersByTime(LONG_PRESS_CONTEXT_MENU_DELAY_MS - 1)
      expect(contextHandler).not.toHaveBeenCalled()

      vi.advanceTimersByTime(1)
      expect(contextHandler).toHaveBeenCalledTimes(1)
      const event = contextHandler.mock.calls[0]![0]
      expect(event.clientX).toBe(72)
      expect(event.clientY).toBe(96)
      expect(event.button).toBe(2)

      target.dispatchEvent(touchPointerEvent('pointerup', 72, 96))
      target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
      expect(clickHandler).not.toHaveBeenCalled()

      const duplicateNativeEvent = contextEvent(72, 96)
      target.dispatchEvent(duplicateNativeEvent)
      expect(duplicateNativeEvent.defaultPrevented).toBe(true)
      expect(contextHandler).toHaveBeenCalledTimes(1)
    } finally {
      target.remove()
      vi.runOnlyPendingTimers()
      vi.useRealTimers()
    }
  })

  it('cancels the touch long-press when the pointer moves away from its fixed point', () => {
    vi.useFakeTimers()
    const target = document.createElement('button')
    const contextHandler = vi.fn((event: MouseEvent) => event.preventDefault())
    target.addEventListener('contextmenu', contextHandler)
    document.body.appendChild(target)

    try {
      target.dispatchEvent(touchPointerEvent('pointerdown', 20, 30))
      target.dispatchEvent(touchPointerEvent('pointermove', 40, 30))
      vi.advanceTimersByTime(LONG_PRESS_CONTEXT_MENU_DELAY_MS)
      expect(contextHandler).not.toHaveBeenCalled()
    } finally {
      target.remove()
      vi.runOnlyPendingTimers()
      vi.useRealTimers()
    }
  })

  it('does not duplicate a native contextmenu that arrives before the long-press timer', () => {
    vi.useFakeTimers()
    const target = document.createElement('button')
    const contextHandler = vi.fn((event: MouseEvent) => event.preventDefault())
    target.addEventListener('contextmenu', contextHandler)
    document.body.appendChild(target)

    try {
      target.dispatchEvent(touchPointerEvent('pointerdown', 52, 68))
      vi.advanceTimersByTime(250)
      target.dispatchEvent(contextEvent(52, 68))
      vi.advanceTimersByTime(LONG_PRESS_CONTEXT_MENU_DELAY_MS)
      expect(contextHandler).toHaveBeenCalledTimes(1)
    } finally {
      target.remove()
      vi.runOnlyPendingTimers()
      vi.useRealTimers()
    }
  })

  it('keeps the native long-press menu when no LamTools context handler accepts it', () => {
    vi.useFakeTimers()
    const target = document.createElement('input')
    const contextHandler = vi.fn()
    target.addEventListener('contextmenu', contextHandler)
    document.body.appendChild(target)

    try {
      target.dispatchEvent(touchPointerEvent('pointerdown', 32, 44))
      vi.advanceTimersByTime(LONG_PRESS_CONTEXT_MENU_DELAY_MS)
      expect(contextHandler).not.toHaveBeenCalled()

      const nativeEvent = contextEvent(32, 44)
      target.dispatchEvent(nativeEvent)
      expect(nativeEvent.defaultPrevented).toBe(false)
      expect(contextHandler).toHaveBeenCalledTimes(1)
    } finally {
      target.remove()
      vi.runOnlyPendingTimers()
      vi.useRealTimers()
    }
  })

  it('preserves the native editing menu even when textarea text is selected', () => {
    const target = document.createElement('textarea')
    target.value = 'paste here'
    target.setSelectionRange(0, 5)
    document.body.appendChild(target)
    try {
      const event = contextEvent()
      target.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
      expect(menuPanel()).toBeNull()
    } finally {
      target.remove()
    }
  })

  it('opens copy and select-all actions for selected text while preserving unselected native targets', async () => {
    const plain = document.createElement('div')
    const button = document.createElement('button')
    const input = document.createElement('input')
    const selected = document.createElement('span')
    selected.textContent = 'selected text'
    document.body.append(plain, button, input, selected)

    const plainEvent = contextEvent()
    plain.dispatchEvent(plainEvent)
    expect(plainEvent.defaultPrevented).toBe(true)

    const buttonEvent = contextEvent()
    button.dispatchEvent(buttonEvent)
    expect(buttonEvent.defaultPrevented).toBe(true)

    const inputEvent = contextEvent()
    input.dispatchEvent(inputEvent)
    expect(inputEvent.defaultPrevented).toBe(false)

    const selection = window.getSelection()
    const range = document.createRange()
    range.selectNodeContents(selected)
    selection?.removeAllRanges()
    selection?.addRange(range)
    const selectedEvent = contextEvent()
    selected.dispatchEvent(selectedEvent)
    await settleRender()
    expect(selectedEvent.defaultPrevented).toBe(true)
    expect(menuPanel()?.hasAttribute('data-text-selection-menu')).toBe(true)
    expect(menuButton(0).textContent).toContain('复制')
    expect(menuButton(1).textContent).toContain('全选')

    selection?.removeAllRanges()
    plain.remove()
    button.remove()
    input.remove()
    selected.remove()
  })

  it('appends surface contributions to the shared text-selection menu', async () => {
    const selected = document.createElement('span')
    selected.textContent = 'selected text'
    document.body.appendChild(selected)
    const selection = window.getSelection()!
    const range = document.createRange()
    range.selectNodeContents(selected)
    selection.removeAllRanges()
    selection.addRange(range)
    const mark = vi.fn()
    const release = registerTextSelectionMenuContributor('test-surface', () => [
      { id: 'mark', label: '标记', action: mark },
    ])

    try {
      selected.dispatchEvent(contextEvent())
      await settleRender()
      expect(contextMenuState.items.filter(entry => entry.type !== 'separator').map(entry => 'label' in entry && entry.label))
        .toEqual(['复制', '全选', '标记'])
      expect(contextMenuState.items.some(entry => entry.type === 'separator')).toBe(true)
      expect(menuButton(3).textContent).toContain('标记')
    } finally {
      release()
      selection.removeAllRanges()
      selected.remove()
    }
  })

  it('keeps copy and select-all when a contributor declines or fails', async () => {
    const selected = document.createElement('span')
    selected.textContent = 'selected text'
    document.body.appendChild(selected)
    const selection = window.getSelection()!
    const range = document.createRange()
    range.selectNodeContents(selected)
    selection.removeAllRanges()
    selection.addRange(range)
    const releaseDeclining = registerTextSelectionMenuContributor('test-declining', () => null)
    const releaseThrowing = registerTextSelectionMenuContributor('test-throwing', () => { throw new Error('no selection scope') })

    try {
      selected.dispatchEvent(contextEvent())
      await settleRender()
      expect(contextMenuState.items.filter(entry => entry.type !== 'separator').map(entry => 'label' in entry && entry.label))
        .toEqual(['复制', '全选'])
      expect(contextMenuState.items.some(entry => entry.type === 'separator')).toBe(false)

      releaseThrowing()
      selected.dispatchEvent(contextEvent())
      await settleRender()
      expect(contextMenuState.items.filter(entry => entry.type !== 'separator').map(entry => 'label' in entry && entry.label))
        .toEqual(['复制', '全选'])
    } finally {
      releaseDeclining()
      releaseThrowing()
      selection.removeAllRanges()
      selected.remove()
    }
  })

  it('copies the exact selected text and lets select-all expand the selection', async () => {
    const scope = document.createElement('section')
    const first = document.createElement('span')
    const second = document.createElement('span')
    const outside = document.createElement('aside')
    first.textContent = 'selected text'
    second.textContent = 'more text'
    outside.textContent = 'outside text'
    scope.append(first, second)
    document.body.append(scope, outside)
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })

    const selection = window.getSelection()!
    const range = document.createRange()
    range.selectNodeContents(first)
    selection.removeAllRanges()
    selection.addRange(range)

    first.dispatchEvent(contextEvent())
    await settleRender()
    menuButton(0).click()
    await settleRender()
    expect(writeText).toHaveBeenCalledWith('selected text')

    selection.removeAllRanges()
    range.selectNodeContents(first)
    selection.addRange(range)
    first.dispatchEvent(contextEvent())
    await settleRender()
    menuButton(1).click()
    await settleRender()
    expect(selection.toString()).toContain('selected text')
    expect(selection.toString()).toContain('more text')
    expect(selection.toString()).not.toContain('outside text')

    selection.removeAllRanges()
    scope.remove()
    outside.remove()
  })

  it('uses roving tabindex and skips separators, labels, and disabled entries', async () => {
    const firstAction = vi.fn()
    const secondAction = vi.fn()
    const items: ContextMenuEntry[] = [
      { type: 'label', label: '操作' },
      { type: 'separator' },
      { id: 'disabled', label: '不可用', disabled: true, action: vi.fn() },
      { id: 'first', label: '第一项', action: firstAction },
      { id: 'second', label: '第二项', action: secondAction },
    ]

    openContextMenu({ event: contextEvent(), items })
    await settleRender()

    expect(menuButton(2).disabled).toBe(true)
    expect(menuButton(3).tabIndex).toBe(0)
    expect(menuButton(4).tabIndex).toBe(-1)
    expect(document.activeElement).toBe(menuButton(3))

    menuButton(3).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(menuButton(4))

    menuButton(4).dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(menuButton(3))

    menuButton(3).dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(menuButton(4))

    menuButton(4).dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    await settleRender()
    expect(secondAction).toHaveBeenCalledOnce()
    expect(firstAction).not.toHaveBeenCalled()
    expect(contextMenuState.open).toBe(false)
  })

  it('opens a submenu, flips it to the left when needed, and runs its action', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 350 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('context-menu-panel')) {
        return { left: 0, top: 0, right: 200, bottom: 100, width: 200, height: 100 } as DOMRect
      }
      if (this.matches('[data-context-menu-index="0"]')) {
        return { left: 280, top: 20, right: 340, bottom: 52, width: 60, height: 32 } as DOMRect
      }
      return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 } as DOMRect
    })

    const childAction = vi.fn()
    openContextMenu({
      event: contextEvent(16, 16),
      items: [{
        type: 'submenu',
        id: 'export',
        label: '导出',
        children: [{ id: 'markdown', label: 'Markdown', action: childAction }],
      }],
    })
    await settleRender()

    menuButton(0).dispatchEvent(new Event('pointerenter', { bubbles: true }))
    await settleRender()

    const submenu = menuPanel(1)
    expect(submenu).not.toBeNull()
    expect(submenu?.dataset.placement).toBe('left')
    expect(submenu?.style.left).toBe('76px')

    menuButton(0, 1).click()
    await settleRender()
    expect(childAction).toHaveBeenCalledOnce()
    expect(contextMenuState.open).toBe(false)
  })

  it('clears an expanded submenu when another menu replaces it', async () => {
    openContextMenu({
      event: contextEvent(),
      ownerId: 'first',
      items: [{
        type: 'submenu',
        label: '更多',
        children: [{ label: '第一项', action: vi.fn() }],
      }],
    })
    await settleRender()
    menuButton(0).dispatchEvent(new Event('pointerenter', { bubbles: true }))
    await settleRender()
    expect(menuPanel(1)).not.toBeNull()

    openContextMenu({
      event: contextEvent(120, 120),
      ownerId: 'second',
      items: [{ label: '新菜单', action: vi.fn() }],
    })
    await settleRender()

    expect(menuPanel(1)).toBeNull()
    expect(menuPanel(0)?.textContent).toContain('新菜单')
  })

  it('renders semantic groups with collapsible heads and remembers their state', async () => {
    const fileGroup = { id: 'test.file', label: '文件' }
    const organizeGroup = { id: 'test.organize', label: '整理' }
    openContextMenu({
      event: contextEvent(),
      items: [
        { id: 'open', label: '打开', group: fileGroup, action: vi.fn() },
        { id: 'copy', label: '复制路径', group: fileGroup, action: vi.fn() },
        { id: 'favorite', label: '添加到收藏', group: organizeGroup, action: vi.fn() },
        { id: 'remove', label: '移除', destructive: true, action: vi.fn() },
      ],
    })
    await settleRender()

    const heads = menuPanel()!.querySelectorAll<HTMLButtonElement>('.context-menu-group-head')
    expect(heads).toHaveLength(2)
    expect(heads[0]!.textContent).toContain('文件')
    expect(heads[1]!.textContent).toContain('整理')
    // 缺省全展开。
    expect(heads[0]!.getAttribute('aria-checked')).toBe('true')
    expect(menuPanel()!.querySelector('.context-menu-group-body.is-collapsed')).toBeNull()

    // 点击组头折叠：组体收起并写进记忆，另一组不受影响。
    heads[0]!.click()
    await settleRender()
    const collapsed = menuPanel()!.querySelector('.context-menu-group-body.is-collapsed')
    expect(collapsed).not.toBeNull()
    expect(collapsed!.getAttribute('aria-hidden')).toBe('true')
    expect(isMenuGroupCollapsed('test.file')).toBe(true)
    expect(isMenuGroupCollapsed('test.organize')).toBe(false)

    // 记忆跨开关生效：重开同一菜单，文件组仍是折叠的。
    closeContextMenu()
    await settleRender()
    openContextMenu({
      event: contextEvent(),
      items: [
        { id: 'open', label: '打开', group: fileGroup, action: vi.fn() },
        { id: 'copy', label: '复制路径', group: fileGroup, action: vi.fn() },
      ],
    })
    await settleRender()
    expect(menuPanel()!.querySelector('.context-menu-group-body.is-collapsed')).not.toBeNull()

    // 再次点组头展开，记忆同步翻转。
    menuPanel()!.querySelector<HTMLButtonElement>('.context-menu-group-head')!.click()
    await settleRender()
    expect(isMenuGroupCollapsed('test.file')).toBe(false)
  })

  it('honors defaultCollapsed and skips collapsed entries in keyboard navigation', async () => {
    const archiveGroup = { id: 'test.archive', label: '归档', defaultCollapsed: true }
    openContextMenu({
      event: contextEvent(),
      items: [
        { id: 'a1', label: '归档一', group: archiveGroup, action: vi.fn() },
        { id: 'a2', label: '归档二', group: archiveGroup, action: vi.fn() },
        { id: 'top', label: '置顶操作', action: vi.fn() },
        { id: 'bottom', label: '末尾操作', action: vi.fn() },
      ],
    })
    await settleRender()

    // 缺省收起生效；初始焦点跳过隐藏条目落在第一个可达项上。
    expect(menuPanel()!.querySelector('.context-menu-group-body.is-collapsed')).not.toBeNull()
    expect(document.activeElement).toBe(menuButton(2))

    // 键盘导航跳过折叠组里的条目。
    menuButton(2).dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    await nextTick()
    expect(document.activeElement).toBe(menuButton(3))

    // 用户展开一次后，记忆覆盖缺省值。
    setMenuGroupCollapsed('test.archive', false)
    await nextTick()
    expect(menuPanel()!.querySelector('.context-menu-group-body.is-collapsed')).toBeNull()
  })

  it('keeps the panel inside the window when its measured size settles late', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 400 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 300 })
    let measuredHeight = 60
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('context-menu-panel')) {
        return { left: 0, top: 0, right: 200, bottom: measuredHeight, width: 200, height: measuredHeight } as DOMRect
      }
      return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 } as DOMRect
    })

    openContextMenu({ event: contextEvent(40, 40), items: [{ id: 'a', label: 'A', action: vi.fn() }] })
    await settleRender()
    expect(menuPanel()?.style.top).toBe('40px')

    // 实际高度随后长到 280px（条目渲染、字体就绪都会造成）：重定位必须把
    // 面板压回窗口内，底边不得越过窗口下缘减去安全边距。
    measuredHeight = 280
    const exposed = (host!.findComponent(ContextMenuPanel).vm.$ as unknown as {
      exposed?: { reposition?: () => void }
    }).exposed
    expect(typeof exposed?.reposition).toBe('function')
    exposed!.reposition!()
    await settleRender()
    const top = Number.parseInt(menuPanel()?.style.top ?? '', 10)
    expect(top).toBeLessThanOrEqual(300 - 280 - 8)
  })

  it('animates entry, exit, group folding, and falls back for reduced motion', () => {
    // 出场是内容层的 popover-in（既有契约）；退场是面板层短淡出；
    // 组折叠与箭头转向都有过渡；减弱动态下全部退化为直切。
    expect(contextMenuPanelSource).toMatch(/\.context-menu-leave-active\s*\{[^}]*transition: opacity/)
    expect(contextMenuPanelSource).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.context-menu-leave-active\s*\{[^}]*transition: none/)
    expect(contextMenuPanelSource).toMatch(/\.context-menu-group-body\s*\{[^}]*grid-template-rows: 1fr/)
    expect(contextMenuPanelSource).toMatch(/\.context-menu-group-body\.is-collapsed\s*\{[^}]*grid-template-rows: 0fr/)
    expect(contextMenuPanelSource).toMatch(/\.context-menu-group-chevron\s*\{[^}]*transition: transform/)
    expect(contextMenuPanelSource).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.context-menu-group-body,\s*\n\s*\.context-menu-group-chevron\s*\{[^}]*transition: none/)
    // 尺寸稳定后的重定位回路真实存在。
    expect(contextMenuPanelSource).toContain('new ResizeObserver')
    expect(contextMenuPanelSource).toContain('requestAnimationFrame')
  })

  it('closes on outside input, Escape, scroll, resize, and window blur', async () => {
    const reopen = async (): Promise<void> => {
      openContextMenu({ event: contextEvent(), items: [{ label: '打开', action: vi.fn() }] })
      await settleRender()
      expect(contextMenuState.open).toBe(true)
    }

    await reopen()
    document.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await settleRender()
    expect(contextMenuState.open).toBe(false)

    await reopen()
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    await settleRender()
    expect(contextMenuState.open).toBe(false)

    await reopen()
    document.dispatchEvent(new Event('scroll', { bubbles: true }))
    await settleRender()
    expect(contextMenuState.open).toBe(false)

    await reopen()
    window.dispatchEvent(new Event('resize'))
    await settleRender()
    expect(contextMenuState.open).toBe(false)

    await reopen()
    window.dispatchEvent(new Event('blur'))
    await settleRender()
    expect(contextMenuState.open).toBe(false)
  })

  it('restores focus, replaces menus for another target, and leaves trigger toggles to the owner', async () => {
    const source = document.createElement('button')
    source.textContent = 'source'
    document.body.appendChild(source)
    source.focus()

    openContextMenu({
      event: contextEvent(),
      ownerId: 'first',
      items: [{ label: '第一菜单', action: vi.fn() }],
    })
    await settleRender()
    expect(document.activeElement).toBe(menuButton(0))

    closeContextMenu()
    await Promise.resolve()
    expect(document.activeElement).toBe(source)
    source.focus()

    openContextMenu({
      event: contextEvent(),
      ownerId: 'first',
      items: [{ label: '第一菜单', action: vi.fn() }],
    })
    await settleRender()

    const trigger = document.createElement('button')
    trigger.setAttribute('data-context-menu-trigger', '')
    document.body.appendChild(trigger)
    trigger.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
    await nextTick()
    expect(contextMenuState.open).toBe(true)

    openContextMenu({
      event: contextEvent(80, 80),
      ownerId: 'second',
      items: [{ label: '第二菜单', action: vi.fn() }],
    })
    await settleRender()
    expect(contextMenuState.ownerId).toBe('second')
    expect(document.querySelectorAll('[data-context-menu-level="0"]')).toHaveLength(1)

    closeContextMenu()

    source.remove()
    trigger.remove()
  })

  it('closes when the host is unmounted', async () => {
    openContextMenu({ event: contextEvent(), items: [{ label: '打开', action: vi.fn() }] })
    await settleRender()
    expect(contextMenuState.open).toBe(true)

    host!.unmount()
    host = null
    expect(contextMenuState.open).toBe(false)
  })
})

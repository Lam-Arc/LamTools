import { shallowReactive } from 'vue'
import type { ContextMenuEntry, ContextMenuAttributes, OpenContextMenuOptions } from './types'

export interface ContextMenuState {
  /** Changes for every open call, including replacement of an already open menu. */
  revision: number
  open: boolean
  x: number
  y: number
  items: ContextMenuEntry[]
  ownerId?: string
  panelAttributes?: ContextMenuAttributes
  ariaLabel: string
}

export const contextMenuState = shallowReactive<ContextMenuState>({
  revision: 0,
  open: false,
  x: 0,
  y: 0,
  items: [],
  ownerId: undefined,
  panelAttributes: undefined,
  ariaLabel: '上下文菜单',
})

const NATIVE_CONTEXT_TARGET_SELECTOR = [
  'input',
  'textarea',
  'select',
  'a',
  'img',
  'video',
  'audio',
  'iframe',
  '.cm-editor',
  '[contenteditable]',
  'pre',
  'code',
].join(', ')

/** Elements whose browser editing/media context menu must remain available. */
export function isNativeContextTarget(target: EventTarget | null): boolean {
  return typeof Element !== 'undefined'
    && target instanceof Element
    && Boolean(target.closest(NATIVE_CONTEXT_TARGET_SELECTOR))
}

function hasTextSelectionAtTarget(target: EventTarget | null): boolean {
  if (typeof window === 'undefined' || typeof Node === 'undefined' || !(target instanceof Node)) return false
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || !selection.toString().trim()) return false

  try {
    return selection.containsNode(target, true)
      || Boolean(selection.anchorNode && target.contains(selection.anchorNode))
      || Boolean(selection.focusNode && target.contains(selection.focusNode))
  } catch {
    return false
  }
}

/** Whether the browser should keep its editing/selection/media context menu. */
export function shouldPreserveNativeContextMenu(event: MouseEvent): boolean {
  return isNativeContextTarget(event.target) || hasTextSelectionAtTarget(event.target)
}

let contextMenuGuardConsumers = 0
let contextMenuGuardInstalled = false

function handleDocumentContextMenu(event: MouseEvent): void {
  if (!shouldPreserveNativeContextMenu(event)) event.preventDefault()
}

/** Suppress WebView's default menu everywhere except explicit native targets. */
export function installContextMenuGuard(): void {
  if (typeof document === 'undefined') return
  contextMenuGuardConsumers += 1
  if (contextMenuGuardInstalled) return
  contextMenuGuardInstalled = true
  document.addEventListener('contextmenu', handleDocumentContextMenu, true)
}

export function removeContextMenuGuard(): void {
  if (typeof document === 'undefined' || contextMenuGuardConsumers === 0) return
  contextMenuGuardConsumers -= 1
  if (contextMenuGuardConsumers > 0 || !contextMenuGuardInstalled) return
  contextMenuGuardInstalled = false
  document.removeEventListener('contextmenu', handleDocumentContextMenu, true)
}

export const LONG_PRESS_CONTEXT_MENU_DELAY_MS = 500
const LONG_PRESS_MOVE_TOLERANCE_PX = 10
const LONG_PRESS_DUPLICATE_WINDOW_MS = 750

let longPressConsumers = 0
let longPressInstalled = false
let longPressTimer: ReturnType<typeof setTimeout> | null = null
let longPressPointerId: number | null = null
let longPressTarget: Element | null = null
let longPressOrigin = { x: 0, y: 0 }
let suppressClickTarget: Element | null = null
let suppressClickUntil = 0
let suppressNativeContextMenuTarget: Element | null = null
let suppressNativeContextMenuUntil = 0
let longPressSuppressionTimer: ReturnType<typeof setTimeout> | null = null
const syntheticContextMenuEvents = new WeakSet<Event>()

function clearLongPressCandidate(): void {
  if (longPressTimer !== null) clearTimeout(longPressTimer)
  longPressTimer = null
  longPressPointerId = null
  longPressTarget = null
}

function clearLongPressSuppression(): void {
  if (longPressSuppressionTimer !== null) clearTimeout(longPressSuppressionTimer)
  longPressSuppressionTimer = null
  suppressClickTarget = null
  suppressClickUntil = 0
  suppressNativeContextMenuTarget = null
  suppressNativeContextMenuUntil = 0
}

function targetsOverlap(left: EventTarget | null, right: Element | null): boolean {
  return typeof Node !== 'undefined'
    && left instanceof Node
    && Boolean(right && (left === right || right.contains(left) || left.contains(right)))
}

function handleLongPressPointerDown(event: PointerEvent): void {
  if (event.pointerType !== 'touch' || !event.isPrimary || event.button !== 0) return
  if (!(event.target instanceof Element) || isContextMenuElement(event.target)) return

  clearLongPressCandidate()
  longPressPointerId = event.pointerId
  longPressTarget = event.target
  longPressOrigin = { x: event.clientX, y: event.clientY }
  longPressTimer = setTimeout(() => {
    const target = longPressTarget
    if (!target?.isConnected) {
      clearLongPressCandidate()
      return
    }

    const contextEvent = new MouseEvent('contextmenu', {
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: longPressOrigin.x,
      clientY: longPressOrigin.y,
      button: 2,
      buttons: 0,
    })
    syntheticContextMenuEvents.add(contextEvent)
    target.dispatchEvent(contextEvent)

    // Native targets without a LamTools right-click handler keep the platform
    // selection/copy menu. Only suppress the following native event and click
    // when the synthetic desktop-equivalent context menu was actually handled.
    if (contextEvent.defaultPrevented) {
      const now = Date.now()
      clearLongPressSuppression()
      suppressClickTarget = target
      suppressClickUntil = now + LONG_PRESS_DUPLICATE_WINDOW_MS
      suppressNativeContextMenuTarget = target
      suppressNativeContextMenuUntil = now + LONG_PRESS_DUPLICATE_WINDOW_MS
      longPressSuppressionTimer = setTimeout(clearLongPressSuppression, LONG_PRESS_DUPLICATE_WINDOW_MS)
    }
    longPressTimer = null
  }, LONG_PRESS_CONTEXT_MENU_DELAY_MS)
}

function handleLongPressPointerMove(event: PointerEvent): void {
  if (event.pointerId !== longPressPointerId) return
  const deltaX = event.clientX - longPressOrigin.x
  const deltaY = event.clientY - longPressOrigin.y
  if (deltaX * deltaX + deltaY * deltaY > LONG_PRESS_MOVE_TOLERANCE_PX ** 2) {
    clearLongPressCandidate()
  }
}

function handleLongPressPointerEnd(event: PointerEvent): void {
  if (event.pointerId !== longPressPointerId) return
  clearLongPressCandidate()
}

function handleLongPressClick(event: MouseEvent): void {
  const now = Date.now()
  if (now > suppressClickUntil) {
    suppressClickTarget = null
    return
  }
  if (!targetsOverlap(event.target, suppressClickTarget)) return
  event.preventDefault()
  event.stopImmediatePropagation()
  suppressClickTarget = null
  suppressClickUntil = 0
}

function handleLongPressNativeContextMenu(event: MouseEvent): void {
  if (syntheticContextMenuEvents.has(event)) return
  if (targetsOverlap(event.target, longPressTarget)) clearLongPressCandidate()
  if (Date.now() > suppressNativeContextMenuUntil) {
    suppressNativeContextMenuTarget = null
    return
  }
  if (!targetsOverlap(event.target, suppressNativeContextMenuTarget)) return
  event.preventDefault()
  event.stopImmediatePropagation()
  suppressNativeContextMenuTarget = null
  suppressNativeContextMenuUntil = 0
}

function handleLongPressScroll(): void {
  clearLongPressCandidate()
}

/** Make a stationary touch long-press behave like a desktop right-click. */
export function installLongPressContextMenu(): void {
  if (typeof document === 'undefined') return
  longPressConsumers += 1
  if (longPressInstalled) return
  longPressInstalled = true
  document.addEventListener('pointerdown', handleLongPressPointerDown, true)
  document.addEventListener('pointermove', handleLongPressPointerMove, true)
  document.addEventListener('pointerup', handleLongPressPointerEnd, true)
  document.addEventListener('pointercancel', handleLongPressPointerEnd, true)
  document.addEventListener('click', handleLongPressClick, true)
  document.addEventListener('contextmenu', handleLongPressNativeContextMenu, true)
  document.addEventListener('scroll', handleLongPressScroll, true)
}

export function removeLongPressContextMenu(): void {
  if (typeof document === 'undefined' || longPressConsumers === 0) return
  longPressConsumers -= 1
  if (longPressConsumers > 0 || !longPressInstalled) return
  longPressInstalled = false
  clearLongPressCandidate()
  clearLongPressSuppression()
  document.removeEventListener('pointerdown', handleLongPressPointerDown, true)
  document.removeEventListener('pointermove', handleLongPressPointerMove, true)
  document.removeEventListener('pointerup', handleLongPressPointerEnd, true)
  document.removeEventListener('pointercancel', handleLongPressPointerEnd, true)
  document.removeEventListener('click', handleLongPressClick, true)
  document.removeEventListener('contextmenu', handleLongPressNativeContextMenu, true)
  document.removeEventListener('scroll', handleLongPressScroll, true)
}

let restoreFocusTarget: HTMLElement | null = null
let closeCallback: (() => void) | undefined
let listenersInstalled = false

function isContextMenuElement(target: EventTarget | null): boolean {
  return typeof Element !== 'undefined'
    && target instanceof Element
    && Boolean(target.closest('[data-context-menu-panel]'))
}

function isContextMenuTrigger(target: EventTarget | null): boolean {
  return typeof Element !== 'undefined'
    && target instanceof Element
    && Boolean(target.closest('[data-context-menu-trigger]'))
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!isContextMenuElement(event.target) && !isContextMenuTrigger(event.target)) closeContextMenu()
}

function handleDocumentKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape' || event.key === 'Tab') closeContextMenu()
}

function handleDocumentScroll(): void {
  closeContextMenu()
}

function handleWindowResize(): void {
  closeContextMenu()
}

function handleWindowBlur(): void {
  closeContextMenu()
}

function installListeners(): void {
  if (listenersInstalled || typeof document === 'undefined' || typeof window === 'undefined') return
  listenersInstalled = true
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
  document.addEventListener('keydown', handleDocumentKeyDown)
  document.addEventListener('scroll', handleDocumentScroll, true)
  window.addEventListener('resize', handleWindowResize)
  window.addEventListener('blur', handleWindowBlur)
  window.addEventListener('popstate', handleWindowResize)
  window.addEventListener('hashchange', handleWindowResize)
}

function removeListeners(): void {
  if (!listenersInstalled || typeof document === 'undefined' || typeof window === 'undefined') return
  listenersInstalled = false
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
  document.removeEventListener('keydown', handleDocumentKeyDown)
  document.removeEventListener('scroll', handleDocumentScroll, true)
  window.removeEventListener('resize', handleWindowResize)
  window.removeEventListener('blur', handleWindowBlur)
  window.removeEventListener('popstate', handleWindowResize)
  window.removeEventListener('hashchange', handleWindowResize)
}

export function isContextMenuOpen(ownerId?: string): boolean {
  return contextMenuState.open && (ownerId === undefined || contextMenuState.ownerId === ownerId)
}

export function openContextMenu(options: OpenContextMenuOptions): void {
  if (!options.items.length) return

  options.event.preventDefault()
  options.event.stopPropagation()

  // Opening another menu is a replacement, not a focus restore boundary.
  closeContextMenu({ restoreFocus: false })

  restoreFocusTarget = typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  closeCallback = options.onClose
  contextMenuState.revision += 1
  contextMenuState.open = true
  contextMenuState.x = options.event.clientX
  contextMenuState.y = options.event.clientY
  contextMenuState.items = options.items
  contextMenuState.ownerId = options.ownerId
  contextMenuState.panelAttributes = options.panelAttributes
  contextMenuState.ariaLabel = options.ariaLabel || '上下文菜单'
  installListeners()
}

export function closeContextMenu(options: { restoreFocus?: boolean } = {}): void {
  if (!contextMenuState.open && !closeCallback) return

  const shouldRestoreFocus = options.restoreFocus !== false
  const focusTarget = restoreFocusTarget
  const callback = closeCallback
  restoreFocusTarget = null
  closeCallback = undefined
  contextMenuState.open = false
  contextMenuState.items = []
  contextMenuState.ownerId = undefined
  contextMenuState.panelAttributes = undefined
  removeListeners()

  callback?.()
  if (shouldRestoreFocus && focusTarget?.isConnected) {
    queueMicrotask(() => {
      if (focusTarget.isConnected) focusTarget.focus({ preventScroll: true })
    })
  }
}

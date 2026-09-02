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

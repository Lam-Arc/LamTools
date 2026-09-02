import type { Component } from 'vue'

export type ContextMenuAttributeValue = string | number | boolean | undefined
export type ContextMenuAttributes = Record<string, ContextMenuAttributeValue>

export interface ContextMenuAction {
  type?: 'item'
  id?: string
  label: string
  icon?: Component
  shortcut?: string
  disabled?: boolean
  destructive?: boolean
  attributes?: ContextMenuAttributes
  action: () => void | Promise<void>
}

export interface ContextMenuSeparator {
  type: 'separator'
  id?: string
}

export interface ContextMenuLabel {
  type: 'label'
  id?: string
  label: string
}

export interface ContextMenuSubmenu {
  type: 'submenu'
  id?: string
  label: string
  icon?: Component
  disabled?: boolean
  attributes?: ContextMenuAttributes
  panelAttributes?: ContextMenuAttributes
  children: ContextMenuEntry[]
}

export type ContextMenuEntry =
  | ContextMenuAction
  | ContextMenuSeparator
  | ContextMenuLabel
  | ContextMenuSubmenu

export type ContextMenuPointAnchor = {
  type: 'point'
  x: number
  y: number
}

export type ContextMenuRectAnchor = {
  type: 'rect'
  left: number
  right: number
  top: number
  bottom: number
}

export type ContextMenuAnchor = ContextMenuPointAnchor | ContextMenuRectAnchor

export interface OpenContextMenuOptions {
  event: MouseEvent
  items: ContextMenuEntry[]
  /** Stable owner id used by triggers to reflect aria-expanded/toggle state. */
  ownerId?: string
  /** Attributes applied to the root panel, useful for stable integration hooks. */
  panelAttributes?: ContextMenuAttributes
  ariaLabel?: string
  onClose?: () => void
}

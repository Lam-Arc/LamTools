import type { Component } from 'vue'

export type ContextMenuAttributeValue = string | number | boolean | undefined
export type ContextMenuAttributes = Record<string, ContextMenuAttributeValue>

/** 语义分组：面板把它管辖的连续条目收进一个可折叠的组。 */
export interface ContextMenuGroupMeta {
  /** 稳定 id：折叠状态按它记忆（跨开关、跨会话）。 */
  id: string
  label: string
  /** 缺省展开；确有超长菜单需要默认收起时由宿主显式声明。 */
  defaultCollapsed?: boolean
}

export interface ContextMenuAction {
  type?: 'item'
  id?: string
  label: string
  /** 小字说明，渲染在标签下方（如模式切换的一句话描述）。 */
  description?: string
  icon?: Component
  /** 选中标记：渲染在行右侧的对号（如模式切换的当前项）。 */
  checked?: boolean
  shortcut?: string
  disabled?: boolean
  destructive?: boolean
  /** 语义分组：同组且相邻的条目共用一个可折叠组头。 */
  group?: ContextMenuGroupMeta
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
  /** 语义分组：同组且相邻的条目共用一个可折叠组头。 */
  group?: ContextMenuGroupMeta
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
  /** 固定锚点（贴住触发按钮）；不给则跟随鼠标点击位置。 */
  anchor?: ContextMenuAnchor
  /** Stable owner id used by triggers to reflect aria-expanded/toggle state. */
  ownerId?: string
  /** Attributes applied to the root panel, useful for stable integration hooks. */
  panelAttributes?: ContextMenuAttributes
  ariaLabel?: string
  onClose?: () => void
}

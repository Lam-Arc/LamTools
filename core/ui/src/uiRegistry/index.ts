import { UI_REGISTRY } from './registry.ts'
import type { UiRegistryEntry } from './types.ts'

/**
 * 注册表查询入口。
 *
 * user:“新增核心功能：主题设置 → 可视化界面编辑器”+
 * (编辑器与运行端都从这里取元素清单，不各自维护一份。)
 */
export type { UiEditableProperty, UiProtectionLevel, UiRegistryEntry } from './types.ts'
export { UI_REGISTRY } from './registry.ts'

/** 按标识取一条登记；未登记返回 undefined。 */
export function findUiEntry(id: string): UiRegistryEntry | undefined {
  return UI_REGISTRY.find((entry) => entry.id === id)
}

/** 取某个元素的直接子元素。 */
export function uiChildrenOf(id: string): UiRegistryEntry[] {
  return UI_REGISTRY.filter((entry) => entry.parent === id)
}

/** 没有父级的顶层元素。 */
export function uiRootEntries(): UiRegistryEntry[] {
  return UI_REGISTRY.filter((entry) => !entry.parent)
}

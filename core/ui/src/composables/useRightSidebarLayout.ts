import { computed, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import type { RightSidebarLayoutController, RightSidebarLayoutState } from '../right-sidebar/types'

export interface RightSidebarModuleDefaults {
  visible?: boolean
  collapsed?: boolean
}

export interface RightSidebarLayoutOptions {
  storageKey?: string
  moduleIds: MaybeRefOrGetter<string[]>
  moduleDefaults?: MaybeRefOrGetter<Record<string, RightSidebarModuleDefaults>>
  activeProjectId?: MaybeRefOrGetter<string | null | undefined>
}

interface StoredRightSidebarLayout {
  version?: number
  global?: Partial<RightSidebarLayoutState>
  projects?: Record<string, Partial<RightSidebarLayoutState>>
  // Pre-release builds briefly wrote the state directly.  Reading that shape
  // keeps users from losing a small amount of sidebar customisation.
  order?: unknown
  visible?: unknown
  collapsed?: unknown
}

const DEFAULT_STORAGE_KEY = 'lamtools.ui.right-sidebar'

function emptyLayout(): RightSidebarLayoutState {
  return { order: [], visible: {}, collapsed: {} }
}

function normalizeState(
  value: unknown,
  moduleIds: string[],
  defaults: Record<string, RightSidebarModuleDefaults>,
): RightSidebarLayoutState {
  const input = value && typeof value === 'object' ? value as Partial<RightSidebarLayoutState> : {}
  const rawOrder = Array.isArray(input.order) ? input.order : []
  const known = new Set(moduleIds)
  const order: string[] = []
  for (const id of rawOrder) {
    if (typeof id === 'string' && known.has(id) && !order.includes(id)) order.push(id)
  }
  for (const id of moduleIds) if (!order.includes(id)) order.push(id)

  const visible: Record<string, boolean> = {}
  const collapsed: Record<string, boolean> = {}
  const rawVisible = input.visible && typeof input.visible === 'object' ? input.visible : {}
  const rawCollapsed = input.collapsed && typeof input.collapsed === 'object' ? input.collapsed : {}
  for (const id of moduleIds) {
    const configuredVisible = (rawVisible as Record<string, unknown>)[id]
    const configuredCollapsed = (rawCollapsed as Record<string, unknown>)[id]
    visible[id] = typeof configuredVisible === 'boolean'
      ? configuredVisible
      : defaults[id]?.visible !== false
    collapsed[id] = typeof configuredCollapsed === 'boolean'
      ? configuredCollapsed
      : defaults[id]?.collapsed === true
  }
  return { order, visible, collapsed }
}

function readStore(storageKey: string): StoredRightSidebarLayout {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return {}
    const value = JSON.parse(raw)
    return value && typeof value === 'object' ? value as StoredRightSidebarLayout : {}
  } catch {
    return {}
  }
}

function writeStore(storageKey: string, store: StoredRightSidebarLayout): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(store))
  } catch {
    // Sidebar preferences are best effort in private mode/quota-restricted
    // WebViews and should never make the workspace unusable.
  }
}

function hasLayout(value: unknown): value is Partial<RightSidebarLayoutState> {
  return Boolean(value && typeof value === 'object')
}

/**
 * Per-project right-sidebar layout persistence.
 *
 * A project with no saved entry starts from the global layout.  The first
 * project edit then forks that state into its own entry, so global changes do
 * not unexpectedly overwrite deliberate project customisation.
 */
export function useRightSidebarLayout(options: RightSidebarLayoutOptions): RightSidebarLayoutController {
  const storageKey = options.storageKey || DEFAULT_STORAGE_KEY
  const project = computed<string | null>(() => {
    const value = options.activeProjectId === undefined ? null : toValue(options.activeProjectId)
    return typeof value === 'string' && value.trim() ? value : null
  })
  const layout = ref<RightSidebarLayoutState>(emptyLayout())
  const isProjectScope = computed(() => project.value !== null)
  let activeScope: string | null = null

  function moduleIds(): string[] {
    const seen = new Set<string>()
    const ids: string[] = []
    for (const id of toValue(options.moduleIds) || []) {
      if (typeof id !== 'string' || !id || seen.has(id)) continue
      seen.add(id)
      ids.push(id)
    }
    return ids
  }

  function moduleDefaults(): Record<string, RightSidebarModuleDefaults> {
    const value = options.moduleDefaults === undefined ? {} : toValue(options.moduleDefaults)
    return value && typeof value === 'object' ? value : {}
  }

  function load(scope: string | null = project.value): void {
    const ids = moduleIds()
    const defaults = moduleDefaults()
    const store = readStore(storageKey)
    const legacy = hasLayout(store) && (store.order !== undefined || store.visible !== undefined || store.collapsed !== undefined)
      ? store
      : undefined
    const global = hasLayout(store.global) ? store.global : legacy
    const scoped = scope && store.projects && hasLayout(store.projects[scope])
      ? store.projects[scope]
      : undefined
    activeScope = scope
    layout.value = normalizeState(scoped || global, ids, defaults)
  }

  function save(): void {
    const store = readStore(storageKey)
    const state = normalizeState(layout.value, moduleIds(), moduleDefaults())
    // Keep the in-memory value canonical when modules are added by a plugin.
    layout.value = state
    if (activeScope) {
      store.version = 1
      store.projects = { ...(store.projects || {}), [activeScope]: state }
    } else {
      store.version = 1
      store.global = state
    }
    writeStore(storageKey, store)
  }

  function setProject(projectId: string | null): void {
    const next = typeof projectId === 'string' && projectId.trim() ? projectId : null
    if (next === activeScope && project.value === next) return
    load(next)
  }

  function syncModules(): void {
    const ids = moduleIds()
    const defaults = moduleDefaults()
    const next = normalizeState(layout.value, ids, defaults)
    const changed = JSON.stringify(next) !== JSON.stringify(layout.value)
    if (changed) layout.value = next
  }

  function setVisible(moduleId: string, visible: boolean): void {
    syncModules()
    layout.value = {
      ...layout.value,
      visible: { ...layout.value.visible, [moduleId]: visible },
    }
    save()
  }

  function toggleVisible(moduleId: string): void {
    setVisible(moduleId, layout.value.visible[moduleId] === false)
  }

  function setCollapsed(moduleId: string, collapsed: boolean): void {
    syncModules()
    layout.value = {
      ...layout.value,
      collapsed: { ...layout.value.collapsed, [moduleId]: collapsed },
    }
    save()
  }

  function toggleCollapsed(moduleId: string): void {
    setCollapsed(moduleId, layout.value.collapsed[moduleId] !== true)
  }

  function reorder(moduleIdsInOrder: string[]): void {
    const known = new Set(moduleIds())
    const order: string[] = []
    for (const id of moduleIdsInOrder) {
      if (known.has(id) && !order.includes(id)) order.push(id)
    }
    for (const id of moduleIds()) if (!order.includes(id)) order.push(id)
    layout.value = { ...layout.value, order }
    save()
  }

  function move(moduleId: string, direction: -1 | 1): void {
    const order = [...layout.value.order]
    const index = order.indexOf(moduleId)
    const target = index + direction
    if (index < 0 || target < 0 || target >= order.length) return
    const [moved] = order.splice(index, 1)
    order.splice(target, 0, moved)
    reorder(order)
  }

  function reset(): void {
    layout.value = normalizeState(emptyLayout(), moduleIds(), moduleDefaults())
    save()
  }

  watch(
    [() => toValue(options.moduleIds), project],
    ([, nextProject], [, previousProject]) => {
      if (nextProject !== previousProject || activeScope === null && previousProject === undefined) {
        load(nextProject)
        return
      }
      syncModules()
    },
    { immediate: true },
  )

  return {
    layout,
    activeProjectId: project,
    isProjectScope,
    setProject,
    reset,
    setVisible,
    toggleVisible,
    setCollapsed,
    toggleCollapsed,
    move,
    reorder,
    save,
  }
}

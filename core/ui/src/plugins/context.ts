import {
  inject,
  provide,
  ref,
  toValue,
  type ComputedRef,
  type InjectionKey,
  type MaybeRefOrGetter,
  type Ref,
} from 'vue'
import type { CoreAppEvent } from '../appServer'
import type { CoreMessage, CoreSessionListItem, ProjectGroup } from '../types'
import type { CoreProject } from '../projects/types'
import type { CoreProjectClient } from '../projects/client'
import type { LamToolsTransport } from '../transport'
import type { PluginRpc } from './types'

export interface PluginSidebarSurface {
  groups: MaybeRefOrGetter<ProjectGroup[]>
  hasProjects?: MaybeRefOrGetter<boolean>
  activeSessionId?: MaybeRefOrGetter<string | undefined>
  primaryActionLabel?: MaybeRefOrGetter<string>
  onPrimaryAction?: () => void | Promise<void>
  newSessionLabel?: MaybeRefOrGetter<string>
  allowProjectNewSession?: MaybeRefOrGetter<boolean>
  allowProjectDelete?: MaybeRefOrGetter<boolean>
  allowSessionDelete?: MaybeRefOrGetter<boolean>
  allowSessionContextMenu?: MaybeRefOrGetter<boolean>
  allowProjectClick?: MaybeRefOrGetter<boolean>
  allowProjectContextMenu?: MaybeRefOrGetter<boolean>
  onSelectSession?: (id: string) => void | Promise<void>
  onSelectProject?: (id: string) => void | Promise<void>
  onNewSession?: (projectGroupId: string) => void | Promise<void>
  onDeleteProject?: (id: string) => void | Promise<void>
  onProjectContextMenu?: (id: string) => void | Promise<void>
  onDeleteSession?: (id: string) => void | Promise<void>
  onRenameSession?: (id: string, title: string) => void | Promise<void>
  onExportSession?: (id: string, format: string) => void | Promise<void>
}

export interface PluginModeSurface {
  composerPlaceholder?: MaybeRefOrGetter<string>
  composerDisabled?: MaybeRefOrGetter<boolean>
  turnOptions?: () => Record<string, unknown>
  sidebar?: PluginSidebarSurface
}

export interface PluginModeRuntime {
  version: Ref<number>
  register(modeId: string, surface: PluginModeSurface): () => void
  get(modeId: string): PluginModeSurface | undefined
}

export interface CorePluginChatContext {
  messages: Readonly<Ref<CoreMessage[]>>
  processExpandedIds: Ref<Set<string>>
  toggleProcess: (id: string) => void
  activeTurnId: ComputedRef<string>
  activeTurnRunning: ComputedRef<boolean>
  checkpointTurnIds: ComputedRef<Set<string>>
  onDecisionSelect: (payload: unknown) => void | Promise<void>
  onForkMessage: (payload: unknown) => void | Promise<void>
  onRollbackMessage: (payload: unknown) => void | Promise<void>
  onEditMessage: (payload: unknown) => void | Promise<void>
}

export interface CorePluginModeContext {
  transport: LamToolsTransport
  requestRpc: PluginRpc
  projectClient: CoreProjectClient
  projects: Ref<CoreProject[]>
  sessions: Ref<CoreSessionListItem[]>
  selectedProjectId: Ref<string | null>
  activeSessionId: Ref<string | null>
  selectedProject: ComputedRef<CoreProject | null>
  activeProjectId: ComputedRef<string | null>
  activeProject: ComputedRef<CoreProject | null>
  currentWorkRoot: () => string
  setSelectedProjectId: (id: string | null) => void
  selectSession: (id: string) => Promise<void>
  refreshSessions: () => Promise<void>
  setRuntimeStatus: (text: string, duration?: number) => void
  availableModels: Ref<Array<{ id: string; display_name?: string; model_id?: string }>>
  composerText: Ref<string>
  ensureRightPanelOpen: () => void
  lastEvent: Ref<CoreAppEvent | null>
  chat: CorePluginChatContext
}

export const CORE_PLUGIN_MODE_CONTEXT: InjectionKey<CorePluginModeContext> = Symbol('core-plugin-mode-context')
export const CORE_PLUGIN_MODE_RUNTIME: InjectionKey<PluginModeRuntime> = Symbol('core-plugin-mode-runtime')

export function createPluginModeRuntime(): PluginModeRuntime {
  const version = ref(0)
  const surfaces = new Map<string, PluginModeSurface>()

  function bump() {
    version.value += 1
  }

  return {
    version,
    register(modeId, surface) {
      surfaces.set(modeId, surface)
      bump()
      return () => {
        if (surfaces.get(modeId) === surface) {
          surfaces.delete(modeId)
          bump()
        }
      }
    },
    get(modeId) {
      // Reading version makes consumers that compute the active surface
      // reactive without exposing the mutable registry itself.
      version.value
      return surfaces.get(modeId)
    },
  }
}

export function provideCorePluginModeContext(context: CorePluginModeContext, runtime: PluginModeRuntime): void {
  provide(CORE_PLUGIN_MODE_CONTEXT, context)
  provide(CORE_PLUGIN_MODE_RUNTIME, runtime)
}

export function useCorePluginModeContext(): CorePluginModeContext {
  const context = inject(CORE_PLUGIN_MODE_CONTEXT)
  if (!context) throw new Error('Core plugin mode context is not available')
  return context
}

export function usePluginModeRuntime(): PluginModeRuntime {
  const runtime = inject(CORE_PLUGIN_MODE_RUNTIME)
  if (!runtime) throw new Error('Plugin mode runtime is not available')
  return runtime
}

export function readPluginSurface<T>(value: MaybeRefOrGetter<T> | undefined, fallback: T): T {
  return value === undefined ? fallback : toValue(value)
}

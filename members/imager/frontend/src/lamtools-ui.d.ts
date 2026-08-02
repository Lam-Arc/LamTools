/**
 * Type declarations for @lamtools/ui components.
 * Bridges the gap for vue-tsc to resolve .vue files
 * from the external Core UI source directory.
 * Aligned with core/ui/src (Phase 5A+ contract).
 */
declare module '@lamtools/ui' {
  import type { DefineComponent } from 'vue'

  // ---------------------------------------------------------------------------
  // Product adapter
  // ---------------------------------------------------------------------------

  /** Opaque feature identifier declared by a product adapter. */
  export type ProductFeatureId = string

  /** Minimal product identity and capability descriptor. */
  export interface ProductAdapter {
    id: string
    displayName: string
    version?: string
    sessionGroups?: CoreSessionGroup[]
    supportedFeatures?: ProductFeatureId[]
    metadata?: Record<string, unknown>
  }

  // ---------------------------------------------------------------------------
  // Session grouping
  // ---------------------------------------------------------------------------

  /** A named group of sessions displayed in the sidebar. */
  export interface CoreSessionGroup {
    id: string
    label: string
    sessionIds?: string[]
    description?: string
    metadata?: Record<string, unknown>
  }

  // ---------------------------------------------------------------------------
  // Runtime steps
  // ---------------------------------------------------------------------------

  export type CoreRuntimeStepStatus =
    | 'pending'
    | 'running'
    | 'completed'
    | 'failed'
    | 'skipped'

  /** A single step in a runtime process. */
  export interface CoreRuntimeStep {
    id: string
    title: string
    status: CoreRuntimeStepStatus
    kind?: string
    detail?: string
    timestamp?: string
    metadata?: Record<string, unknown>
  }

  /** A named group of runtime steps. */
  export interface CoreRuntimeStepGroup {
    id: string
    label: string
    status: CoreRuntimeStepStatus
    steps: CoreRuntimeStep[]
    description?: string
    metadata?: Record<string, unknown>
  }

  // ---------------------------------------------------------------------------
  // Core data types
  // ---------------------------------------------------------------------------

  export interface CoreSessionListItem {
    id: string
    title: string
    createdAt: string
    updatedAt?: string
    groupId?: string
    status?: string
    metadata?: Record<string, unknown>
  }

  export interface CoreMessage {
    id: string
    role: 'user' | 'assistant' | 'system'
    content: string
    timestamp: string
    metadata?: Record<string, unknown>
  }

  export interface CoreRuntimeEvent {
    id: string
    type: string
    timestamp: string
    data?: unknown
  }

  export interface CoreComposerPayload {
    content: string
    attachments?: unknown[]
  }

  export interface CoreMemberDescriptor {
    id: string
    name: string
    version?: string
  }

  // ---------------------------------------------------------------------------
  // API mapper helpers
  // ---------------------------------------------------------------------------

  export interface CoreSessionRawLike {
    id: string
    title: string
    created_at: string | null
    updated_at?: string | null
    status?: string
    metadata?: Record<string, unknown> | null
  }

  export interface CoreMessageRawLike {
    id: string
    role: string
    content: string
    created_at: string | null
    metadata?: Record<string, unknown> | null
  }

  export interface CoreApiMapper<Raw, Core> {
    toCore(raw: Raw): Core
    toRaw(core: Core): Raw
  }

  export interface CreateSessionMapperOptions {
    nullFallback?: boolean
  }

  export interface CreateMessageMapperOptions {
    nullFallback?: boolean
  }

  export function createSessionMapper(
    groupId: string,
    options?: CreateSessionMapperOptions,
  ): CoreApiMapper<CoreSessionRawLike, CoreSessionListItem>

  export function createMessageMapper(
    options?: CreateMessageMapperOptions,
  ): CoreApiMapper<CoreMessageRawLike, CoreMessage>

  export function createLoadingStepGroup(): CoreRuntimeStepGroup[]

  // ---------------------------------------------------------------------------
  // Workbench controller
  // ---------------------------------------------------------------------------

  export interface CoreWorkbenchApi {
    listSessions(): Promise<CoreSessionListItem[]>
    createSession(): Promise<CoreSessionListItem>
    getMessages(sessionId: string): Promise<CoreMessage[]>
    createMessage(sessionId: string, content: string, role?: string): Promise<CoreMessage>
    getEvents(sessionId: string): Promise<CoreRuntimeEvent[]>
    listProviders?(): Promise<unknown[]>
  }

  export interface UseCoreWorkbenchControllerContext {
    sessions: CoreSessionListItem[]
    activeSessionId: string | null
    providerCount: number
  }

  export interface UseCoreWorkbenchControllerOptions {
    api: CoreWorkbenchApi
    onMountedExtra?: (ctx: UseCoreWorkbenchControllerContext) => Promise<void> | void
  }

  export function useCoreWorkbenchController(
    options: UseCoreWorkbenchControllerOptions,
  ): {
    sessions: import('vue').Ref<CoreSessionListItem[]>
    activeSessionId: import('vue').Ref<string | null>
    messages: import('vue').Ref<CoreMessage[]>
    events: import('vue').Ref<CoreRuntimeEvent[]>
    composerText: import('vue').Ref<string>
    loading: import('vue').Ref<boolean>
    providerCount: import('vue').Ref<number>
    stepGroups: import('vue').ComputedRef<CoreRuntimeStepGroup[]>
    selectSession: (id: string) => Promise<void>
    newSession: () => Promise<void>
    sendMessage: () => Promise<void>
    loadInitialData: () => Promise<void>
  }

  // ---------------------------------------------------------------------------
  // Components
  // ---------------------------------------------------------------------------

  export const WorkspaceShell: DefineComponent
  export const SessionSidebar: DefineComponent<{
    sessions: CoreSessionListItem[]
    activeId?: string
    groups?: CoreSessionGroup[]
  }>
  export const ChatThread: DefineComponent<{
    messages: CoreMessage[]
  }>
  export const ComposerBar: DefineComponent<{
    modelValue: string
    placeholder?: string
    disabled?: boolean
  }>
  export const RuntimePanel: DefineComponent<{
    events: CoreRuntimeEvent[]
    stepGroups?: CoreRuntimeStepGroup[]
  }>
  export const SettingsShell: DefineComponent

  // ---------------------------------------------------------------------------
  // Slot protocol
  // ---------------------------------------------------------------------------

  export type SlotId =
    | 'sidebar-header'
    | 'sidebar'
    | 'sidebar-footer'
    | 'sidebar-extra'
    | 'chat-header'
    | 'chat'
    | 'composer-extra'
    | 'drawer-right'
    | 'message-card'
    | 'runtime-step'
    | 'artifact-card'
    | 'inspector'
    | 'composer'
    | 'composer-toolbar'
    | 'settings-section'
    | 'toolbar'
    | 'empty-state'
    | 'step-detail'
    | 'action'
    | 'artifact'

  export type SlotParent =
    | 'WorkspaceShell'
    | 'ChatThread'
    | 'ComposerBar'
    | 'RuntimePanel'
    | 'SettingsShell'
    | 'SessionSidebar'

  export interface SlotDefinition {
    id: SlotId
    parent: SlotParent
    scoped: boolean
    scopeProps: string[]
    permission: string
    fallback: string
  }

  export interface MemberSlotEntry {
    slotId: SlotId
    component?: string
    description: string
  }

  export interface MemberSlotSet {
    memberId: string
    memberName: string
    slots: ReadonlyArray<MemberSlotEntry>
  }

  export const SLOT_REGISTRY: ReadonlyArray<SlotDefinition>
  export function getSlotDefinition(id: SlotId): SlotDefinition | undefined
  export function getSlotsByParent(parent: SlotParent): ReadonlyArray<SlotDefinition>
  export function getAllSlotIds(): ReadonlyArray<SlotId>
  export function validateMemberSlotSet(slotSet: MemberSlotSet): string[]

  // ---------------------------------------------------------------------------
  // Slot resolution (Phase 2)
  // ---------------------------------------------------------------------------

  export interface ResolvedSlot {
    slotId: SlotId
    entry: MemberSlotEntry
    definition: SlotDefinition
  }

  export function resolveMemberSlots(slotSet: MemberSlotSet): ResolvedSlot[]
  export function getSlotEntriesByParent(slotSet: MemberSlotSet, parent: SlotParent): MemberSlotEntry[]
  export function hasSlot(slotSet: MemberSlotSet, slotId: SlotId): boolean

  // ---------------------------------------------------------------------------
  // Member slots composable (Phase 2)
  // ---------------------------------------------------------------------------

  export interface UseMemberSlotsReturn {
    slotSet: import('vue').Ref<MemberSlotSet | null>
    validationErrors: import('vue').Ref<string[]>
    resolvedSlots: import('vue').Ref<ResolvedSlot[]>
    hasSlot: (slotId: SlotId) => boolean
    getSlotsByParent: (parent: SlotParent) => ResolvedSlot[]
    register: (slotSet: MemberSlotSet) => void
    clear: () => void
  }

  export function useMemberSlots(initial?: MemberSlotSet | null): UseMemberSlotsReturn
}

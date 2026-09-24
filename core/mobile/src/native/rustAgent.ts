import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import type {
  StandaloneModel,
  StandaloneProvider,
  StandaloneRuntimeModel,
} from '../standalone/StandaloneConfigStore'

export interface RustAgentImage {
  attachment_id: string
  mime_type: string
  data_base64?: string
}

export type RustAgentMessage =
  | { role: 'system' | 'user'; content: string }
  | { role: 'user_multimodal'; content: string; images: RustAgentImage[] }
  | { role: 'assistant'; content: string; providerState?: unknown }
  | { role: 'assistant_tool_calls'; calls: unknown[]; providerState?: unknown }
  | { role: 'tool'; tool_call_id: string; name?: string; content: string }

export interface RustTurnResult {
  text: string
  reasoning?: string
  runtimeModelId: string
  toolRounds: number
  providerState?: unknown
  sessionApprovedTools?: string[]
  hookAuditEvents?: unknown[]
  hookStatusMessages?: string[]
  runtimeWarnings?: string[]
  runtimeHistory?: RustAgentMessage[]
  compaction?: {
    originalTokens: number
    compactedTokens: number
    summarizedMessages: number
  } | null
  dreaming?: {
    status: string
    summary: string
    memoryUpdated: boolean
  } | null
}

export type RustAgentStreamEvent = {
  turnId: string
  kind: 'text_delta' | 'reasoning_delta' | 'reset' | 'tool_call' | 'tool_result'
  delta?: string
  /** Present for `tool_call` / `tool_result`; carries the tool step detail. */
  data?: Record<string, unknown>
}

export async function listenEmbeddedSundayAgentStream(
  handler: (payload: unknown) => void,
): Promise<() => void> {
  return await listen<RustAgentStreamEvent>('sunday-agent-stream', event => handler(event.payload))
}

export interface RustApprovalRequest {
  requestId: string
  toolCall: { id: string; name: string; arguments?: unknown }
  message: string
}

export interface RustTurnContinuation {
  turnId: string
  modelRecordId: string
  messages: unknown[]
  capabilities: Record<string, unknown>
  options: Record<string, unknown>
  context?: {
    globalInstructions?: string
    projectInstructions?: string
    memory?: string
    modeContext?: string
  }
  hookContext?: Record<string, unknown>
  hookAuditEvents?: unknown[]
  hookStatusMessages?: string[]
  runtimeWarnings?: string[]
  toolRounds: number
  pendingCalls: unknown[]
  nextCallIndex: number
}

export type RustTurnProgress =
  | { status: 'completed'; result: RustTurnResult }
  | { status: 'approval_required'; request: RustApprovalRequest; continuation: RustTurnContinuation }

export interface EmbeddedProjectFile {
  path: string
  content: string
}

export interface EmbeddedProjectFileEntry {
  name: string
  type: 'directory' | 'file'
  size: number
  ext: string
}

export interface EmbeddedProjectDirectoryListing {
  path: string
  entries: EmbeddedProjectFileEntry[]
}

export function hasEmbeddedRustCore(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export interface EmbeddedStudySkill {
  name: string
  description: string
  location: string
}

export async function listEmbeddedStudySkills(): Promise<EmbeddedStudySkill[]> {
  return await invoke<EmbeddedStudySkill[]>('sunday_study_skill_catalog')
}

/** One selectable tool in the mode editor, derived from the real runtimes. */
export interface EmbeddedCatalogTool {
  name: string
  category: string
}

export async function readEmbeddedToolCatalog(): Promise<EmbeddedCatalogTool[]> {
  return await invoke<EmbeddedCatalogTool[]>('sunday_tool_catalog')
}

/** Tool names a bundled plugin grants its own mode; empty when unknown. */
export async function listEmbeddedPluginModeTools(mode: string): Promise<string[]> {
  if (!hasEmbeddedRustCore()) return []
  return await invoke<string[]>('sunday_plugin_mode_tools', { mode })
}

/** One tool the mobile agent can actually call, as reported by the runtime. */
export interface EmbeddedPluginTool {
  name: string
  permission: string
}

/** Tool inventory for one bundled plugin on this device. */
export interface EmbeddedPluginInventory {
  plugin: string
  /** Tools assembled into the agent; the panel count must come from this. */
  assembled: EmbeddedPluginTool[]
  /** What the plugin manifest declares, for an honest comparison. */
  declared_count: number
  /** Why the two differ; empty when everything declared is assembled. */
  note: string
}

export async function listEmbeddedPluginInventory(): Promise<EmbeddedPluginInventory[]> {
  return await invoke<EmbeddedPluginInventory[]>('sunday_plugin_inventory')
}

export async function runEmbeddedSundayTurn(input: {
  turnId: string
  sessionId: string
  projectId: string
  modelRecordId: string
  provider: StandaloneProvider
  model: StandaloneModel
  apiKey: string
  models?: StandaloneRuntimeModel[]
  history: RustAgentMessage[]
  reasoningLevel?: string
  thinkingBudget?: number
  maxOutputTokens?: number
  temperature?: number
  permissionPreset?: 'ask' | 'auto' | 'full_access'
  sessionApprovedTools?: string[]
  /** Name of the active mode, used verbatim when a call is refused. */
  activeMode?: string
  /** Mode tool whitelist; omit or pass an empty list for an unrestricted mode. */
  modeTools?: string[]
  hookConfig?: Record<string, unknown>
  trustedHookHashes?: string[]
  mcpConfig?: Record<string, unknown>
  dreaming?: { enabled?: boolean; min_turns?: number }
  contextCompaction?: { retained_steps?: number }
  subAgent?: { enabled?: boolean; guide?: string }
  study?: { enabled?: boolean }
  disabledSkillNames?: string[]
  disabledPluginNames?: string[]
  imagegenConfig?: Record<string, unknown>
  retryConfig?: Record<string, unknown>
  loadContextConfig?: Record<string, unknown>
  context?: {
    globalInstructions?: string
    projectInstructions?: string
    memory?: string
    modeContext?: string
  }
}): Promise<RustTurnProgress> {
  return await invoke<RustTurnProgress>('sunday_agent_turn', {
    payload: {
      turnId: input.turnId,
      sessionId: input.sessionId,
      projectId: input.projectId,
      modelRecordId: input.modelRecordId,
      provider: rustProvider(input.provider, input.model, input.apiKey),
      models: runtimeModels(input.models || []),
      history: input.history,
      context: input.context || {},
      options: {
        reasoningLevel: input.reasoningLevel || 'off',
        thinkingBudget: input.thinkingBudget,
        maxOutputTokens: input.maxOutputTokens,
        temperature: input.temperature,
        contextWindow: input.model.context_window,
        compactRetainedSteps: Math.min(
          100,
          Math.max(0, Math.floor(Number(input.contextCompaction?.retained_steps) || 0)),
        ),
        permissionPreset: input.permissionPreset || 'ask',
        sessionApprovedTools: input.sessionApprovedTools || [],
        activeMode: input.activeMode || '',
        modeTools: input.modeTools && input.modeTools.length ? input.modeTools : null,
      },
      hookConfig: input.hookConfig || {},
      trustedHookHashes: input.trustedHookHashes || [],
      mcpConfig: input.mcpConfig || {},
      dreaming: {
        enabled: input.dreaming?.enabled === true,
        minTurns: Math.max(1, Math.floor(Number(input.dreaming?.min_turns) || 3)),
      },
      subAgentEnabled: input.subAgent?.enabled !== false,
      subAgentGuide: String(input.subAgent?.guide || ''),
      studyTools: input.study?.enabled === true,
      disabledSkillNames: input.disabledSkillNames || [],
      disabledPluginNames: input.disabledPluginNames || [],
      imagegenConfig: input.imagegenConfig || {},
      retryConfig: input.retryConfig || {},
      loadContextConfig: input.loadContextConfig || {},
    },
  })
}

export async function resumeEmbeddedSundayTurn(input: {
  sessionId: string
  projectId: string
  provider: StandaloneProvider
  model: StandaloneModel
  apiKey: string
  models?: StandaloneRuntimeModel[]
  continuation: RustTurnContinuation
  requestId: string
  decision: 'approve_once' | 'approve_for_session' | 'deny' | 'other_guidance'
  guidance?: string
  hookConfig?: Record<string, unknown>
  trustedHookHashes?: string[]
  mcpConfig?: Record<string, unknown>
  dreaming?: { enabled?: boolean; min_turns?: number }
  subAgent?: { enabled?: boolean; guide?: string }
  study?: { enabled?: boolean }
  disabledSkillNames?: string[]
  disabledPluginNames?: string[]
  imagegenConfig?: Record<string, unknown>
  retryConfig?: Record<string, unknown>
  loadContextConfig?: Record<string, unknown>
}): Promise<RustTurnProgress> {
  return await invoke<RustTurnProgress>('sunday_agent_resume', {
    payload: {
      projectId: input.projectId,
      sessionId: input.sessionId,
      provider: rustProvider(input.provider, input.model, input.apiKey),
      models: runtimeModels(input.models || []),
      continuation: input.continuation,
      response: {
        requestId: input.requestId,
        decision: input.decision,
        guidance: input.guidance || '',
      },
      hookConfig: input.hookConfig || {},
      trustedHookHashes: input.trustedHookHashes || [],
      mcpConfig: input.mcpConfig || {},
      dreaming: {
        enabled: input.dreaming?.enabled === true,
        minTurns: Math.max(1, Math.floor(Number(input.dreaming?.min_turns) || 3)),
      },
      subAgentEnabled: input.subAgent?.enabled !== false,
      subAgentGuide: String(input.subAgent?.guide || ''),
      studyTools: input.study?.enabled === true,
      disabledSkillNames: input.disabledSkillNames || [],
      disabledPluginNames: input.disabledPluginNames || [],
      imagegenConfig: input.imagegenConfig || {},
      retryConfig: input.retryConfig || {},
      loadContextConfig: input.loadContextConfig || {},
    },
  })
}

export async function cancelEmbeddedSundayTurn(turnId: string): Promise<boolean> {
  return await invoke<boolean>('sunday_agent_cancel', {
    payload: { turnId },
  })
}

export interface EmbeddedHookListPayload {
  hooks: Array<{
    id: string
    event: string
    matcher: string
    source: string
    source_name: string
    plugin_name: string
    config_path: string
    handler_type: string
    command: string
    definition_hash: string
    trusted: boolean
    status: string
  }>
  trustable_count: number
  total_count: number
  trusted_count: number
}

export async function listEmbeddedHooks(
  config: Record<string, unknown>,
  trustedHookHashes: string[],
): Promise<EmbeddedHookListPayload> {
  return await invoke<EmbeddedHookListPayload>('sunday_hook_list', {
    config,
    trustedHookHashes,
  })
}

export async function listEmbeddedSubAgents(parentThreadId: string): Promise<Record<string, unknown>> {
  return await invoke<Record<string, unknown>>('sunday_sub_agent_list', { parentThreadId })
}

export async function respondEmbeddedSubAgentApproval(input: {
  parentThreadId: string
  name: string
  requestId: string
  decision: 'approve_once' | 'approve_for_session' | 'deny' | 'other_guidance'
  guidance?: string
}): Promise<Record<string, unknown>> {
  return await invoke<Record<string, unknown>>('sunday_sub_agent_approval', {
    payload: {
      parentThreadId: input.parentThreadId,
      name: input.name,
      response: {
        requestId: input.requestId,
        decision: input.decision,
        guidance: input.guidance || '',
      },
    },
  })
}

function rustProvider(provider: StandaloneProvider, model: StandaloneModel, apiKey: string) {
  return {
    apiType: provider.api_type,
    baseUrl: provider.base_url,
    apiKey,
    apiModelId: model.model_id,
    notes: model.notes || '',
    maxOutputTokens: model.max_output_tokens,
    temperature: model.temperature,
    providerName: provider.name,
    providerExtra: provider.extra || {},
    modelExtra: model.extra || {},
    thinkingSupported: model.thinking_supported === true,
    thinkingBudget: model.thinking_budget,
  }
}

function runtimeModels(models: StandaloneRuntimeModel[]) {
  return models.map(entry => ({
    id: entry.id,
    displayName: entry.displayName,
    provider: rustProvider(entry.provider, entry.model, entry.apiKey),
  }))
}

export async function loadLegacyMobileState<TState>(): Promise<TState | null> {
  if (!hasEmbeddedRustCore()) return null
  return await invoke<TState | null>('load_legacy_mobile_state')
}

export async function listEmbeddedProjectFiles(
  projectId: string,
  path = '',
): Promise<EmbeddedProjectFileEntry[]> {
  return await invoke<EmbeddedProjectFileEntry[]>('project_file_list', { projectId, path })
}

export async function browseEmbeddedProjectDirectory(
  path = '',
): Promise<EmbeddedProjectDirectoryListing> {
  return await invoke<EmbeddedProjectDirectoryListing>('project_directory_browse', { path })
}

export async function readEmbeddedProjectFile(
  projectId: string,
  path: string,
): Promise<EmbeddedProjectFile | null> {
  return await invoke<EmbeddedProjectFile | null>('project_file_read', { projectId, path })
}

export async function writeEmbeddedProjectFile(
  projectId: string,
  path: string,
  content: string,
): Promise<EmbeddedProjectFile> {
  return await invoke<EmbeddedProjectFile>('project_file_write', { projectId, path, content })
}

export interface EmbeddedProjectRawFile {
  path: string
  mimeType: string
  bytes: Uint8Array
}

/** Bytes of one project file; `null` when the path does not exist. */
export async function readEmbeddedProjectFileRaw(
  projectId: string,
  path: string,
): Promise<EmbeddedProjectRawFile | null> {
  const raw = await invoke<{ path: string; mimeType: string; dataBase64: string } | null>(
    'project_file_read_raw',
    { projectId, path },
  )
  if (!raw) return null
  return { path: raw.path, mimeType: raw.mimeType, bytes: decodeBase64(raw.dataBase64) }
}

function decodeBase64(value: string): Uint8Array {
  const binary = atob(value)
  return Uint8Array.from(binary, character => character.charCodeAt(0))
}

export interface EmbeddedProjectAgents {
  content: string
  exists: boolean
}

export async function readEmbeddedProjectAgents(projectId: string): Promise<EmbeddedProjectAgents> {
  return await invoke<EmbeddedProjectAgents>('project_agents_md', { projectId })
}

export async function writeEmbeddedProjectAgents(
  projectId: string,
  content: string,
): Promise<EmbeddedProjectAgents> {
  return await invoke<EmbeddedProjectAgents>('project_agents_md', { projectId, content })
}

export interface EmbeddedStudyCall {
  method: string
  params?: Record<string, unknown>
  /** Host-owned session metadata; never taken from a tool payload. */
  sessionMetadata?: Record<string, unknown>
  sessionTargets?: Record<string, unknown>
  provider?: {
    provider: StandaloneProvider
    model: StandaloneModel
    apiKey: string
  }
  retryConfig?: Record<string, unknown>
}

/**
 * Run one Study operation in the shared Rust runtime.
 *
 * The command reports Study failures as a JSON payload so the shared UI keeps
 * the structured `error`/`reason`/`code` fields it already reads; anything
 * else (a missing database, an unknown operation) surfaces as a plain error.
 */
export async function callEmbeddedStudy<T = Record<string, unknown>>(
  call: EmbeddedStudyCall,
): Promise<T> {
  try {
    return await invoke<T>('sunday_study_rpc', {
      payload: {
        method: call.method,
        params: call.params || {},
        sessionMetadata: call.sessionMetadata,
        sessionTargets: call.sessionTargets,
        provider: call.provider
          ? rustProvider(call.provider.provider, call.provider.model, call.provider.apiKey)
          : undefined,
        retryConfig: call.retryConfig || {},
      },
    })
  } catch (cause) {
    throw studyError(cause, call.method)
  }
}

function studyError(cause: unknown, method: string): Error {
  const raw = cause instanceof Error ? cause.message : String(cause)
  let payload: Record<string, unknown> = {}
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      payload = parsed as Record<string, unknown>
    }
  } catch {
    // A plain transport failure keeps its original message.
  }
  const message = String(payload.error || raw || `${method} failed`)
  return Object.assign(new Error(message), payload, { method })
}

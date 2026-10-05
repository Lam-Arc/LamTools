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
  /** Modified time in whole epoch seconds (files only; 0 for directories). */
  mtime: number
}

export interface EmbeddedProjectDirectoryListing {
  path: string
  entries: EmbeddedProjectFileEntry[]
}

export function hasEmbeddedRustCore(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

/** One skill a host catalog returns: bundled core, plugin or user authored. */
export interface EmbeddedSkillRecord {
  name: string
  description: string
  location: string
}

export type EmbeddedStudySkill = EmbeddedSkillRecord

export async function listEmbeddedStudySkills(): Promise<EmbeddedStudySkill[]> {
  return await invoke<EmbeddedStudySkill[]>('sunday_study_skill_catalog')
}

/**
 * The core skills this host offers, from the runtime that loads them.
 *
 * A skill whose instructions need the desktop (the office CLI, the plugin
 * installer, the Arrange scheduler) is left out here, so the panel cannot offer
 * what `load_skill` would refuse.
 */
export async function listEmbeddedCoreSkills(): Promise<EmbeddedSkillRecord[]> {
  return await invoke<EmbeddedSkillRecord[]>('sunday_core_skill_catalog')
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

/** One artifact the host recorded from an agent write. */
export interface EmbeddedArtifact {
  artifact_id: string
  project_id: string
  name: string
  path: string
  mime_type: string
  source: string
  role: string
  thread_id: string
  turn_id: string
  item_id: string
  tool_name: string
  deleted: boolean
  created_at: string
  updated_at: string
}

export async function listEmbeddedArtifacts(
  projectId: string,
  includeDeleted = false,
): Promise<EmbeddedArtifact[]> {
  if (!hasEmbeddedRustCore()) return []
  const payload = await invoke<{ artifacts: EmbeddedArtifact[] }>('sunday_artifact_list', {
    projectId,
    includeDeleted,
  })
  return payload.artifacts || []
}

export async function setEmbeddedArtifactsDeleted(
  projectId: string,
  artifactIds: string[],
  deleted: boolean,
): Promise<{ deleted?: number; restored?: number }> {
  return await invoke('sunday_artifact_set_deleted', { projectId, artifactIds, deleted })
}

/** Hand one artifact to the system's default app; Android only. */
export async function openEmbeddedArtifact(
  projectId: string,
  artifactId: string,
): Promise<{ status: string; path: string }> {
  return await invoke('sunday_artifact_open', { projectId, artifactId })
}

export async function readEmbeddedArtifactFile(
  projectId: string,
  artifactId: string,
): Promise<{ path: string; mimeType: string; bytes: Uint8Array } | null> {
  const raw = await invoke<{ path: string; mimeType: string; dataBase64: string } | null>(
    'sunday_artifact_file',
    { projectId, artifactId },
  )
  if (!raw) return null
  const binary = atob(raw.dataBase64)
  return {
    path: raw.path,
    mimeType: raw.mimeType,
    bytes: Uint8Array.from(binary, character => character.charCodeAt(0)),
  }
}

/** One checkpoint node, shaped like the desktop's checkpoint payload. */
export interface EmbeddedCheckpoint {
  id: string
  graph_id: string
  root_session_id: string
  session_id: string
  parent_checkpoint_id: string
  edge_kind: string
  turn_id: string
  actor_kind: string
  reason: string
  label: string
  work_root: string
  manifest_hash: string
  status: string
  created_at: string
}

export async function readEmbeddedCheckpointGraph(
  sessionId: string,
): Promise<{ nodes: EmbeddedCheckpoint[]; heads: Record<string, string> }> {
  if (!hasEmbeddedRustCore()) return { nodes: [], heads: {} }
  const payload = await invoke<{ nodes: EmbeddedCheckpoint[]; heads: Record<string, string> }>(
    'sunday_checkpoint_graph',
    { sessionId },
  )
  return { nodes: payload.nodes || [], heads: payload.heads || {} }
}

export async function readEmbeddedCheckpoint(checkpointId: string): Promise<EmbeddedCheckpoint> {
  const payload = await invoke<{ checkpoint: EmbeddedCheckpoint }>('sunday_checkpoint_get', { checkpointId })
  return payload.checkpoint
}

/** One durable goal, shaped like the desktop's `Goal.to_dict()`. */
export interface EmbeddedGoal {
  id: string
  thread_id: string
  objective: string
  completion_criteria: string[]
  status: 'active' | 'blocked' | 'archived'
  status_reason: string
  metadata: Record<string, unknown>
  revision: number
  created_at: string
  updated_at: string
  completed_at: string | null
}

export async function createEmbeddedGoal(input: {
  threadId: string
  objective: string
  completionCriteria?: string[]
  metadata?: Record<string, unknown>
  goalId?: string
}): Promise<{ goal: EmbeddedGoal }> {
  return await invoke('sunday_goal_create', {
    threadId: input.threadId,
    objective: input.objective,
    completionCriteria: input.completionCriteria || [],
    metadata: input.metadata || {},
    goalId: input.goalId || null,
  })
}

export async function readEmbeddedGoal(goalId: string): Promise<{ goal: EmbeddedGoal }> {
  return await invoke('sunday_goal_get', { goalId })
}

export async function listEmbeddedGoals(
  threadId?: string,
  status?: string,
): Promise<{ goals: EmbeddedGoal[] }> {
  return await invoke('sunday_goal_list', { threadId: threadId || null, status: status || null })
}

/** Only the fields present are changed; the host keeps the stored values. */
export async function updateEmbeddedGoal(input: {
  goalId: string
  objective?: string
  completionCriteria?: string[]
  status?: string
  statusReason?: string
  metadata?: Record<string, unknown>
}): Promise<{ goal: EmbeddedGoal }> {
  return await invoke('sunday_goal_update', {
    goalId: input.goalId,
    objective: input.objective ?? null,
    completionCriteria: input.completionCriteria ?? null,
    status: input.status ?? null,
    statusReason: input.statusReason ?? null,
    metadata: input.metadata ?? null,
  })
}

/** One bundled plugin's config schema, embedded and parsed by the host. */
export interface EmbeddedPluginSchema {
  schema: Record<string, unknown>
  path: string
}

export async function readEmbeddedPluginSchemas(): Promise<Record<string, EmbeddedPluginSchema>> {
  if (!hasEmbeddedRustCore()) return {}
  return await invoke<Record<string, EmbeddedPluginSchema>>('sunday_plugin_schemas')
}

/** One skill the user created on this device. */
export interface EmbeddedUserSkill {
  name: string
  description: string
  location: string
}

export async function listEmbeddedUserSkills(): Promise<EmbeddedUserSkill[]> {
  if (!hasEmbeddedRustCore()) return []
  return await invoke<EmbeddedUserSkill[]>('sunday_user_skills')
}

export async function createEmbeddedUserSkill(input: {
  name: string
  description: string
  content: string
}): Promise<EmbeddedUserSkill> {
  return await invoke<EmbeddedUserSkill>('sunday_skill_create', {
    name: input.name,
    description: input.description,
    content: input.content,
  })
}

export async function deleteEmbeddedUserSkill(name: string): Promise<EmbeddedUserSkill> {
  const deleted = await invoke<{ name: string; location: string; deleted: boolean }>(
    'sunday_skill_delete',
    { name },
  )
  return { name: deleted.name, description: '', location: deleted.location }
}

/** One tool the mobile agent can actually call, as reported by the runtime. */
export interface EmbeddedPluginTool {
  name: string
  permission: string
}

/** One mode a bundled plugin contributes, from its manifest. */
export interface EmbeddedPluginMode {
  id: string
  title: string
  icon: string
  tools: string[]
  /** Absent when the manifest makes no claim; an empty list claims none. */
  capabilities?: string[] | null
}

/**
 * One bundled plugin this device offers, read from its own manifest.
 *
 * The runtime filters by the class the manifest declares (`desktop` / `mobile` /
 * `universal`), so a plugin of another platform is not in this list at all.
 */
export interface EmbeddedPluginCatalogEntry {
  name: string
  version: string
  description: string
  platforms: string
  /** Skill roots the manifest declares, as `bundled://` locations. */
  skills: string[]
  skill_names: string[]
  modes: EmbeddedPluginMode[]
  dependencies: string[]
  /** Tools assembled into the agent; the panel count must come from this. */
  tools: EmbeddedPluginTool[]
  /** What the plugin manifest declares, for an honest comparison. */
  declared_tool_count: number
  /** Why the two differ; empty when everything declared is assembled. */
  tools_note: string
}

export async function listEmbeddedPluginCatalog(): Promise<EmbeddedPluginCatalogEntry[]> {
  return await invoke<EmbeddedPluginCatalogEntry[]>('sunday_plugin_catalog')
}

/** One grade the model's adapter profile declares. */
export interface EmbeddedReasoningLevel {
  value: string
  label: string
}

/** The reasoning ladder the host resolved for a model. */
export interface EmbeddedReasoningDeclaration {
  levels: EmbeddedReasoningLevel[]
  off_supported: boolean
}

/**
 * The ladder the model's adapter profile declares, resolved by the host from
 * the profiles compiled into the runtime.
 *
 * This is what lets a model that only carries an `adapter_profile_id` show its
 * own grades instead of the product's fixed ladder. The answer is display data,
 * so a host that cannot supply it (no embedded runtime, a command this build
 * does not register, a configuration the resolver cannot read) degrades to
 * `null` and the caller keeps its own ladder. A model catalog must never fail
 * because a thinking menu could not be filled in.
 */
export async function readEmbeddedModelReasoningDeclaration(input: {
  provider: StandaloneProvider
  model: StandaloneModel
}): Promise<EmbeddedReasoningDeclaration | null> {
  if (!hasEmbeddedRustCore()) return null
  try {
    const result = await invoke<EmbeddedReasoningDeclaration>(
      'sunday_model_reasoning_declaration',
      // The same configuration the turn path sends, so the ladder describes the
      // profile the next request will actually use.
      { config: rustProvider(input.provider, input.model, '') },
    )
    if (!Array.isArray(result?.levels) || typeof result?.off_supported !== 'boolean') return null
    return {
      levels: result.levels
        .filter(level => level && typeof level.value === 'string')
        .map(level => ({ value: level.value, label: String(level.label ?? '') })),
      off_supported: result.off_supported,
    }
  } catch {
    return null
  }
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
  contextCompaction?: { retained_steps?: number }
  subAgent?: { enabled?: boolean; guide?: string }
  study?: { enabled?: boolean }
  disabledSkillNames?: string[]
  disabledPluginNames?: string[]
  imagegenConfig?: Record<string, unknown>
  websearchConfig?: Record<string, unknown>
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
      subAgentEnabled: input.subAgent?.enabled !== false,
      subAgentGuide: String(input.subAgent?.guide || ''),
      studyTools: input.study?.enabled === true,
      disabledSkillNames: input.disabledSkillNames || [],
      disabledPluginNames: input.disabledPluginNames || [],
      imagegenConfig: input.imagegenConfig || {},
      websearchConfig: input.websearchConfig || {},
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
  subAgent?: { enabled?: boolean; guide?: string }
  study?: { enabled?: boolean }
  disabledSkillNames?: string[]
  disabledPluginNames?: string[]
  imagegenConfig?: Record<string, unknown>
  websearchConfig?: Record<string, unknown>
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
      subAgentEnabled: input.subAgent?.enabled !== false,
      subAgentGuide: String(input.subAgent?.guide || ''),
      studyTools: input.study?.enabled === true,
      disabledSkillNames: input.disabledSkillNames || [],
      disabledPluginNames: input.disabledPluginNames || [],
      imagegenConfig: input.imagegenConfig || {},
      websearchConfig: input.websearchConfig || {},
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

export async function deleteEmbeddedProjectFile(
  projectId: string,
  path: string,
): Promise<void> {
  await invoke('project_file_delete', { projectId, path })
}

/** Create one directory (parents included) inside the project tree. */
export async function createEmbeddedProjectDirectory(
  projectId: string,
  path: string,
): Promise<void> {
  await invoke('project_directory_create', { projectId, path })
}

/** Delete one empty directory inside the project tree. */
export async function deleteEmbeddedProjectDirectory(
  projectId: string,
  path: string,
): Promise<void> {
  await invoke('project_directory_delete', { projectId, path })
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

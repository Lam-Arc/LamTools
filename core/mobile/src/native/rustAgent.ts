import { invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'
import type {
  StandaloneModel,
  StandaloneProvider,
  StandaloneRuntimeModel,
} from '../standalone/StandaloneConfigStore'

export type RustAgentMessage =
  | { role: 'system' | 'user'; content: string }
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
  kind: 'text_delta' | 'reasoning_delta' | 'reset'
  delta?: string
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
  hookContext?: Record<string, unknown>
  hookAuditEvents?: unknown[]
  hookStatusMessages?: string[]
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
  path: string
  size: number
}

export function hasEmbeddedRustCore(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
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
  hookConfig?: Record<string, unknown>
  trustedHookHashes?: string[]
  mcpConfig?: Record<string, unknown>
  dreaming?: { enabled?: boolean; min_turns?: number }
  contextCompaction?: { retained_steps?: number }
  subAgent?: { enabled?: boolean; guide?: string }
  study?: { enabled?: boolean }
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

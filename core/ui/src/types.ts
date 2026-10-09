/**
 * Core type definitions for UI components
 * Product-neutral interfaces for workspace shell
 */

// ---------------------------------------------------------------------------
// Product adapter
// ---------------------------------------------------------------------------

export type ProductFeatureId = string;

export interface ProductAdapter {
  id: string;
  displayName: string;
  version?: string;
  sessionGroups?: CoreSessionGroup[];
  supportedFeatures?: ProductFeatureId[];
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Session grouping
// ---------------------------------------------------------------------------

export interface CoreSessionGroup {
  id: string;
  label: string;
  sessionIds?: string[];
  description?: string;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Runtime steps
// ---------------------------------------------------------------------------

export type CoreRuntimeStepStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped';

export interface CoreRuntimeStep {
  id: string;
  title: string;
  status: CoreRuntimeStepStatus;
  kind?: string;
  detail?: string;
  /** Planned files or other outputs associated with this step. */
  deliverables?: string[];
  timestamp?: string;
  /** Optional typed part for rich rendering */
  part?: MessagePart;
  metadata?: Record<string, unknown>;
}

export interface CoreRuntimeStepGroup {
  id: string;
  label: string;
  status: CoreRuntimeStepStatus;
  steps: CoreRuntimeStep[];
  description?: string;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export interface SettingsSectionDef {
  id: string;
  label: string;
  description?: string;
  order?: number;
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// API mapping
// ---------------------------------------------------------------------------

export interface CoreApiMapper<TRaw, TCore> {
  toCore(raw: TRaw): TCore;
  toRaw(core: TCore): TRaw;
}

// ---------------------------------------------------------------------------
// Core data types
// ---------------------------------------------------------------------------

export interface CoreSessionListItem {
  id: string;
  title: string;
  createdAt: string;
  updatedAt?: string;
  groupId?: string;
  status?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Transcript formats exposed by the shared session sidebar.
 *
 * Keep this union in the product-neutral type layer so desktop and mobile
 * shells cannot drift when they wire the same export menu to Core HTTP.
 */
export type CoreSessionExportFormat = 'markdown' | 'txt' | 'jsonl' | 'handoff' | 'zip';

// ---------------------------------------------------------------------------
// Message parts — typed content blocks within a message
// ---------------------------------------------------------------------------

export type MessagePartType =
  | 'text'
  | 'attachment'
  | 'reasoning'
  | 'model_text'
  | 'tool_call'
  | 'tool_result'
  | 'file_diff'
  | 'command_output'
  | 'plan'
  | 'todo_update'
  | 'status'
  | 'error'
  | 'decision'
  | 'sub_line'
  | 'agent_summary'
  | 'compaction'
  /** 运行中插进去的引导指令：属于这一轮的过程，随过程区一起展开/折叠。 */
  | 'guidance';

export type MessagePartStatus = 'pending' | 'running' | 'completed' | 'error';

/** Durable sub-agent lifecycle states.  Message parts keep their compact
 * process status union, while right-rail runs may remain idle/paused/closed
 * after the parent tool call has completed. */
export type CoreSubAgentStatus =
  | MessagePartStatus
  | 'idle'
  | 'paused'
  | 'closed'
  | 'interrupted';

export interface ToolArtifact {
  kind: string;
  uri?: string;
  content?: unknown;
  metadata?: Record<string, unknown>;
  /** Registry identity (optional on legacy streamed tool artifacts). */
  artifact_id?: string;
  role?: ArtifactRole;
  thread_id?: string;
  turn_id?: string;
  item_id?: string;
  missing?: boolean;
  deleted?: boolean;
  path?: string;
  mime_type?: string;
  availability?: string;
}

/** The three artifact roles surfaced by the project成果库. */
export type ArtifactRole = 'input' | 'intermediate' | 'deliverable' | string;

export type ArtifactStatus = 'ready' | 'running' | 'completed' | 'failed' | 'missing' | 'deleted' | string;

/** Compatibility envelope for the artifact registry projection. */
export interface ProjectArtifact {
  artifact_id: string;
  name: string;
  kind: string;
  mime_type?: string;
  path?: string;
  uri?: string;
  role?: ArtifactRole;
  status?: ArtifactStatus;
  source?: string;
  provenance?: unknown;
  /** 后端可用性：available；工作区文件不在了就是 missing。 */
  availability?: string;
  created_at?: string;
  updated_at?: string;
  thread_id?: string;
  turn_id?: string;
  item_id?: string;
  missing?: boolean;
  deleted?: boolean;
  /** 资料库里的收藏标记。 */
  favorite?: boolean;
  /** 资料库里的归档层级（'' = 未归档）。 */
  folder?: string;
  prompt?: string;
  parent_ids?: string[];
  children_ids?: string[];
  [key: string]: unknown;
}

export interface ToolInputPreview {
  field: string;
  content: string;
  chars: number;
  truncated?: boolean;
}

export interface MessagePart {
  id: string;
  partType: MessagePartType;
  status: MessagePartStatus;
  /** Text content — absent for tool_call/tool_result/status parts whose
   *  payload lives in toolArgs/toolResult (audit 21: the type required it
   *  while the protocol omits it). Renderers already guard with `|| ''`. */
  content?: string;
  /** Short label for collapsed display */
  label?: string;
  /** Extra detail shown inline */
  detail?: string;
  /** Tool-specific fields */
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  toolError?: string;
  inputPreview?: ToolInputPreview;
  artifacts?: ToolArtifact[];
  /** Compaction bookkeeping carried by the backend projection
   *  (audit 21: tests exercised these fields the type did not declare). */
  before_tokens?: number;
  after_tokens?: number;
  compaction_status?: string;
  limit_tokens?: number;
  /** reason/phase/message: decision & status parts' payload fields. */
  reason?: string;
  phase?: string;
  message?: string;
  /** Compaction segment bookkeeping carried by the backend projection
   *  (audit 21: tests exercised these fields the type did not declare).
   *  segment = current segment index, segments = total segment count,
   *  compacted_messages/removed_messages = message counts. */
  segment?: number;
  segments?: number;
  compacted_messages?: number;
  removed_messages?: number;
  /** Timing */
  runId?: string;
  startedAt?: string;
  completedAt?: string;
  /** Sub-agent lifecycle metadata.  New snapshots may expose these fields
   * directly; legacy snapshots keep them inside `metadata`. */
  agentType?: 'consider' | 'execute' | string;
  agentName?: string;
  model?: string;
  reasoningLevel?: string;
  summary?: string;
  elapsedMs?: number;
  sourceMessageId?: string;
  sourcePartId?: string;
  subSessionId?: string;
  sourceCallId?: string;
  /** Arbitrary metadata */
  metadata?: Record<string, unknown>;
}

export interface CoreMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  /** Optional typed parts for rich rendering. When present, the renderer
   *  should prefer parts over the flat `content` field. */
  parts?: MessagePart[];
  /** Stable process/answer projection consumed by MessageView. */
  processParts?: MessagePart[];
  answerText?: string;
  answerPart?: MessagePart | null;
  /** Product-specific persisted payload used by the host app to rebuild parts. */
  rawParts?: unknown;
  metadata?: Record<string, unknown>;
}

/** Durable sub-agent record from the supervisor (`sub_agent.list`). The
 * transcript projection cannot know run boundaries of resumed agents — this
 * record is the source of truth for their status and timing. */
export interface CoreSubAgentDurableRecord {
  name: string;
  type?: string;
  model_id?: string;
  reasoning_level?: string;
  status?: string;
  summary?: string;
  started_at?: number | null;
  completed_at?: number | null;
  elapsed_ms?: number | null;
  sub_session_id?: string;
}

export interface CoreSubAgentRun {
  /** Durable child thread identifier. Also used as the stable UI identity. */
  id: string;
  subSessionId: string;
  name: string;
  task: string;
  status: CoreSubAgentStatus;
  modelId: string;
  startedAt: string;
  updatedAt: string;
  /** ChatThread-ready child conversation and runtime timeline. */
  timeline: CoreMessage[];
  sourcePartIds: string[];
  /** Current invocation kind (`consider` or `execute`). */
  type?: 'consider' | 'execute' | string;
  /** Model and reasoning metadata used by the child invocation. */
  model?: string;
  reasoningLevel?: string;
  /** Current projected summary and frozen elapsed duration. */
  summary?: string;
  completedAt?: string;
  elapsedMs?: number;
  /** Source evidence for locating the parent message/part. */
  sourceMessageId?: string;
  sourcePartId?: string;
  sourceMessageIds?: string[];
  /** All observed child session ids when a named agent is resumed. */
  subSessionIds?: string[];
  /** Original backend call id, retained for source-part compatibility. */
  sourceCallId?: string;
}

export interface CoreRuntimeEvent {
  id: string;
  type: string;
  timestamp: string;
  data?: unknown;
}

export type CoreAttachmentStatus = 'uploading' | 'uploaded' | 'failed';

export interface CoreAttachment {
  id: string;
  filename: string;
  label?: string;
  mime_type: string;
  size: number;
  preview_type: 'text' | 'image' | 'pdf' | 'external' | string;
  status?: CoreAttachmentStatus;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface CoreAttachmentInputItem {
  type: 'attachment';
  attachment_id: string;
  filename?: string;
  mime_type?: string;
  preview_type?: string;
  size?: number;
}

export type CoreCommandSource = 'core' | 'member' | 'plugin';

export type CoreCommandAction = 'insert_token' | 'run_action' | 'expand_on_send';

export type CoreCommandKind = 'action' | 'skill';

export interface CoreCommandCatalogItem {
  name: string;
  title: string;
  description: string;
  icon: string;
  source: CoreCommandSource;
  action: CoreCommandAction;
  /** Canonical command category. Optional for compatibility with old catalogs. */
  kind?: CoreCommandKind;
  accepts_args?: boolean;
  disabled?: boolean;
  metadata?: Record<string, unknown>;
}

export interface CoreCommandToken {
  type: 'command_token';
  command: string;
  name: string;
  source_text: string;
  start: number;
  end: number;
}

export interface CoreSkillInputItem {
  type: 'skill';
  name: string;
  source_text?: string;
}

export type CoreInputItem =
  | { type: 'text'; text: string }
  | CoreAttachmentInputItem
  | CoreSkillInputItem;

export interface CoreModelInputCapabilities {
  input_modalities?: string[] | null;
}

export interface CoreComposerPayload {
  content: string;
  attachments?: CoreAttachment[];
}

export interface CoreMemberDescriptor {
  id: string;
  name: string;
  version?: string;
}

// ---------------------------------------------------------------------------
// Theme types (re-exported from helpers/theme for consumer convenience)
// ---------------------------------------------------------------------------

export type { ThemeStop, ThemeArea, ThemeData, ThemePreset, ThemeCSSVars } from './helpers/theme';

// ---------------------------------------------------------------------------
// Member slot declarations
// ---------------------------------------------------------------------------

export type WorkspaceSlotName =
  | 'sidebar-header'
  | 'sidebar-header-action'
  | 'sidebar-body'
  | 'sidebar-footer'
  | 'main-header'
  | 'main-content'
  | 'thread-content'
  | 'composer-preamble'
  | 'composer-status'
  | 'composer-textarea'
  | 'composer-tools'
  | 'composer-action'
  | 'right-panel'
  | 'runtime-overlay'
  | 'modals';

export const WORKSPACE_SLOT_NAMES: readonly WorkspaceSlotName[] = [
  'sidebar-header',
  'sidebar-header-action',
  'sidebar-body',
  'sidebar-footer',
  'main-header',
  'main-content',
  'thread-content',
  'composer-preamble',
  'composer-status',
  'composer-textarea',
  'composer-tools',
  'composer-action',
  'right-panel',
  'runtime-overlay',
  'modals',
] as const;

export interface MemberSlotSet {
  memberId: string;
  declaredSlots: WorkspaceSlotName[];
  fallbacks?: Partial<Record<WorkspaceSlotName, string>>;
}

export interface SlotValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

// ---------------------------------------------------------------------------
// Sidebar data types (used by SessionSidebar)
// ---------------------------------------------------------------------------

export interface SessionItem {
  id: string;
  title: string;
  createdAt?: string;
  updatedAt?: string;
  status?: string;
  /** Optional secondary line rendered by the shared sidebar. */
  meta?: string;
  metadata?: Record<string, unknown>;
}

export interface ProjectGroup {
  id: string;
  name: string;
  workRoot?: string;
  /** Optional host-provided visual metadata for project navigation. */
  iconKey?: string;
  colorKey?: string;
  /** False marks compatibility/read-only groups that cannot be mutated. */
  canManage?: boolean;
  sessions: SessionItem[];
}

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------

export interface CoreSkillItem {
  name: string;
  description: string;
  location: string;
  source: string;
  enabled: boolean;
  deletable: boolean;
}

export interface CoreSkillListPayload {
  skills: CoreSkillItem[];
  total_count: number;
  enabled_count: number;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export interface CoreHookItem {
  id: string;
  event: string;
  matcher: string;
  source: string;
  source_name: string;
  plugin_name: string;
  config_path: string;
  handler_type: string;
  command: string;
  definition_hash: string;
  trusted: boolean;
  status: string;
}

export interface CoreHookListPayload {
  hooks: CoreHookItem[];
  trustable_count: number;
  total_count: number;
  trusted_count: number;
}

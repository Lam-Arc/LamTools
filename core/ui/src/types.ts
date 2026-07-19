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
  | 'compaction';

export type MessagePartStatus = 'pending' | 'running' | 'completed' | 'error';

export interface ToolArtifact {
  kind: string;
  uri?: string;
  content?: unknown;
  metadata?: Record<string, unknown>;
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
  content: string;
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
  /** Timing */
  runId?: string;
  startedAt?: string;
  completedAt?: string;
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
  /** Product-specific persisted payload used by the host app to rebuild parts. */
  rawParts?: unknown;
  metadata?: Record<string, unknown>;
}

export interface CoreSubAgentRun {
  /** Durable child thread identifier. Also used as the stable UI identity. */
  id: string;
  subSessionId: string;
  name: string;
  task: string;
  status: MessagePartStatus;
  modelId: string;
  startedAt: string;
  updatedAt: string;
  /** ChatThread-ready child conversation and runtime timeline. */
  timeline: CoreMessage[];
  sourcePartIds: string[];
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

export type CoreCommandSource = 'core' | 'member';

export type CoreCommandAction = 'insert_token' | 'run_action' | 'expand_on_send';

export interface CoreCommandCatalogItem {
  name: string;
  title: string;
  description: string;
  icon: string;
  source: CoreCommandSource;
  action: CoreCommandAction;
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
  metadata?: Record<string, unknown>;
}

export interface ProjectGroup {
  id: string;
  name: string;
  workRoot?: string;
  sessions: SessionItem[];
}

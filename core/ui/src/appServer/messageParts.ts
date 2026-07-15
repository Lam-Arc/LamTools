import type { MessagePart } from '../types'
import type { CoreAppItem } from './protocol.ts'

export interface CoreAppItemPartOptions {
  status?: MessagePart['status']
  type?: MessagePart['partType']
  label?: string
  metadata?: Record<string, unknown>
}

export function coreAppItemToMessagePart(
  item: CoreAppItem,
  options: CoreAppItemPartOptions = {},
): MessagePart {
  const partType = options.type ?? coreAppItemPartType(String(item.type || ''))
  return {
    id: item.item_id,
    partType,
    status: options.status ?? coreAppItemPartStatus(String(item.status || '')),
    content: String(item.content || item.message || item.summary || item.tool_result || ''),
    label: options.label ?? coreAppItemPartLabel(item, partType),
    detail: String(item.message || item.summary || ''),
    toolName: typeof item.tool_name === 'string' ? item.tool_name : undefined,
    toolArgs: isRecord(item.arguments) ? item.arguments : undefined,
    toolResult: typeof item.tool_result === 'string' ? item.tool_result : undefined,
    toolError: typeof item.error === 'string' ? item.error : undefined,
    inputPreview: coreAppItemInputPreview(item.input_preview || item.inputPreview),
    artifacts: Array.isArray(item.artifacts) ? item.artifacts as MessagePart['artifacts'] : undefined,
    metadata: options.metadata ?? item,
  }
}

export function coreAppItemPartType(type: string): MessagePart['partType'] {
  if (type === 'reasoning') return 'reasoning'
  if (type === 'dynamicToolCall' || type === 'mcpToolCall' || type === 'collabToolCall' || type === 'webSearch') return 'tool_call'
  if (type === 'commandExecution') return 'command_output'
  if (type === 'fileChange') return 'file_diff'
  if (type === 'serverRequest') return 'decision'
  if (type === 'error') return 'error'
  if (type === 'plan') return 'plan'
  if (type === 'agent_summary' || type === 'sub_line') return type
  if (type === 'toolResult') return 'tool_result'
  if (type === 'imageView') return 'tool_result'
  if (type === 'compaction' || type === 'contextCompaction') return 'compaction'
  if (type === 'status') return 'status'
  if (type === 'agentMessage') return 'model_text'
  return 'model_text'
}

export function coreAppItemPartStatus(rawStatus: string): MessagePart['status'] {
  if (rawStatus === 'failed' || rawStatus === 'error') return 'error'
  if (rawStatus === 'pending' || rawStatus === 'waiting') return 'pending'
  if (rawStatus === 'running' || rawStatus === 'interrupting') return 'running'
  return 'completed'
}

export function coreAppItemPartLabel(item: CoreAppItem, partType: MessagePart['partType']): string {
  if (partType === 'compaction' && typeof item.label === 'string' && item.label.trim()) {
    return item.label.trim()
  }
  if (partType === 'model_text') return '正文'
  if (partType === 'tool_call') return String(item.tool_name || item.kind || 'tool')
  if (partType === 'reasoning') return 'thinking'
  if (partType === 'decision') return 'approval'
  if (partType === 'status') return 'status'
  return String(item.tool_name || item.kind || partType)
}

export function coreAppItemInputPreview(value: unknown): MessagePart['inputPreview'] | undefined {
  if (!isRecord(value)) return undefined
  const content = typeof value.content === 'string' ? value.content : ''
  const field = typeof value.field === 'string' ? value.field : ''
  const chars = typeof value.chars === 'number' ? value.chars : content.length
  if (!content || !field) return undefined
  return {
    field,
    content,
    chars,
    truncated: value.truncated === true,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

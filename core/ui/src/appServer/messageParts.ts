import type { MessagePart } from '../types'
import type { CoreAppItem } from './protocol.ts'

export interface AssistantMessagePartsProjection {
  processParts: MessagePart[]
  answerPart: MessagePart | null
  answerText: string
}

/**
 * Normalize only the representation differences that are safe to ignore when
 * deciding whether a model-text item is the flat assistant answer.
 */
export function normalizeAnswerText(value: string): string {
  return String(value || '').replace(/\r\n/g, '\n').trim()
}

/**
 * Split the raw part timeline into one process timeline and one final answer.
 * The UI must not repeat this semantic decision for live/history rendering.
 *
 * Explicit final markers win when a producer provides one. Older snapshots do
 * not have that marker, so the compatibility rule accepts only the last
 * non-empty model_text whose normalized body equals the flat message content;
 * trailing status/attachment bookkeeping does not disqualify it.
 */
export function projectAssistantMessageParts(
  parts: MessagePart[] = [],
  content = '',
  options: { live?: boolean } = {},
): AssistantMessagePartsProjection {
  const source = Array.isArray(parts) ? parts : []
  const answerText = String(content || '')
  let answerIndex = -1

  for (let index = source.length - 1; index >= 0; index -= 1) {
    const part = source[index]
    if (part.partType !== 'model_text' || !normalizeAnswerText(part.content || '')) continue
    if (isExplicitFinalAnswerPart(part)) {
      answerIndex = index
      break
    }
  }

  if (answerIndex < 0) {
    const normalizedContent = normalizeAnswerText(answerText)
    if (normalizedContent) {
      for (let index = source.length - 1; index >= 0; index -= 1) {
        const part = source[index]
        if (part.partType !== 'model_text') continue
        if (normalizeAnswerText(part.content || '') !== normalizedContent) continue
        if (!hasMeaningfulTrailingProcess(source, index)) {
          answerIndex = index
          break
        }
      }
    }
  }

  // During a live stream the flat message content can lag behind the terminal
  // model_text delta. Treat a terminal model_text as the answer until a later
  // process part arrives; the next projection will move it back into the
  // process timeline when that happens.
  if (answerIndex < 0 && options.live) {
    for (let index = source.length - 1; index >= 0; index -= 1) {
      const part = source[index]
      if (part.partType !== 'model_text' || !normalizeAnswerText(part.content || '')) continue
      if (hasMeaningfulTrailingProcess(source, index)) break
      answerIndex = index
      break
    }
  }

  const answerPart = answerIndex >= 0 ? source[answerIndex] : null
  const hasMeaningfulModelText = source.some((part) => (
    part.partType === 'model_text'
    && Boolean(normalizeAnswerText(part.content || ''))
  ))
  return {
    processParts: answerIndex >= 0 ? source.filter((_, index) => index !== answerIndex) : [...source],
    answerPart,
    // During live projection, a model-text part that remains in the process
    // timeline means the flat content field is usually its stale snapshot.
    // Do not render it again in the final-answer slot; a later projection will
    // promote the terminal model-text once the process stream reaches its end.
    answerText: answerPart
      ? (answerText || String(answerPart.content || ''))
      : options.live && hasMeaningfulModelText
        ? ''
        : answerText,
  }
}

function isExplicitFinalAnswerPart(part: MessagePart): boolean {
  const metadata = part.metadata || {}
  return metadata.final === true
    || metadata.is_final === true
    || metadata.final_answer === true
    || metadata.answer === true
    || metadata.role === 'assistant_answer'
    || metadata.kind === 'final_answer'
}

function hasMeaningfulTrailingProcess(parts: MessagePart[], index: number): boolean {
  return parts.slice(index + 1).some((part) => {
    if (part.partType === 'status' || part.partType === 'attachment') return false
    return part.partType !== 'text' || Boolean(normalizeAnswerText(part.content || ''))
  })
}

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

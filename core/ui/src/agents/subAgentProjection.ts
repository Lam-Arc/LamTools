import type {
  CoreMessage,
  CoreSubAgentRun,
  MessagePart,
  MessagePartStatus,
} from '../types'

interface MutableSubAgentRun extends CoreSubAgentRun {
  lastOrder: number
}

export function selectCoreSubAgentRuns(messages: readonly CoreMessage[]): CoreSubAgentRun[] {
  const runs = new Map<string, MutableSubAgentRun>()
  let order = 0

  for (const message of messages) {
    for (const part of message.parts ?? []) {
      if (!isSubAgentPart(part)) continue
      const subSessionId = subAgentSessionId(part)
      if (!subSessionId) continue

      order += 1
      const task = subAgentTask(part)
      const existing = runs.get(subSessionId)
      const run = existing ?? createRun(part, subSessionId, task, message.timestamp, order)
      if (!existing) runs.set(subSessionId, run)

      if (!run.task && task) {
        run.task = task
        run.timeline.unshift(taskMessage(subSessionId, task, part.startedAt || message.timestamp))
      }

      const name = subAgentName(part)
      const modelId = subAgentModelId(part)
      const updatedAt = part.completedAt || part.startedAt || message.timestamp
      run.name = name || run.name
      run.modelId = modelId || run.modelId
      run.status = subAgentProjectedStatus(part)
      run.startedAt = run.startedAt || part.startedAt || message.timestamp
      run.updatedAt = updatedAt || run.updatedAt
      run.lastOrder = order
      if (!run.sourcePartIds.includes(part.id)) run.sourcePartIds.push(part.id)

      const replacementIndex = run.timeline.findIndex(item => item.metadata?.sourcePartId === part.id)
      run.timeline = run.timeline.filter(item => item.metadata?.sourcePartId !== part.id)
      const projectedMessages = subAgentMessages(part, subSessionId, message.timestamp)
      if (replacementIndex >= 0) run.timeline.splice(replacementIndex, 0, ...projectedMessages)
      else run.timeline.push(...projectedMessages)
    }
  }

  return [...runs.values()]
    .sort((a, b) => b.lastOrder - a.lastOrder)
    .map(({ lastOrder: _lastOrder, ...run }) => run)
}

function createRun(
  part: MessagePart,
  subSessionId: string,
  task: string,
  timestamp: string,
  order: number,
): MutableSubAgentRun {
  const startedAt = part.startedAt || timestamp
  return {
    id: subSessionId,
    subSessionId,
    name: subAgentName(part) || 'Sub Agent',
    task,
    status: part.status,
    modelId: subAgentModelId(part),
    startedAt,
    updatedAt: part.completedAt || startedAt,
    timeline: task ? [taskMessage(subSessionId, task, startedAt)] : [],
    sourcePartIds: [],
    lastOrder: order,
  }
}

function taskMessage(subSessionId: string, task: string, timestamp: string): CoreMessage {
  return {
    id: 'sub-agent:' + subSessionId + ':task',
    role: 'user',
    content: task,
    timestamp,
    parts: [],
  }
}

function subAgentMessages(part: MessagePart, subSessionId: string, timestamp: string): CoreMessage[] {
  const parts = subAgentTimelineParts(part)
  const messages: CoreMessage[] = []
  let assistantParts: MessagePart[] = []
  let segment = 0

  const flushAssistant = () => {
    if (assistantParts.length === 0) return
    messages.push(assistantMessage(part, subSessionId, timestamp, assistantParts, segment))
    assistantParts = []
    segment += 1
  }

  for (const timelinePart of parts) {
    if (!isUserTimelinePart(timelinePart)) {
      assistantParts.push(timelinePart)
      continue
    }
    flushAssistant()
    messages.push(userTimelineMessage(part, subSessionId, timestamp, timelinePart, segment))
    segment += 1
  }
  flushAssistant()

  const conclusion = subAgentConclusion(part)
  const lastAssistant = [...messages].reverse().find(message => message.role === 'assistant')
  if (lastAssistant) lastAssistant.content = conclusion
  else if (conclusion) messages.push(assistantMessage(part, subSessionId, timestamp, [], segment, conclusion))
  return messages
}

function subAgentProjectedStatus(part: MessagePart): MessagePartStatus {
  const childParts = subAgentTimelineParts(part).filter(item => !isUserTimelinePart(item))
  const childStatus = childParts.at(-1)?.status
  const statuses = [part.status, childStatus]
  if (statuses.includes('running')) return 'running'
  if (statuses.includes('pending')) return 'pending'
  if (statuses.includes('error')) return 'error'
  return childStatus || part.status
}

function assistantMessage(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  parts: MessagePart[],
  segment: number,
  content = '',
): CoreMessage {
  return timelineMessage(
    part,
    subSessionId,
    part.completedAt || part.startedAt || timestamp,
    'assistant',
    segment,
    content,
    parts,
  )
}

function userTimelineMessage(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  timelinePart: MessagePart,
  segment: number,
): CoreMessage {
  return timelineMessage(
    part,
    subSessionId,
    timelinePart.completedAt || timelinePart.startedAt || timestamp,
    'user',
    segment,
    timelinePart.content || '',
    [],
  )
}

function timelineMessage(
  part: MessagePart,
  subSessionId: string,
  timestamp: string,
  role: CoreMessage['role'],
  segment: number,
  content: string,
  parts: MessagePart[],
): CoreMessage {
  return {
    id: 'sub-agent:' + subSessionId + ':' + part.id + ':' + segment,
    role,
    content,
    timestamp,
    parts,
    metadata: {
      timeline: role === 'assistant' && parts.length > 0 || undefined,
      live: role === 'assistant' && part.status === 'running' || undefined,
      liveStatus: role === 'assistant' ? subAgentStatusLabel(part.status) : undefined,
      subSessionId,
      sourcePartId: part.id,
    },
  }
}

function isUserTimelinePart(part: MessagePart): boolean {
  const metadata = record(part.metadata)
  return metadata.subAgentRole === 'user' || metadata.type === 'userMessage'
}

function isSubAgentPart(part: MessagePart): boolean {
  if (part.partType !== 'agent_summary' && part.partType !== 'sub_line') return false
  const toolName = String(part.toolName || part.label || '').toLowerCase()
  return part.partType === 'sub_line' || !toolName || toolName.includes('sub_agent') || toolName.includes('subagent')
}

function subAgentSessionId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const args = record(part.toolArgs)
  return firstText(
    metadata.sub_session_id,
    metadata.subSessionId,
    nestedMetadata.sub_session_id,
    nestedMetadata.subSessionId,
    args.sub_session_id,
    args.subSessionId,
  )
}

function subAgentName(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const args = record(part.toolArgs)
  return firstText(
    metadata.agent_name,
    metadata.agentName,
    metadata.agent,
    nestedMetadata.agent_name,
    nestedMetadata.agentName,
    nestedMetadata.agent,
    args.agent_name,
    args.agentName,
    args.agent,
    args.name,
  )
}

function subAgentTask(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const args = record(part.toolArgs)
  return firstText(
    args.task,
    args.task_description,
    args.taskDescription,
    args.description,
    metadata.task,
    nestedMetadata.task,
  )
}

function subAgentModelId(part: MessagePart): string {
  const metadata = record(part.metadata)
  const nestedMetadata = record(metadata.metadata)
  const args = record(part.toolArgs)
  return firstText(
    metadata.model_id,
    metadata.modelId,
    metadata.model,
    nestedMetadata.model_id,
    nestedMetadata.modelId,
    nestedMetadata.model,
    args.model_id,
    args.modelId,
  )
}

function subAgentTimelineParts(part: MessagePart): MessagePart[] {
  const metadata = record(part.metadata)
  const rawParts = Array.isArray(metadata.subLineParts)
    ? metadata.subLineParts
    : Array.isArray(metadata.sub_line_parts)
      ? metadata.sub_line_parts
      : []
  const normalized = rawParts
    .map((item, index) => normalizeTimelinePart(part.id, item, index))
    .filter((item): item is MessagePart => Boolean(item))
  if (normalized.length > 0) return normalized

  const fallback: MessagePart[] = []
  const reasoning = Array.isArray(metadata.reasoning_blocks) ? metadata.reasoning_blocks : []
  for (const [index, item] of reasoning.entries()) {
    const content = typeof item === 'string' ? item : firstText(record(item).content)
    if (!content) continue
    fallback.push({
      id: part.id + ':reasoning:' + index,
      partType: 'reasoning',
      status: 'completed',
      content,
    })
  }

  const toolCalls = Array.isArray(metadata.tool_calls) ? metadata.tool_calls : []
  for (const [index, item] of toolCalls.entries()) {
    const tool = record(item)
    const toolName = firstText(tool.name, tool.tool_name, tool.toolName) || 'tool'
    const toolArgs = record(tool.arguments || tool.args || tool.tool_args || tool.toolArgs)
    const output = firstText(tool.output, tool.result, tool.content, tool.summary)
    const error = firstText(tool.error, tool.tool_error, tool.toolError)
    fallback.push({
      id: part.id + ':tool:' + index,
      partType: 'tool_call',
      status: normalizeStatus(tool.status),
      content: output || error,
      label: toolName,
      toolName,
      toolArgs,
      toolResult: output || undefined,
      toolError: error || undefined,
      artifacts: Array.isArray(tool.artifacts) ? tool.artifacts as MessagePart['artifacts'] : undefined,
    })
  }
  return fallback
}

function normalizeTimelinePart(parentId: string, value: unknown, index: number): MessagePart | null {
  const item = record(value)
  if (Object.keys(item).length === 0) return null
  const rawType = firstText(item.partType, item.part_type, item.type) || 'tool_result'
  const partType = normalizePartType(rawType)
  const content = firstTextContent(item.content, item.message, item.summary, item.toolResult, item.tool_result)
  const sourceMetadata = record(item.metadata)
  return {
    id: firstText(item.id, item.item_id) || parentId + ':timeline:' + index,
    partType,
    status: normalizeStatus(item.status),
    content,
    label: firstText(item.label, item.title) || undefined,
    detail: firstText(item.detail, item.message, item.summary) || undefined,
    toolName: firstText(item.toolName, item.tool_name) || undefined,
    toolArgs: recordOrUndefined(item.toolArgs || item.tool_args || item.arguments),
    toolResult: firstText(item.toolResult, item.tool_result) || undefined,
    toolError: firstText(item.toolError, item.tool_error, item.error) || undefined,
    inputPreview: isInputPreview(item.inputPreview || item.input_preview),
    artifacts: Array.isArray(item.artifacts) ? item.artifacts as MessagePart['artifacts'] : undefined,
    metadata: recordOrUndefined({
      ...sourceMetadata,
      ...(rawType === 'userMessage' || sourceMetadata.type === 'userMessage' ? { subAgentRole: 'user' } : {}),
    }),
    startedAt: firstText(item.startedAt, item.started_at) || undefined,
    completedAt: firstText(item.completedAt, item.completed_at) || undefined,
  }
}

function normalizePartType(value: string): MessagePart['partType'] {
  const known: MessagePart['partType'][] = [
    'text', 'attachment', 'reasoning', 'model_text', 'tool_call', 'tool_result',
    'file_diff', 'command_output', 'plan', 'todo_update', 'status', 'error',
    'decision', 'sub_line', 'agent_summary', 'compaction',
  ]
  if (known.includes(value as MessagePart['partType'])) return value as MessagePart['partType']
  if (value === 'agentMessage') return 'model_text'
  if (value === 'dynamicToolCall') return 'tool_call'
  return 'tool_result'
}

function normalizeStatus(value: unknown): MessagePartStatus {
  const status = String(value || '').toLowerCase()
  if (status === 'running' || status === 'interrupting') return 'running'
  if (status === 'pending' || status === 'waiting') return 'pending'
  if (status === 'error' || status === 'failed' || status === 'rejected') return 'error'
  return 'completed'
}

function subAgentConclusion(part: MessagePart): string {
  const metadata = record(part.metadata)
  const finalAnswer = firstText(metadata.final_answer, metadata.finalAnswer)
  if (finalAnswer) return finalAnswer
  const content = firstText(part.content, part.toolResult)
  if (content) return content
  const detail = firstText(part.detail)
  const toolName = firstText(part.toolName, part.label)
  return detail && detail !== toolName ? detail : ''
}

function subAgentStatusLabel(status: MessagePartStatus): string {
  if (status === 'running') return '运行中'
  if (status === 'pending') return '等待中'
  if (status === 'error') return '失败'
  return '已完成'
}

function isInputPreview(value: unknown): MessagePart['inputPreview'] | undefined {
  const preview = record(value)
  const field = firstText(preview.field)
  const content = firstText(preview.content)
  if (!field || !content) return undefined
  return {
    field,
    content,
    chars: Number(preview.chars || content.length),
    truncated: preview.truncated === true,
  }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function recordOrUndefined(value: unknown): Record<string, unknown> | undefined {
  const result = record(value)
  return Object.keys(result).length > 0 ? result : undefined
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (value === null || value === undefined) continue
    const text = String(value).trim()
    if (text) return text
  }
  return ''
}

function firstTextContent(...values: unknown[]): string {
  for (const value of values) {
    if (Array.isArray(value)) {
      const text = value
        .map(item => firstText(record(item).text, record(item).content))
        .filter(Boolean)
        .join('\n')
        .trim()
      if (text) return text
      continue
    }
    const text = firstText(value)
    if (text) return text
  }
  return ''
}

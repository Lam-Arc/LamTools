/* Building the app-server snapshot.
 *
 * The product never invents a conversation: it draws whatever the app server
 * last sent it. So a scene describes a conversation as a list of steps with
 * start times, and this module turns that into the exact snapshot shape the
 * real backend produces (`CoreAppSnapshot`, see `core/ui/src/appServer`).
 *
 * Everything here is a pure function of `t` and `revision`; there is no clock.
 */

import { reveal } from './timeline'

export type StepKind = 'thinking' | 'tool' | 'command' | 'answer'

export interface Step {
  kind: StepKind
  /** seconds: when this step starts appearing */
  at: number
  /** the full text; how much of it exists at time t is computed from `cps` */
  text: string
  /** characters per second the model "types"; default 26 */
  cps?: number
  /** when it flips to completed; defaults to the moment the text finishes */
  doneAt?: number
  /** for kind 'tool' and 'command' */
  tool?: string
  args?: Record<string, unknown>
  /** the one-line title the product shows above a tool call */
  title?: string
}

export interface Turn {
  id: string
  /** seconds: when your message lands in the thread */
  at: number
  prompt: string
  steps: Step[]
}

export interface SnapshotOptions {
  threadId: string
  /** bumped every frame; the product drops a snapshot whose version regressed */
  revision: number
  modelId?: string
  providerId?: string
  contextWindow?: number
  /** a fixed wall clock for created_at, so the transcript never shifts */
  baseTime?: string
  /** keeps item ids stable across frames */
  idPrefix?: string
}

const DEFAULT_CPS = 26
const DEFAULT_MODEL = 'demo-model'
const DEFAULT_BASE_TIME = '2026-10-06T08:00:00.000Z'

const stepCps = (step: Step) => step.cps ?? DEFAULT_CPS
const stepEnd = (step: Step) => step.doneAt ?? step.at + step.text.length / stepCps(step)

/**
 * The snapshot for `turns` at time `t`.
 *
 * Only what has started is present: an item that is still revealing carries
 * exactly the characters that exist so far, which is how streaming is drawn
 * without any wall-clock animation inside the application.
 */
export function snapshotAt(turns: Turn[], t: number, options: SnapshotOptions): unknown {
  const modelId = options.modelId || DEFAULT_MODEL
  const providerId = options.providerId || 'demo-provider'
  const base = options.baseTime || DEFAULT_BASE_TIME
  const prefix = options.idPrefix || options.threadId
  const contextWindow = options.contextWindow ?? 1_048_576

  const projectionTurns: Record<string, unknown> = {}
  const coreTurns: Record<string, unknown> = {}
  const projectionItems: Record<string, unknown> = {}
  const coreItems: Record<string, unknown> = {}
  const projectionOrder: string[] = []
  const coreOrder: string[] = []
  let seq = 0
  let live = false

  for (const turn of turns) {
    if (t < turn.at) continue
    const turnId = `${prefix}:turn:${turn.id}`
    const userId = `${prefix}:user:${turn.id}`
    const itemIds: string[] = []

    seq += 1
    projectionItems[userId] = {
      item_id: userId,
      turn_id: turnId,
      type: 'userMessage',
      status: 'completed',
      seq,
      content: [{ type: 'text', text: turn.prompt }],
    }
    projectionOrder.push(userId)

    for (const [index, step] of turn.steps.entries()) {
      if (t < step.at) continue
      const finished = stepEnd(step) <= t
      if (!finished) live = true
      const itemId = `${prefix}:${turn.id}:${step.kind}:${index}`
      seq += 1
      coreItems[itemId] = {
        item_id: itemId,
        turn_id: turnId,
        kind: stepKindOf(step),
        status: finished ? 'completed' : 'running',
        seq,
        content: reveal(step.text, t, step.at, stepCps(step)),
        payload: payloadFor(step),
      }
      itemIds.push(itemId)
      coreOrder.push(itemId)
    }

    const ends = turn.steps.map(stepEnd)
    const turnEnd = ends.length ? Math.max(...ends) : turn.at
    const turnStatus = t >= turnEnd ? 'completed' : 'running'
    const firstSeq = seq - itemIds.length
    const shared = {
      turn_id: turnId,
      status: turnStatus,
      seq: firstSeq,
      last_seq: seq,
      created_at: base,
      input: [{ type: 'text', text: turn.prompt }],
      context_metrics: {
        estimated_prompt_tokens: 4_812,
        context_window_tokens: contextWindow,
        model_id: modelId,
      },
      runtime_snapshot: {
        model_id: modelId,
        provider_id: providerId,
        active_mode: 'execute',
        reasoning_level: 'high',
        permission_preset: 'ask',
        context_window_tokens: contextWindow,
      },
    }
    projectionTurns[turnId] = { ...shared, items: [userId] }
    coreTurns[turnId] = { ...shared, items: itemIds }
  }

  const status = live ? 'running' : threadStatus(turns, t)
  const itemCount = coreOrder.length + projectionOrder.length

  return {
    thread_id: options.threadId,
    snapshot_seq: options.revision,
    revision: options.revision,
    seen_event_ids: [],
    turns: projectionTurns,
    items: projectionItems,
    item_order: projectionOrder,
    queue: [],
    requests: {},
    artifacts: {},
    status,
    history_page: {
      char_limit: 200_000,
      character_count: 0,
      turn_limit: 20,
      turn_count: Object.keys(coreTurns).length,
      item_count: itemCount,
      total_items: itemCount,
      has_more: false,
      next_before_item_id: null,
      next_before_seq: null,
    },
    core: {
      thread_id: options.threadId,
      snapshot_seq: options.revision,
      revision: options.revision,
      seen_event_ids: [],
      turns: coreTurns,
      items: coreItems,
      item_order: coreOrder,
      requests: {},
      artifacts: {},
      status,
    },
  }
}

/** Nothing has started yet means the thread is idle rather than completed. */
function threadStatus(turns: Turn[], t: number): string {
  const started = turns.filter((turn) => t >= turn.at)
  if (!started.length) return 'idle'
  const last = started[started.length - 1]
  const ends = last.steps.map(stepEnd)
  const finished = ends.length ? Math.max(...ends) : last.at
  return t >= finished ? 'completed' : 'running'
}

function stepKindOf(step: Step): string {
  if (step.kind === 'answer') return 'agentMessage'
  if (step.kind === 'thinking') return 'thinking'
  return 'tool_call'
}

function payloadFor(step: Step): Record<string, unknown> {
  if (step.kind === 'thinking') return { type: 'reasoning' }
  if (step.kind === 'tool') {
    return {
      type: 'dynamicToolCall',
      tool_name: step.tool || 'read_file',
      arguments: step.args || {},
      ...(step.title ? { metadata: { title: step.title } } : {}),
    }
  }
  if (step.kind === 'command') {
    return {
      type: 'commandExecution',
      tool_name: step.tool || 'run_command',
      arguments: step.args || {},
      ...(step.title ? { metadata: { title: step.title } } : {}),
    }
  }
  return { type: 'agentMessage', metadata: { final: true } }
}

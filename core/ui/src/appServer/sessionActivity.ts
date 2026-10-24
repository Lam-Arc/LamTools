import { isCoreActiveTurnStatus } from '@/appServer/workbenchActions.ts'
import { selectLatestTurnStatus } from '@/appServer/selectors.ts'
import { selectLatestActiveTurnId } from '@/appServer/workbenchProjection.ts'
import { normalizeSubAgentStatus, reconcileCoreSubAgentRecords, reconcileCoreSubAgentRun, selectCoreSubAgentRuns } from '@/agents/subAgentProjection.ts'
import type { CoreAppSnapshot, CoreAppThreadStatus } from '@/appServer/protocol.ts'
import type { CoreMessage, CoreSubAgentStatus, CoreSubAgentDurableRecord } from '@/types.ts'

/**
 * Session-level activity, derived once and consumed by every surface that needs
 * to know whether the session is busy (session-list dot, composer send/stop,
 * thread "follow latest" spinner, streaming cursor). Two busy states are
 * deliberately distinct:
 *
 *  · `running` — the main agent is working on the active turn.
 *  · `awaiting_sub_agents` — the main turn has ended, but sub-agents delegated
 *    from it are still running. This is quieter than `running`: nothing is
 *    streaming into the main transcript, and the composer must stay usable
 *    (the user can open a new turn while the delegated work finishes). Before
 *    this split existed, the session kept reading as the generic `running`
 *    state, so the composer queued onto a turn that no longer existed and the
 *    request was rejected.
 */
export type CoreSessionPhase = 'idle' | 'running' | 'awaiting_sub_agents'

export interface CoreSessionActivity {
  /** Projected thread status, kept verbatim for callers that render it. */
  status: CoreAppThreadStatus
  /** The main agent is working on the active turn. */
  mainRunning: boolean
  /** The main turn is over but delegated sub-agents are still running/pending. */
  awaitingSubAgents: boolean
  /** Sub-agents still running/pending (0 unless `awaitingSubAgents`). */
  pendingSubAgentCount: number
  /** Names of the running members, when the backend reported them. */
  pendingSubAgentNames: string[]
  /** The runtime has published its members-running fact for this session. */
  memberWaitKnown: boolean
  /** That fact currently says the harness is waiting on members. */
  memberWaitWaiting: boolean
  /**
   * Members the runtime reports as still running (only populated while
   * `memberWaitWaiting`). A member absent from this list is settled: the runtime
   * rebuilds the list each wait round and clears it when the drain finishes, so
   * it is a per-member settle signal that does not require the pane to be open.
   */
  runningMemberNames: string[]
  /**
   * Each member's own lifecycle status, as the runtime publishes it (name in
   * lower case → normalized status). Published on every transition *while the
   * turn is still open*, so a status label can be accurate mid-turn instead of
   * waiting for the turn to end or for the supervisor-record poll.
   */
  memberStatuses: Record<string, CoreSubAgentStatus>
  memberStatusRecords: Record<string, CoreSubAgentDurableRecord>
  /**
   * Members currently working (running/pending). When the main turn is not the
   * active target, Stop addresses these members instead of the parent turn: a
   * parent turn that already ended must not be restarted to control them.
   */
  interruptibleSubAgentNames: string[]
  /**
   * Members whose last recorded state is `interrupted`. Resume continues them
   * from their committed child history; it never restarts the parent turn.
   */
  resumableSubAgentNames: string[]
  /** The single display phase derived from the two flags above. */
  phase: CoreSessionPhase
}

export interface SelectCoreSessionActivityOptions {
  /** Projected thread messages. Only read when the main turn is not running and
   *  the backend did not report the member-wait signal, so the per-frame
   *  streaming path pays nothing for the sub-agent scan. */
  messages?: readonly CoreMessage[]
  /** Complete polled registry for this thread; undefined until loaded. */
  memberRecords?: Record<string, CoreSubAgentDurableRecord>
}

/**
 * The member-wait fact the runtime projects for a turn held open for background
 * members. `known` false means this snapshot predates the signal (or has no
 * turn yet), in which case the transcript is consulted as a fallback.
 */
interface MemberWaitSignal {
  known: boolean
  waiting: boolean
  names: string[]
  /** 每个成员自己发布的实时状态（同一遍扫描顺手收下，不额外扫一遍条目）。 */
  statuses: Record<string, CoreSubAgentStatus>
  records: Record<string, CoreSubAgentDurableRecord>
}

// `createWorkbench` asks for the same snapshot-only member signal both before
// projection (to decide whether the last main message is live) and after
// projection (to derive the session activity shown by the UI). On a snapshot
// without the lifted turn flag, each lookup would scan every normalized item;
// share that immutable result for both consumers of this exact snapshot.
const memberWaitSignalsBySnapshot = new WeakMap<CoreAppSnapshot, MemberWaitSignal>()

/**
 * The one place this state is derived. The authoritative signal is the turn's
 * `waiting_on_members` / `running_members` (lifted onto the snapshot turn) with
 * the live `subAgents` status item as the fallback projection; only when the
 * snapshot carries neither does the selector fall back to inferring from the
 * delegated runs in the transcript.
 */
export function selectCoreSessionActivity(
  snapshot: CoreAppSnapshot | null | undefined,
  options: SelectCoreSessionActivityOptions = {},
): CoreSessionActivity {
  const status = snapshot ? selectLatestTurnStatus(snapshot) : 'idle'
  const statusActive = isCoreActiveTurnStatus(status)
  const signal = snapshot ? readMemberWaitSignal(snapshot) : EMPTY_MEMBER_WAIT  // A turn held open for background members stays non-terminal while the main
  // agent is no longer working, so the member-wait flag, not the turn status,
  // decides "the main agent stopped". Only then can the two states be told
  // apart without guessing.
  const mainRunning = statusActive && !signal.waiting
  const records = options.memberRecords === undefined ? signal.records
    : reconcileCoreSubAgentRecords(signal.records, options.memberRecords)
  const registryNames = Object.entries(records)
    .filter(([, record]) => record.status === 'running' || record.status === 'pending')
    .map(([name]) => name)
  // Child-directed control reads the same reconciled records as every status
  // label, so Stop/Resume can never disagree with the pane about a member.
  const interruptedNames = Object.entries(records)
    .filter(([, record]) => normalizeSubAgentStatus(record.status) === 'interrupted')
    .map(([name]) => name)
  const inferredCount = mainRunning || signal.known || options.memberRecords !== undefined
    ? 0 : countOutstandingSubAgents(options.messages, signal.records)
  const awaitingSubAgents = !mainRunning && (options.memberRecords !== undefined
    ? registryNames.length > 0 : signal.waiting || inferredCount > 0)
  const pendingSubAgentNames = awaitingSubAgents
    ? options.memberRecords !== undefined ? registryNames : signal.names : []
  const pendingSubAgentCount = awaitingSubAgents
    ? options.memberRecords !== undefined ? registryNames.length
      : signal.waiting ? Math.max(signal.names.length, 1) : inferredCount : 0
  return {
    status,
    mainRunning,
    awaitingSubAgents,
    pendingSubAgentCount,
    pendingSubAgentNames,
    memberWaitKnown: signal.known,
    memberWaitWaiting: signal.waiting,
    runningMemberNames: options.memberRecords !== undefined ? registryNames : signal.waiting ? signal.names : [],
    memberStatuses: options.memberRecords === undefined ? signal.statuses
      : Object.fromEntries(Object.entries(records).map(([name, record]) => [name, normalizeSubAgentStatus(record.status)])),
    memberStatusRecords: records,
    interruptibleSubAgentNames: registryNames,
    resumableSubAgentNames: interruptedNames,
    phase: mainRunning ? 'running' : awaitingSubAgents ? 'awaiting_sub_agents' : 'idle',
  }
}

const EMPTY_MEMBER_WAIT: MemberWaitSignal = { known: false, waiting: false, names: [], statuses: {}, records: {} }

/** The turn-level flag first (authoritative), the live item second. */
function readMemberWaitSignal(snapshot: CoreAppSnapshot): MemberWaitSignal {
  const cached = memberWaitSignalsBySnapshot.get(snapshot)
  if (cached) return cached

  const turnId = selectMemberSignalTurnId(snapshot)
  let known = false
  let waiting = false
  const names: string[] = []
  for (const turns of [snapshot.turns, snapshot.core?.turns]) {
    const record = turnId ? turns?.[turnId] as Record<string, unknown> | undefined : undefined
    if (!record || !Object.prototype.hasOwnProperty.call(record, 'waiting_on_members')) continue
    known = true
    waiting = record.waiting_on_members === true
    if (waiting && Array.isArray(record.running_members)) pushMemberNames(names, record.running_members)
    break
  }
  if (known) {
    const signal = { known, waiting, names: [...new Set(names)], ...readMemberStatuses(snapshot, turnId) }
    memberWaitSignalsBySnapshot.set(snapshot, signal)
    return signal
  }
  const itemTurnId = turnId || latestSubAgentItemTurnId(snapshot)
  for (const items of [snapshot.core?.items, snapshot.items]) {
    for (const item of Object.values(items ?? {})) {
      const payload = isRecord((item as { payload?: unknown })?.payload) ? (item as { payload: Record<string, unknown> }).payload : null
      if (!payload || payload.type !== 'subAgents') continue
      const rowTurnId = String((item as { turn_id?: unknown })?.turn_id || '')
      if (itemTurnId && rowTurnId !== itemTurnId) continue
      known = true
      if (payload.waiting_on_members !== true) continue
      waiting = true
      if (Array.isArray(payload.members)) {
        for (const member of payload.members) {
          const name = isRecord(member) ? String(member.name || '').trim() : ''
          if (name) names.push(name)
        }
      }
    }
  }
  const signal = {
    known,
    waiting,
    names: [...new Set(names)],
    ...readMemberStatuses(snapshot, itemTurnId),
  }
  memberWaitSignalsBySnapshot.set(snapshot, signal)
  return signal
}

/**
 * 成员自己的实时状态：后端在成员每一次生命周期变化时发布一行
 * （`payload.type === "subAgentStatus"`，条目 id 每个成员稳定），所以不必等到回合终结
 * 或监督者记录的下一次轮询。回合终态之后 `running_members` 事实已经是权威口径，这里
 * 照旧返回最新发布的状态行（它描述的就是成员自己的状态）。
 *
 * 与等待信号一起挂在同一份按快照缓存的结果上：一遍条目扫描同时收下两者，不给每帧
 * 再加一次全量扫描。
 */
function readMemberStatuses(
  snapshot: CoreAppSnapshot,
  turnId: string,
): Pick<MemberWaitSignal, 'statuses' | 'records'> {
  const records: Record<string, CoreSubAgentDurableRecord> = {}
  const statuses: Record<string, CoreSubAgentStatus> = {}
  // 只扫这一轮的条目（成员状态行属于当前回合），不为此再全量扫一遍线程条目。
  const turnItemIds: string[] = []
  for (const turns of [snapshot.turns, snapshot.core?.turns]) {
    const record = turnId ? turns?.[turnId] as { items?: unknown } | undefined : undefined
    if (Array.isArray(record?.items)) {
      for (const itemId of record.items) {
        if (typeof itemId === 'string' && itemId) turnItemIds.push(itemId)
      }
    }
  }
  if (turnItemIds.length === 0) return { statuses, records }
  for (const itemId of turnItemIds) {
    for (const items of [snapshot.items, snapshot.core?.items]) {
      recordMemberStatus(items?.[itemId], statuses, records)
    }
  }
  return { statuses, records }
}

/** 一行 `subAgentStatus` → 该成员自己的状态（名字小写做键，后出现的覆盖先出现的）。 */
function recordMemberStatus(item: unknown, statuses: Record<string, CoreSubAgentStatus>, records: Record<string, CoreSubAgentDurableRecord>): void {
  const payload = isRecord((item as { payload?: unknown })?.payload)
    ? (item as { payload: Record<string, unknown> }).payload
    : null
  if (!payload || payload.type !== 'subAgentStatus') return
  const record = isRecord(payload.sub_agent) ? payload.sub_agent : null
  const name = String(record?.name || '').trim().toLowerCase()
  if (!name) return
  records[name] = record as unknown as CoreSubAgentDurableRecord
  statuses[name] = normalizeSubAgentStatus(record?.status)
}

/**
 * Member-wait is a property of the current/latest turn, not a session-wide
 * latch. Prefer the active turn; otherwise retain the latest completed turn's
 * signal so genuine background work remains visible after the main reply ends.
 */
function selectMemberSignalTurnId(snapshot: CoreAppSnapshot): string {
  const activeTurnId = selectLatestActiveTurnId(snapshot)
  if (activeTurnId) return activeTurnId

  let latestId = ''
  let latestSeq = Number.NEGATIVE_INFINITY
  let latestCreatedAt = Number.NEGATIVE_INFINITY
  let order = 0
  let latestOrder = -1
  for (const turns of [snapshot.turns, snapshot.core?.turns]) {
    for (const [id, turn] of Object.entries(turns ?? {})) {
      const seq = Math.max(numberValue(turn.last_seq), numberValue(turn.seq))
      const createdAt = Date.parse(String(turn.created_at || ''))
      const time = Number.isFinite(createdAt) ? createdAt : Number.NEGATIVE_INFINITY
      if (
        seq > latestSeq
        || (seq === latestSeq && time > latestCreatedAt)
        || (seq === latestSeq && time === latestCreatedAt && order > latestOrder)
      ) {
        latestId = String(turn.turn_id || id)
        latestSeq = seq
        latestCreatedAt = time
        latestOrder = order
      }
      order += 1
    }
  }
  return latestId
}

/** When a snapshot has no turn records yet, use the newest projected member row. */
function latestSubAgentItemTurnId(snapshot: CoreAppSnapshot): string {
  const candidates: Array<{ id: string; turnId: string; order: number; seq: number }> = []
  let order = 0
  for (const [items, itemOrder] of [
    [snapshot.items, snapshot.item_order],
    [snapshot.core?.items, snapshot.core?.item_order],
  ] as const) {
    const orderById = new Map((itemOrder ?? []).map((id, index) => [id, index]))
    for (const [id, item] of Object.entries(items ?? {})) {
      const payload = isRecord((item as { payload?: unknown })?.payload)
        ? (item as { payload: Record<string, unknown> }).payload
        : null
      if (!payload || payload.type !== 'subAgents') continue
      const turnId = String((item as { turn_id?: unknown })?.turn_id || '')
      if (!turnId) continue
      candidates.push({
        id,
        turnId,
        order: orderById.get(id) ?? order,
        seq: numberValue((item as { last_seq?: unknown; seq?: unknown }).last_seq)
          || numberValue((item as { seq?: unknown }).seq),
      })
      order += 1
    }
  }
  candidates.sort((left, right) => right.seq - left.seq || right.order - left.order || right.id.localeCompare(left.id))
  return candidates[0]?.turnId || ''
}

function numberValue(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function pushMemberNames(target: string[], values: readonly unknown[]): void {
  for (const value of values) {
    const name = String(value || '').trim()
    if (name) target.push(name)
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

/**
 * Outstanding delegated work, read from the transcript the message projection
 * already derives. Fallback only: consulted when the snapshot carries no
 * member-wait signal at all, and never while the main turn is running.
 */
export function countOutstandingSubAgents(messages?: readonly CoreMessage[], records: Record<string, CoreSubAgentDurableRecord> = {}): number {
  if (!messages?.length) return 0
  return selectCoreSubAgentRuns(messages)
    .map(run => reconcileCoreSubAgentRun(run, records[run.name.trim().toLowerCase()]))
    .filter(run => run.status === 'running' || run.status === 'pending')
    .length
}

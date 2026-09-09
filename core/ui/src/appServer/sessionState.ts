import type { CoreAppEvent, CoreAppSnapshot, CoreAppThreadStatus } from './protocol.ts'

export interface CoreSessionState {
  threadId: string
  snapshot: CoreAppSnapshot
  revision: number
  snapshotSeq: number
  status: CoreAppThreadStatus
}

function numberValue(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0
}

export function snapshotRevision(snapshot: CoreAppSnapshot | null | undefined): number {
  if (!snapshot) return 0
  return Math.max(
    numberValue(snapshot.revision),
    numberValue(snapshot.core?.revision),
  )
}

export function snapshotSequence(snapshot: CoreAppSnapshot | null | undefined): number {
  if (!snapshot) return 0
  return Math.max(
    numberValue(snapshot.snapshot_seq),
    numberValue(snapshot.core?.snapshot_seq),
  )
}

export function snapshotStatus(snapshot: CoreAppSnapshot): CoreAppThreadStatus {
  const coreStatus = snapshot.core?.status
  const value = coreStatus && coreStatus !== 'idle' ? coreStatus : snapshot.status || coreStatus
  if (value === 'running' || value === 'waiting' || value === 'completed'
    || value === 'failed' || value === 'cancelled') return value
  return 'idle'
}

function isTerminalStatus(value: unknown): boolean {
  return value === 'completed' || value === 'failed' || value === 'cancelled'
}

function isActiveStatus(value: unknown): boolean {
  return value === 'running' || value === 'waiting' || value === 'interrupting'
}

export function compareSnapshotVersion(
  left: Pick<CoreSessionState, 'revision' | 'snapshotSeq'>,
  right: Pick<CoreSessionState, 'revision' | 'snapshotSeq'>,
): number {
  if (left.revision !== right.revision) return left.revision - right.revision
  return left.snapshotSeq - right.snapshotSeq
}

export interface SessionStateEventResult {
  applied: boolean
  state: CoreSessionState | null
}

/**
 * The session state store is deliberately independent from transport state.
 * WebSocket reconnects may replace the transport, but they must never replace
 * a newer session snapshot with an older cache or delayed event.
 */
export class CoreSessionStateStore {
  private readonly states = new Map<string, CoreSessionState>()

  get(threadId: string): CoreSessionState | null {
    return this.states.get(threadId) || null
  }

  getStatus(threadId: string): CoreAppThreadStatus | undefined {
    return this.states.get(threadId)?.status
  }

  clear(threadId?: string): void {
    if (threadId) this.states.delete(threadId)
    else this.states.clear()
  }

  applySnapshot(snapshot: CoreAppSnapshot): boolean {
    const threadId = String(snapshot.thread_id || '')
    if (!threadId) return false
    const incoming = this.fromSnapshot(snapshot)
    const current = this.states.get(threadId)
    if (current && compareSnapshotVersion(incoming, current) < 0) return false
    this.states.set(threadId, incoming)
    return true
  }

  applyEvent(
    event: CoreAppEvent,
    reducer: (snapshot: CoreAppSnapshot, event: CoreAppEvent) => CoreAppSnapshot,
    options: { allowSequenceRegression?: boolean } = {},
  ): SessionStateEventResult {
    const current = this.states.get(event.thread_id)
    if (!current) return { applied: false, state: null }

    const payload = event.payload || {}
    const eventRevision = Math.max(
      numberValue(event.revision),
      numberValue(payload.revision),
    )
    const eventSeq = numberValue(event.seq)
    const eventKind = typeof payload.kind === 'string' ? payload.kind : ''
    const eventStatus = typeof payload.status === 'string'
      ? payload.status
      : isRecord(payload.payload) && typeof payload.payload.status === 'string'
        ? payload.payload.status
        : ''
    // A terminal run-item is the authoritative close of its turn. Older
    // clients can receive it with a stale projection revision when live event
    // persistence raced; dropping it would leave the UI stuck in retry/running
    // forever even though the durable snapshot is completed.
    const terminalEvent = eventKind === 'status' && isTerminalStatus(eventStatus)
    if (!terminalEvent && eventRevision > 0 && eventRevision < current.revision) {
      return { applied: false, state: current }
    }
    if (!terminalEvent && !options.allowSequenceRegression
      && eventRevision === current.revision && eventSeq > 0 && eventSeq < current.snapshotSeq) {
      return { applied: false, state: current }
    }
    if (!terminalEvent && !options.allowSequenceRegression && eventRevision === 0 && eventSeq > 0 && eventSeq < current.snapshotSeq) {
      return { applied: false, state: current }
    }

    const turnId = String(event.turn_id || payload.turn_id || '')
    const currentTurn = turnId
      ? current.snapshot.core?.turns?.[turnId] || current.snapshot.turns?.[turnId]
      : undefined
    const terminalTurn = currentTurn
      ? isTerminalStatus(currentTurn.status)
      : !turnId && isTerminalStatus(current.status)
    if (eventKind === 'status' && isActiveStatus(eventStatus) && terminalTurn) {
      return { applied: false, state: current }
    }

    const reduced = reducer(current.snapshot, event)
    const snapshot: CoreAppSnapshot = {
      ...reduced,
      revision: Math.max(snapshotRevision(reduced), current.revision, eventRevision),
      snapshot_seq: Math.max(snapshotSequence(reduced), current.snapshotSeq, eventSeq),
    }
    const next = this.fromSnapshot(snapshot)
    this.states.set(event.thread_id, next)
    return { applied: true, state: next }
  }

  private fromSnapshot(snapshot: CoreAppSnapshot): CoreSessionState {
    const revision = snapshotRevision(snapshot)
    const snapshotSeq = snapshotSequence(snapshot)
    const normalized: CoreAppSnapshot = {
      ...snapshot,
      revision,
      snapshot_seq: snapshotSeq,
      ...(snapshot.core ? {
        core: {
          ...snapshot.core,
          revision: Math.max(revision, numberValue(snapshot.core.revision)),
          snapshot_seq: Math.max(snapshotSeq, numberValue(snapshot.core.snapshot_seq)),
        },
      } : {}),
    }
    return {
      threadId: String(snapshot.thread_id),
      snapshot: normalized,
      revision,
      snapshotSeq,
      status: snapshotStatus(normalized),
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

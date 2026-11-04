// @vitest-environment node
/**
 * The interface side of the Android host's event contract.
 *
 * The Rust side of this same file is asserted in
 * `core/android-host/src-tauri/src/projection/contract.rs`. Both read
 * `core/android-host/contract/android-host.v1.json`, so "the projection is correct"
 * and "the screen shows it" cannot drift apart: a field the host stops sending makes
 * the Rust test red, and a shape the interface stops rendering makes this one red.
 *
 * The events fed in here are the contract's *expected* output, materialised. They are
 * not hand-built to suit the UI — that is what made an earlier approval test pass while
 * the real projection produced a card nobody could answer.
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import type { CoreAppEvent, CoreAppSnapshot } from '@/appServer/protocol.ts'
import { applyCoreAppEvent } from '@/appServer/store.ts'
import { selectCoreWorkbenchMessages } from '@/appServer/workbenchProjection.ts'
import { coreDecisionSelectionPlan } from '@/appServer/workbenchActions.ts'

const THREAD = 'th'
/** Fixed instants: the contract only requires "a real timestamp", not a specific one. */
const ISO = '2026-11-04T04:46:36.000Z'
const EPOCH_MS = 1762145196000

const spec = JSON.parse(
  readFileSync(
    new URL('../../android-host/contract/android-host.v1.json', import.meta.url),
    'utf8',
  ),
) as { scenarios: Array<{ name: string; expect: unknown[] }> }

function scenario(name: string): Array<{ name: string; expect: unknown[] }> {
  const found = spec.scenarios.filter((entry) => entry.name === name)
  if (found.length !== 1) throw new Error(`expected one scenario named "${name}", found ${found.length}`)
  return found
}

/**
 * Turns a contract expectation into a concrete event.
 *
 * `$any` / `$iso` / `$epoch_ms` are promises about *kind*, not about value, and
 * `$absent` marks a key the host must not send at all.
 */
function materialize(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(materialize)
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
      if (raw === '$absent') continue
      out[key] = materialize(raw)
    }
    return out
  }
  if (value === '$iso') return ISO
  if (value === '$epoch_ms') return EPOCH_MS
  if (value === '$any') return 'any'
  return value
}

/** The events the host is contracted to emit for a scenario. */
function eventsOf(name: string): CoreAppEvent[] {
  const [entry] = scenario(name)
  return entry.expect.map((expected, index) => {
    const item = materialize(expected) as Record<string, unknown>
    const inner = (item.payload ?? {}) as Record<string, unknown>
    // The contract states identity once, in the payload, and requires the envelope to
    // repeat it. Rebuilding the envelope here is that rule applied, not a substitute
    // for it: the Rust side asserts both agree for every projected item.
    const eventId = String(item.event_id ?? inner.event_id ?? `ev-${index}`)
    return {
      method: 'core/runItem',
      thread_id: THREAD,
      created_at: ISO,
      ...item,
      event_id: eventId,
      payload: { ...inner, event_id: eventId, created_at_ms: inner.created_at_ms ?? EPOCH_MS },
    } as unknown as CoreAppEvent
  })
}

function emptySnapshot(): CoreAppSnapshot {
  return {
    thread_id: THREAD,
    snapshot_seq: 0,
    revision: 0,
    status: 'running',
    turns: {},
    items: {},
    item_order: [],
    requests: {},
    artifacts: {},
    seen_event_ids: [],
  } as CoreAppSnapshot
}

function applyAll(events: CoreAppEvent[], from?: CoreAppSnapshot): CoreAppSnapshot {
  let snapshot = from ?? emptySnapshot()
  for (const event of events) snapshot = applyCoreAppEvent(snapshot, event)
  return snapshot
}

function partsOf(snapshot: CoreAppSnapshot) {
  return selectCoreWorkbenchMessages(snapshot).flatMap((message) => message.parts ?? [])
}

function decisionPart(snapshot: CoreAppSnapshot) {
  return partsOf(snapshot).find((part) => part.partType === 'decision')
}

describe('what the contractor emits, the screen shows', () => {
  it('renders the user instruction as a message', () => {
    const snapshot = applyAll(eventsOf("the user's instruction becomes a visible user message"))
    const user = selectCoreWorkbenchMessages(snapshot).find((message) => message.role === 'user')
    expect(user?.content).toBe('Create notes.md with three lines')
  })

  it('renders the reply and the turn it belongs to', () => {
    const snapshot = applyAll(
      eventsOf('a started turn is a status row, and the reply is one message per round'),
    )
    const messages = selectCoreWorkbenchMessages(snapshot)
    expect(messages.some((message) => message.role === 'assistant' && message.content === 'Done.')).toBe(true)
  })

  it('shows nothing for a reply that carried no text', () => {
    const snapshot = applyAll(eventsOf('a reply with no text produces no bubble'))
    expect(selectCoreWorkbenchMessages(snapshot)).toEqual([])
  })

  it('shows one answerable card carrying the request the host sent', () => {
    const snapshot = applyAll(eventsOf('a prepared tool and its approval card share one row'))
    const decision = decisionPart(snapshot)
    expect(decision, 'the projection produced no decision part').toBeTruthy()

    // The click must become `approval/respond` with this id, not a chat message.
    for (const option of [{ id: 'approve' }, { id: 'deny' }]) {
      const plan = coreDecisionSelectionPlan(decision, {
        partId: decision!.id,
        option,
        response: option.id,
      } as never)
      expect(plan.status, `option ${option.id} degraded to plain text`).toBe('approval')
      expect(plan).toMatchObject({ requestId: 'req-1' })
    }
  })

  it('stops offering a card the user already answered', () => {
    const events = eventsOf('an answered approval ends the card without touching its turn')
    const asking = applyAll(events.slice(0, -1))
    expect(decisionPart(asking)?.status).toBe('pending')

    const settled = applyAll(events.slice(-1), asking)
    expect(decisionPart(settled)?.status, 'the card stayed answerable').not.toBe('pending')
  })

  it('shows the file the tool wrote', () => {
    const snapshot = applyAll(eventsOf('a completed tool carries its result and files it produced'))
    const artifacts = Object.values(snapshot.core?.artifacts ?? {})
    const written = artifacts.find((artifact) => artifact.name === 'notes.md')
    expect(written, `no file card among ${JSON.stringify(artifacts)}`).toBeTruthy()
    expect(written?.path).toBe('notes.md')
    expect(written?.item_id).toBe('th:turn-1:call-1:tool')
  })

  it('reports a failed call as failed', () => {
    const snapshot = applyAll(eventsOf('a failed tool says so instead of looking finished'))
    const item = snapshot.core?.items?.['th:turn-2:call-2:tool']
    expect(item?.status).toBe('failed')
    expect(String(item?.payload?.error ?? '')).toBe('the user denied this call')
  })

  it('keeps one message when the same fact arrives twice', () => {
    // Identity, not rendering: the second event carries the same event_id, so the
    // store's seen-set drops it. Two rows for one fact is the failure this prevents.
    const snapshot = applyAll(eventsOf('the same fact replayed keeps one identity'))
    expect(Object.keys(snapshot.core?.items ?? {})).toEqual(['th:turn-1:assistant:0'])
  })

  it('applies two unanchored closures without colliding', () => {
    const snapshot = applyAll(eventsOf('two unanchored closures stay distinguishable'))
    expect(Object.keys(snapshot.core?.items ?? {}).length).toBe(2)
  })

  it('ignores an event the contract says produces nothing', () => {
    const events = eventsOf('an event with no rendered meaning produces nothing')
    expect(events).toEqual([])
    expect(selectCoreWorkbenchMessages(applyAll(events))).toEqual([])
  })
})

import type { CoreAppSnapshot } from './protocol.ts'

export function hydrateSnapshot(snapshot: CoreAppSnapshot): CoreAppSnapshot {
  return {
    ...snapshot,
    seen_event_ids: snapshot.seen_event_ids ?? [],
    turns: snapshot.turns ?? {},
    items: snapshot.items ?? {},
    item_order: snapshot.item_order ?? [],
    queue: snapshot.queue ?? [],
    requests: snapshot.requests ?? {},
    artifacts: snapshot.artifacts ?? {},
    core: snapshot.core ?? {
      thread_id: snapshot.thread_id,
      snapshot_seq: 0,
      seen_event_ids: [],
      turns: {},
      items: {},
      item_order: [],
      requests: {},
      artifacts: {},
      status: 'idle',
    },
    status: snapshot.status ?? 'idle',
  }
}

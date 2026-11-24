import { describe, expect, it } from 'vitest'

import {
  loadPendingWrites,
  PENDING_WRITE_TTL_MS,
  pendingKey,
  pendingWritesFor,
  rememberPendingWrite,
  settlePendingWrite,
  type PendingWrite,
} from '../src/appServer/pendingWrites.ts'

class MemoryStorage {
  private readonly values = new Map<string, string>()
  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }
  setItem(key: string, value: string): void {
    this.values.set(key, value)
  }
}

function entry(now: number, overrides: Partial<PendingWrite> = {}): PendingWrite {
  return {
    key: pendingKey('thread-1', 'cid-1'),
    threadId: 'thread-1',
    clientMessageId: 'cid-1',
    method: 'turn/start',
    createdAt: now,
    expiresAt: now + PENDING_WRITE_TTL_MS,
    ...overrides,
  }
}

describe('pending writes', () => {
  // user:“断线后恢复未确认的消息与任务状态”+(回执丢了要跨重启记得，不能当成没发过)。
  it('remembers an unconfirmed write across a reload and settles it on the receipt', () => {
    const storage = new MemoryStorage()
    rememberPendingWrite(entry(1_000), 1_000, storage)
    expect(loadPendingWrites(1_000, storage)).toHaveLength(1)

    settlePendingWrite(pendingKey('thread-1', 'cid-1'), 1_100, storage)
    expect(loadPendingWrites(1_100, storage)).toHaveLength(0)
  })

  it('replaces the same key instead of stacking duplicates', () => {
    const storage = new MemoryStorage()
    rememberPendingWrite(entry(1_000), 1_000, storage)
    rememberPendingWrite(entry(1_000, { method: 'turn/resume' }), 1_100, storage)
    const pending = loadPendingWrites(1_100, storage)
    expect(pending).toHaveLength(1)
    expect(pending[0].method).toBe('turn/resume')
  })

  // user:“支持 TTL”+(过了一天还留着只会让用户重发一条早就翻页的消息)。
  it('drops entries whose TTL has passed', () => {
    const storage = new MemoryStorage()
    rememberPendingWrite(entry(1_000, { expiresAt: 2_000 }), 1_000, storage)
    expect(loadPendingWrites(1_999, storage)).toHaveLength(1)
    expect(loadPendingWrites(2_001, storage)).toHaveLength(0)
  })

  it('filters by thread and survives broken storage contents', () => {
    const storage = new MemoryStorage()
    rememberPendingWrite(entry(1_000), 1_000, storage)
    rememberPendingWrite(entry(1_000, {
      key: pendingKey('thread-2', 'cid-2'),
      threadId: 'thread-2',
      clientMessageId: 'cid-2',
    }), 1_000, storage)
    expect(pendingWritesFor('thread-1', 1_000, storage)).toHaveLength(1)

    storage.setItem('sunday.pendingWrites.v1', 'not json')
    expect(loadPendingWrites(1_000, storage)).toEqual([])
  })
})

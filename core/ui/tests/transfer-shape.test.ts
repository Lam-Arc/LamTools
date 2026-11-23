import { describe, expect, it } from 'vitest'

import {
  formatBytes,
  hasActiveTransfer,
  isFreshReceived,
  normalizeReceived,
  normalizeTransfers,
  progressText,
  transferDirectionLabel,
  transferStateLabel,
} from '../src/transfer/shape'

/**
 * user:“进度展示：进度优先使用现有事件/状态推送…进度整形”+
 * 宿主给什么，界面就得画成什么：缺百分比用字节算、越界夹住、状态不认识的时候不假装在传。
 */
describe('transfer shaping', () => {
  it('derives the percent from bytes when the host omits it', () => {
    const [row] = normalizeTransfers([
      { id: 't1', direction: 'send', name: 'a.bin', total: 1000, transferred: 250, state: 'transferring' },
    ])
    expect(row.percent).toBe(25)
    expect(row.active).toBe(true)
    expect(row.retryable).toBe(false)
  })

  it('clamps nonsense percentages instead of painting past the bar', () => {
    const rows = normalizeTransfers([
      { id: 'a', total: 10, transferred: 10, percent: 480, state: 'transferring' },
      { id: 'b', total: 10, transferred: 4, percent: -3, state: 'transferring' },
    ])
    const byId = (id: string) => rows.find((row) => row.id === id)
    // 两个数都不可信：一律退回按字节算，永远落在 0–100。
    expect(byId('a')?.percent).toBe(100)
    expect(byId('b')?.percent).toBe(40)
  })

  it('keeps a running transfer in front and newest first inside each group', () => {
    const rows = normalizeTransfers([
      { id: 'done-1', state: 'completed', direction: 'send', total: 1, transferred: 1 },
      { id: 'run-1', state: 'transferring', direction: 'send', total: 10, transferred: 1 },
      { id: 'done-2', state: 'failed', direction: 'send', total: 2, transferred: 0 },
      { id: 'run-2', state: 'offered', direction: 'receive', total: 10, transferred: 0 },
    ])
    expect(rows.map((row) => row.id)).toEqual(['run-2', 'run-1', 'done-2', 'done-1'])
  })

  it('only lets a stopped outgoing transfer be retried', () => {
    const rows = normalizeTransfers([
      { id: 's-f', state: 'failed', direction: 'send' },
      { id: 'r-f', state: 'failed', direction: 'receive' },
      { id: 's-d', state: 'completed', direction: 'send' },
      { id: 's-c', state: 'cancelled', direction: 'send' },
    ])
    const byId = (id: string) => rows.find((row) => row.id === id)
    expect(byId('s-f')?.retryable).toBe(true)
    expect(byId('s-c')?.retryable).toBe(true)
    expect(byId('r-f')?.retryable).toBe(false)
    expect(byId('s-d')?.retryable).toBe(false)
  })

  it('never pretends an unknown state is still running', () => {
    const [row] = normalizeTransfers([{ id: 'x', state: 'weird', direction: 'send' }])
    expect(row.active).toBe(false)
    expect(row.state).toBe('failed')
  })

  it('drops received entries with no path and keeps the rest', () => {
    const rows = normalizeReceived([
      { transferId: 'a', path: 'C:/received/2026-01-01/a.txt', name: 'a.txt', size: 2048, peer: '手机', at: 100 },
      { transferId: 'b', path: '', name: 'no-path.txt' },
      null,
    ])
    expect(rows).toHaveLength(1)
    expect(rows[0].path).toBe('C:/received/2026-01-01/a.txt')
    expect(rows[0].peer).toBe('手机')
  })

  it('flags only files received after the panel was opened', () => {
    expect(isFreshReceived({ at: 120 }, 100)).toBe(true)
    expect(isFreshReceived({ at: 90 }, 100)).toBe(false)
    expect(isFreshReceived({ at: 0 }, 0)).toBe(false)
  })

  it('tells whether anything is still moving', () => {
    expect(hasActiveTransfer(normalizeTransfers([{ id: 'a', state: 'offered' }]))).toBe(true)
    expect(hasActiveTransfer(normalizeTransfers([{ id: 'a', state: 'completed' }]))).toBe(false)
  })

  it('reads sizes and progress the way a person would', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(12 * 1024 * 1024)).toBe('12.0 MB')
    expect(progressText({ transferred: 2048, total: 4096 })).toBe('2.0 KB / 4.0 KB')
  })

  it('labels states and directions in the interface language', () => {
    expect(transferStateLabel('transferring')).toBe('传输中')
    expect(transferStateLabel('completed')).toBe('已完成')
    expect(transferDirectionLabel('receive')).toBe('接收')
    expect(transferDirectionLabel('send')).toBe('发送')
  })
})

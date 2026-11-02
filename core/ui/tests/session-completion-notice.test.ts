import { describe, expect, it } from 'vitest'

import {
  isBusySessionStatus,
  selectFinishedSessionNotices,
} from '../src/sessions/completion'

function session(id: string, status: string | undefined, title = id) {
  return { id, title, createdAt: '2026-10-31T00:00:00Z', status }
}

describe('selectFinishedSessionNotices', () => {
  it('notices a background session that stopped running and completed', () => {
    const notices = selectFinishedSessionNotices(
      [session('a', 'running')],
      [session('a', 'completed', '鱼丸')],
      { activeSessionId: 'active' },
    )
    expect(notices).toEqual([{ id: 'a', title: '鱼丸', status: 'completed' }])
  })

  it('notices waiting and sub-agent sessions settling, and reports failures', () => {
    const notices = selectFinishedSessionNotices(
      [session('a', 'waiting'), session('b', 'sub_agents'), session('c', 'running')],
      [session('a', 'completed'), session('b', 'completed'), session('c', 'failed')],
      { activeSessionId: 'active' },
    )
    expect(notices.map((notice) => [notice.id, notice.status])).toEqual([
      ['a', 'completed'],
      ['b', 'completed'],
      ['c', 'failed'],
    ])
  })

  it('never notifies for the session the user is already looking at', () => {
    const notices = selectFinishedSessionNotices(
      [session('active', 'running')],
      [session('active', 'completed')],
      { activeSessionId: 'active' },
    )
    expect(notices).toEqual([])
  })

  it('does not repeat a notice for an already settled session or a brand new one', () => {
    const notices = selectFinishedSessionNotices(
      [session('a', 'completed'), session('b', 'idle')],
      [session('a', 'completed'), session('b', 'idle'), session('new', 'running')],
      { activeSessionId: 'active' },
    )
    expect(notices).toEqual([])
  })

  it('keeps a user-stopped session quiet', () => {
    const notices = selectFinishedSessionNotices(
      [session('a', 'running')],
      [session('a', 'cancelled')],
      { activeSessionId: 'active' },
    )
    expect(notices).toEqual([])
  })

  it('treats statuses case-insensitively and understands the done/error aliases', () => {
    expect(isBusySessionStatus('Running')).toBe(true)
    expect(isBusySessionStatus('sub_agents')).toBe(true)
    expect(isBusySessionStatus('completed')).toBe(false)
    const notices = selectFinishedSessionNotices(
      [session('a', 'RUNNING'), session('b', 'running')],
      [session('a', 'DONE'), session('b', 'error')],
      { activeSessionId: 'active' },
    )
    expect(notices.map((notice) => notice.status)).toEqual(['completed', 'failed'])
  })
})

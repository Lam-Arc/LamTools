import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'

import { __resetCoreToastStoreForTests, useCoreToast } from '../src/composables/useCoreToast'
import { useSessionCompletionNotices } from '../src/composables/useSessionCompletionNotices'

function session(id: string, status: string, title = id) {
  return { id, title, createdAt: '2026-10-31T00:00:00Z', status }
}

function runNotices(options: Parameters<typeof useSessionCompletionNotices>[0]) {
  const scope = effectScope()
  scope.run(() => useSessionCompletionNotices(options))
  return scope
}

describe('useSessionCompletionNotices', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    __resetCoreToastStoreForTests()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('pops a notice for a finished background session and opens it when clicked', async () => {
    const sessions = ref([session('a', 'running', '鱼丸')])
    const opened: string[] = []
    const scope = runNotices({
      sessions,
      activeSessionId: ref('active'),
      openSession: (id) => { opened.push(id) },
      refreshSessions: () => {},
    })

    sessions.value = [session('a', 'completed', '鱼丸')]
    await nextTick()

    const { toasts } = useCoreToast()
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].text).toContain('鱼丸')
    expect(toasts.value[0].text).toContain('已完成')
    expect(toasts.value[0].action?.label).toBe('打开会话')

    toasts.value[0].action?.run()
    expect(opened).toEqual(['a'])
    scope.stop()
  })

  it('reports a failed background turn as an error', async () => {
    const sessions = ref([session('a', 'running')])
    const scope = runNotices({
      sessions,
      activeSessionId: ref(null),
      openSession: () => {},
      refreshSessions: () => {},
    })

    sessions.value = [session('a', 'failed')]
    await nextTick()

    const { toasts } = useCoreToast()
    expect(toasts.value[0].kind).toBe('error')
    expect(toasts.value[0].text).toContain('执行失败')
    scope.stop()
  })

  it('keeps polling while a session is busy and stops once it settles', async () => {
    const sessions = ref([session('a', 'running')])
    const refreshSessions = vi.fn()
    const scope = runNotices({
      sessions,
      activeSessionId: ref('active'),
      openSession: () => {},
      refreshSessions,
      busyPollIntervalMs: 4000,
    })

    vi.advanceTimersByTime(4000)
    expect(refreshSessions).toHaveBeenCalledTimes(1)

    sessions.value = [session('a', 'completed')]
    await nextTick()
    vi.advanceTimersByTime(20_000)
    expect(refreshSessions).toHaveBeenCalledTimes(1)
    scope.stop()
  })
})

import { nextTick, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useCorePendingGuidance } from '../src/composables/useCorePendingGuidance'
import type { CoreAppSnapshot } from '../src/appServer'
import type { CoreInputItem } from '../src/types'

const TURN = 'thread-1:turn:run-1'

function snapshot(options: {
  turnStatus?: string
  turnId?: string
  guides?: Array<{ id: string; text: string; turnId?: string }>
  threadId?: string
} = {}): CoreAppSnapshot {
  const threadId = options.threadId || 'thread-1'
  const turnId = options.turnId || TURN
  const guides = options.guides || []
  const items: Record<string, unknown> = {}
  for (const guide of guides) {
    items[guide.id] = {
      item_id: guide.id,
      turn_id: guide.turnId || turnId,
      kind: 'message',
      status: 'completed',
      content: guide.text,
      payload: { type: 'userMessage', content: [{ type: 'text', text: guide.text }] },
    }
  }
  const turn = {
    turn_id: turnId,
    status: options.turnStatus || 'running',
    items: guides.map(guide => guide.id),
  }
  return {
    thread_id: threadId,
    snapshot_seq: 1,
    status: 'running',
    core: {
      thread_id: threadId,
      snapshot_seq: 1,
      status: 'running',
      items,
      item_order: guides.map(guide => guide.id),
      turns: { [turnId]: turn },
      requests: {},
    },
  } as unknown as CoreAppSnapshot
}

function createFixture(initial = snapshot()) {
  const snapshotRef = ref<CoreAppSnapshot | null>(initial)
  const activeThreadId = ref<string | null>('thread-1')
  const composerText = ref('')
  const queued: Array<{ threadId: string; input: CoreInputItem[] }> = []
  const errors: string[] = []
  let queueFails = false
  const guidance = useCorePendingGuidance({
    snapshot: snapshotRef,
    activeThreadId,
    composerText,
    queueInput: async (threadId, input) => {
      if (queueFails) throw new Error('queue unavailable')
      queued.push({ threadId, input })
    },
    onError: (message) => errors.push(message),
  })
  return {
    activeThreadId,
    composerText,
    errors,
    guidance,
    queued,
    snapshotRef,
    failQueue(value: boolean) {
      queueFails = value
    },
  }
}

describe('useCorePendingGuidance', () => {
  it('shows a pending bubble right after the guide is accepted', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '改成蓝色')
    await nextTick()

    const visible = fixture.guidance.guidanceParts.value
    expect(visible).toHaveLength(1)
    expect(visible[0]?.turnId).toBe(TURN)
    expect(visible[0]?.part).toMatchObject({
      partType: 'guidance',
      status: 'pending',
      content: '改成蓝色',
      metadata: { guidancePending: true },
    })

    // 投影缓存依赖 part 引用稳定：快照每帧更新时不能重建对象
    const first = visible[0]?.part
    fixture.snapshotRef.value = snapshot()
    await nextTick()
    expect(fixture.guidance.guidanceParts.value[0]?.part).toBe(first)
  })

  it('takes the pending bubble down once the real guide lands', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '改成蓝色')
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toHaveLength(1)

    fixture.snapshotRef.value = snapshot({
      guides: [{ id: `${TURN}:user:guide:evt-1`, text: '改成蓝色' }],
    })
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toEqual([])

    // 落库之后再怎么刷新也不会复活
    fixture.snapshotRef.value = snapshot({
      guides: [{ id: `${TURN}:user:guide:evt-1`, text: '改成蓝色' }],
    })
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toEqual([])
  })

  it('pairs identical guides one for one', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '再快一点')
    fixture.guidance.track('thread-1', TURN, '再快一点')
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toHaveLength(2)

    // 只有一条真落库：待生效剩一条，不能被整批吃掉
    fixture.snapshotRef.value = snapshot({
      guides: [{ id: `${TURN}:user:guide:evt-1`, text: '再快一点' }],
    })
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toHaveLength(1)

    fixture.snapshotRef.value = snapshot({
      guides: [
        { id: `${TURN}:user:guide:evt-1`, text: '再快一点' },
        { id: `${TURN}:user:guide:evt-2`, text: '再快一点' },
      ],
    })
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toEqual([])
  })

  it('returns an unlanded guide to an empty composer when the turn ends', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '改成蓝色')
    await nextTick()

    fixture.snapshotRef.value = snapshot({ turnStatus: 'cancelled' })
    await nextTick()
    await nextTick()

    expect(fixture.guidance.guidanceParts.value).toEqual([])
    expect(fixture.composerText.value).toBe('改成蓝色')
    expect(fixture.queued).toEqual([])
  })

  it('queues an unlanded guide when the composer already holds text', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '改成蓝色')
    fixture.composerText.value = '另一件要做的事'
    await nextTick()

    fixture.snapshotRef.value = snapshot({ turnStatus: 'cancelled' })
    await nextTick()
    await nextTick()

    expect(fixture.guidance.guidanceParts.value).toEqual([])
    expect(fixture.composerText.value).toBe('另一件要做的事')
    expect(fixture.queued).toEqual([
      { threadId: 'thread-1', input: [{ type: 'text', text: '改成蓝色' }] },
    ])
  })

  it('falls back to the composer when even the queue rejects the guide', async () => {
    const fixture = createFixture()
    fixture.failQueue(true)
    fixture.guidance.track('thread-1', TURN, '改成蓝色')
    fixture.composerText.value = '另一件要做的事'
    await nextTick()

    fixture.snapshotRef.value = snapshot({ turnStatus: 'failed' })
    await nextTick()
    await nextTick()

    expect(fixture.composerText.value).toBe('另一件要做的事\n改成蓝色')
    expect(fixture.errors).toEqual(['queue unavailable'])
  })

  it('leaves another thread\'s pending guide alone until that thread is open', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-2', 'thread-2:turn:run-9', '改成蓝色')
    await nextTick()

    // 当前会话看不到它，也不会因为"看不到"就把它作废
    expect(fixture.guidance.guidanceParts.value).toEqual([])

    fixture.activeThreadId.value = 'thread-2'
    await nextTick()
    const visible = fixture.guidance.guidanceParts.value
    expect(visible).toHaveLength(1)
    expect(visible[0]?.turnId).toBe('thread-2:turn:run-9')
  })

  it('does not treat a still running turn as ended', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '改成蓝色')
    await nextTick()

    // 快照暂时拿不到这一轮（状态未知）时不能误判作废
    fixture.snapshotRef.value = snapshot({ turnId: 'thread-1:turn:other' })
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toHaveLength(1)
    expect(fixture.composerText.value).toBe('')

    fixture.snapshotRef.value = snapshot({ turnStatus: 'running' })
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toHaveLength(1)
  })

  it('ignores blank text', async () => {
    const fixture = createFixture()
    fixture.guidance.track('thread-1', TURN, '   ')
    fixture.guidance.track('thread-1', '', '改成蓝色')
    await nextTick()
    expect(fixture.guidance.guidanceParts.value).toEqual([])
  })
})

import { describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'
import { createIdleHistoryMount } from '../src/composables/useIdleHistoryMount'

function manualIdleScheduler() {
  const queue: Array<() => void> = []
  return {
    schedule(callback: () => void): () => void {
      queue.push(callback)
      return () => {
        const index = queue.indexOf(callback)
        if (index >= 0) queue.splice(index, 1)
      }
    },
    async flush(times = 1): Promise<void> {
      for (let round = 0; round < times; round += 1) {
        const callback = queue.shift()
        if (callback) callback()
        await nextTick()
      }
    },
    pending: () => queue.length,
  }
}

describe('idle history mount', () => {
  it('widens page by page on idle callbacks with the anchoring discipline per page', async () => {
    const hasMore = ref(true)
    const busy = ref(false)
    let widened = 0
    const events: string[] = []
    const idle = manualIdleScheduler()
    const controller = createIdleHistoryMount({
      hasMoreHistory: hasMore,
      busy,
      loadMoreHistory: () => { widened += 1; events.push('widen') },
      captureAnchor: () => { events.push('capture'); return { tag: widened } },
      restoreViewport: (anchor) => { events.push(`restore:${(anchor as { tag: number }).tag}`) },
      afterDomUpdate: async () => { events.push('dom') },
      afterFrame: async () => { events.push('frame') },
      scheduleIdle: idle.schedule,
    })

    controller.schedule()
    expect(controller.hasPending()).toBe(true)
    await idle.flush()
    expect(widened).toBe(1)
    // 每页固定纪律：采集锚点 → 加宽 → 等 DOM → 还原 → 等一帧 → 再还原。
    expect(events).toEqual(['capture', 'widen', 'dom', 'restore:0', 'frame', 'restore:0'])
    // 还有剩余回合：自动排下一页。
    expect(controller.hasPending()).toBe(true)

    await idle.flush()
    expect(widened).toBe(2)
    expect(events.slice(6)).toEqual(['capture', 'widen', 'dom', 'restore:1', 'frame', 'restore:1'])

    // 没有剩余：链式排下的那一页触发时自动空转，不再加宽也不再续排。
    hasMore.value = false
    controller.schedule()
    await idle.flush()
    expect(widened).toBe(2)
    expect(controller.hasPending()).toBe(false)
  })

  it('does not schedule while busy and cancels pending work on session switch', async () => {
    const hasMore = ref(true)
    const busy = ref(false)
    let widened = 0
    const idle = manualIdleScheduler()
    const controller = createIdleHistoryMount({
      hasMoreHistory: hasMore,
      busy,
      loadMoreHistory: () => { widened += 1 },
      captureAnchor: () => null,
      restoreViewport: () => {},
      scheduleIdle: idle.schedule,
    })

    // 用户滚动触发的历史加载进行中：不排程，避免两个来源互相插页。
    busy.value = true
    controller.schedule()
    expect(controller.hasPending()).toBe(false)

    busy.value = false
    controller.schedule()
    expect(controller.hasPending()).toBe(true)

    // 会话切换：作废已排程的补齐，不给旧会话继续补页。
    controller.cancel()
    expect(controller.hasPending()).toBe(false)
    await idle.flush()
    expect(widened).toBe(0)
  })

  it('keeps widening in strict newest-to-oldest batches so DOM order never reshuffles', async () => {
    const hasMore = ref(true)
    const busy = ref(false)
    const pages: number[] = []
    const idle = manualIdleScheduler()
    const controller = createIdleHistoryMount({
      hasMoreHistory: hasMore,
      busy,
      loadMoreHistory: () => { pages.push(pages.length) },
      captureAnchor: () => null,
      restoreViewport: () => {},
      scheduleIdle: idle.schedule,
    })

    controller.schedule()
    await idle.flush(3)
    expect(pages).toEqual([0, 1, 2])
    // 每页补齐只加宽窗口：投影返回更长的数组，旧行的 key 不变，只是上方多出新行。
    expect(hasMore.value).toBe(true)
  })

  it('caps the idle pages and hands the rest to on-demand loading', async () => {
    const hasMore = ref(true)
    const busy = ref(false)
    let mounted = 0
    let widened = 0
    const idle = manualIdleScheduler()
    const controller = createIdleHistoryMount({
      hasMoreHistory: hasMore,
      busy,
      loadMoreHistory: () => { widened += 1; mounted += 10 },
      captureAnchor: () => null,
      restoreViewport: () => {},
      progress: () => mounted,
      maxBatches: 2,
      scheduleIdle: idle.schedule,
    })

    controller.schedule()
    await idle.flush(5)
    expect(widened).toBe(2)
    expect(controller.mountedBatches()).toBe(2)
    expect(controller.hasPending()).toBe(false)

    // 仍有缺口也不再排页：巨型线程的剩余历史交给用户上翻时的按需加载。
    controller.schedule()
    await idle.flush()
    expect(widened).toBe(2)
  })

  it('does not spend the page budget on idle pages that mount nothing', async () => {
    const hasMore = ref(true)
    const busy = ref(false)
    let progressValue = 0
    let widened = 0
    // 前一段模拟"这一页在等服务端分页"：窗口没有真的加宽，内容条数不变。
    let wideningEnabled = false
    const idle = manualIdleScheduler()
    const controller = createIdleHistoryMount({
      hasMoreHistory: hasMore,
      busy,
      loadMoreHistory: () => { widened += 1; if (wideningEnabled) progressValue += 10 },
      captureAnchor: () => null,
      restoreViewport: () => {},
      progress: () => progressValue,
      maxBatches: 3,
      scheduleIdle: idle.schedule,
    })

    // 这一页没挂上来任何内容（例如在等服务端历史分页）：不占预算，也不空转续排。
    controller.schedule()
    await idle.flush()
    expect(widened).toBe(1)
    expect(controller.mountedBatches()).toBe(0)
    expect(controller.hasPending()).toBe(false)

    // 内容到位后由宿主重排，此时才开始正常计费。
    wideningEnabled = true
    controller.schedule()
    await idle.flush()
    expect(widened).toBe(2)
    expect(controller.mountedBatches()).toBe(1)
  })

  it('refills the page budget on session switch', async () => {
    const hasMore = ref(true)
    const busy = ref(false)
    let mounted = 0
    let widened = 0
    const idle = manualIdleScheduler()
    const controller = createIdleHistoryMount({
      hasMoreHistory: hasMore,
      busy,
      loadMoreHistory: () => { widened += 1; mounted += 10 },
      captureAnchor: () => null,
      restoreViewport: () => {},
      progress: () => mounted,
      maxBatches: 1,
      scheduleIdle: idle.schedule,
    })

    controller.schedule()
    await idle.flush(2)
    expect(widened).toBe(1)
    controller.schedule()
    await idle.flush()
    expect(widened).toBe(1)

    // 切会话：作废未执行的补齐，新会话重新享有完整预算。
    controller.cancel()
    expect(controller.mountedBatches()).toBe(0)
    controller.schedule()
    await idle.flush()
    expect(widened).toBe(2)
  })
})

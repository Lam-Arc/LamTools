import { getCurrentScope, onScopeDispose, type Ref } from 'vue'

/**
 * 首屏分批挂载的空闲补齐控制器。
 *
 * 大会话首绘只挂最近若干个回合（窗口化），其余历史回合由本控制器在浏览器
 * 空闲时分页补齐：用户之后向上翻历史时，内容已经在 DOM 里，不再出现滚动
 * 中途等挂载的顿挫。每一页都走宿主注入的锚定流程——补挂发生在视口上方，
 * 必须把首条可见消息按视口坐标还原，否则用户正读历史时会当场跳屏。
 *
 * 语义：
 *  - 单页锁：`busy` 为真（用户滚动触发的历史加载或上一页补齐未完）时不排程。
 *  - 锚定纪律：每页固定为"采集锚点 → 加宽窗口 → 等 DOM → 还原视口 →
 *    等一帧 → 再还原"，第一遍校正布局、第二遍吸收异步撑高的元素。
 *  - 顺序保证：只做"从新到旧逐页加宽窗口"，投影数组顺序即真实时序，DOM 里
 *    新插入的行全部位于既有行之上，顺序永不重排。
 *  - 空闲优先：requestIdleCallback（带超时兜底，避免长期忙碌时永不补齐），
 *    无该 API 的环境退化为短延时定时器。
 *  - 有上限：每个会话只补 `maxBatches` 页（默认见
 *    `IDLE_HISTORY_MAX_BATCHES`），到顶即停，剩下的历史交给用户上翻时的
 *    按需加载——超大线程不会在闲置期被逐页拉成全量 DOM。
 *  - 只算真页：宿主给了 `progress` 时，只有进度真的前进才算消耗一页；空转
 *    页（例如正在等网络分页返回）不计费也不续排，等内容变化后由宿主重排。
 *  - 会话切换即作废：宿主调用 `cancel()` 丢弃未执行的补齐并重置本会话预算。
 */
export interface IdleHistoryMountOptions {
  /** 还有多少回合未挂载；为假时停止补齐。 */
  hasMoreHistory: Ref<boolean>
  /** 单页互斥锁：用户滚动触发的历史加载或上一页补齐进行中时为真。 */
  busy: Ref<boolean>
  /** 加宽一页历史窗口（只改投影窗口，不发网络）。 */
  loadMoreHistory: () => void
  /** 补挂一页前采集锚点（首条可见消息视口坐标 + 滚动基准）。 */
  captureAnchor: () => unknown
  /** 补挂后按锚点还原视口（锚点失效时在宿主内走高度差兜底）。 */
  restoreViewport: (anchor: unknown) => void
  /** DOM 更新完成的钩子（默认不等待）。 */
  afterDomUpdate?: () => Promise<void>
  /** 一帧之后的钩子（默认 rAF），二次还原前等布局稳定。 */
  afterFrame?: () => Promise<void>
  /** 空闲调度器（默认 requestIdleCallback，超时 400ms；无则 32ms 定时器）。 */
  scheduleIdle?: (callback: () => void) => () => void
  /** 每会话的空闲补齐页数上限（默认 `IDLE_HISTORY_MAX_BATCHES`）。 */
  maxBatches?: number
  /** 已挂载内容的进度探针（例如当前投影的消息条数）：只有它前进时这一页才
   *  计入预算；没有前进说明这一页在等别的东西（网络分页），不计费也不续排。 */
  progress?: () => number
}

export interface IdleHistoryMountController {
  /** 有剩余且当前不忙时排一页空闲补齐；重复调用合并。 */
  schedule: () => void
  /** 丢弃已排程的补齐并重置本会话的页预算（会话切换时调用）。 */
  cancel: () => void
  /** 测试观察口：是否有已排程未执行的补齐。 */
  hasPending: () => boolean
  /** 测试观察口：本会话已计入预算的空闲补齐页数。 */
  mountedBatches: () => number
}

/**
 * 每会话的空闲补齐页数上限。一页就是宿主的一个完整回合页
 * （`HISTORY_TURN_PAGE_SIZE` = 10 个完整回合），所以上限即"最近约 130 个回合"
 * （初始窗口 10 + 12 页 × 10），约 260 条消息：正常规模的会话仍会补齐到无等待，
 * 而文档里那种千级回合的巨型线程只被补齐约十分之一，其余留给按需加载。
 */
export const IDLE_HISTORY_MAX_BATCHES = 12

function defaultScheduleIdle(callback: () => void): () => void {
  const idle = (globalThis as { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number }).requestIdleCallback
  if (typeof idle === 'function') {
    const id = idle(callback, { timeout: 400 })
    return () => {
      const cancelIdle = (globalThis as { cancelIdleCallback?: (id: number) => void }).cancelIdleCallback
      if (typeof cancelIdle === 'function') cancelIdle(id)
    }
  }
  const id = setTimeout(callback, 32)
  return () => clearTimeout(id)
}

export function createIdleHistoryMount(options: IdleHistoryMountOptions): IdleHistoryMountController {
  const {
    hasMoreHistory,
    busy,
    loadMoreHistory,
    captureAnchor,
    restoreViewport,
    afterDomUpdate,
    afterFrame,
    scheduleIdle = defaultScheduleIdle,
    maxBatches = IDLE_HISTORY_MAX_BATCHES,
    progress,
  } = options

  let pendingCancel: (() => void) | null = null
  let batches = 0

  async function mountOnePage(): Promise<void> {
    pendingCancel = null
    if (busy.value || !hasMoreHistory.value) return
    if (batches >= maxBatches) return
    const before = progress ? progress() : 0
    const anchor = captureAnchor()
    busy.value = true
    try {
      loadMoreHistory()
      if (afterDomUpdate) await afterDomUpdate()
      restoreViewport(anchor)
      if (afterFrame) await afterFrame()
      restoreViewport(anchor)
    } finally {
      busy.value = false
    }
    if (progress) {
      // 空转页不计数也不续排：这一页没让任何内容挂上来，说明它在等别的东西
      // （例如服务端历史分页）。内容变化后宿主会重新排页，不必在这里空转。
      if (progress() <= before) return
    }
    batches += 1
    if (hasMoreHistory.value) schedule()
  }

  function schedule(): void {
    if (pendingCancel || busy.value || !hasMoreHistory.value) return
    if (batches >= maxBatches) return
    pendingCancel = scheduleIdle(() => { void mountOnePage() })
  }

  function cancel(): void {
    if (pendingCancel) {
      pendingCancel()
      pendingCancel = null
    }
    batches = 0
  }

  if (getCurrentScope()) {
    onScopeDispose(cancel)
  }

  return {
    schedule,
    cancel,
    hasPending: () => pendingCancel !== null,
    mountedBatches: () => batches,
  }
}

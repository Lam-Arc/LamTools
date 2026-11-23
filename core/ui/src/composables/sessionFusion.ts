/**
 * Agent 纵向融合：把「选中的会话」和右侧内容区画成一块连续的面。
 *
 * user:“当前选中的会话与右侧内容区形成连续轮廓；连接处上下用内凹圆角过渡；
 * 消除明显直角拼接与独立胶囊卡片感”+
 * (两侧面板本来就同底色，所以只剩两处会露馅：会话栏与聊天卡之间那条缝、以及两边的描边。
 *  连接处就是补上这两处：一条铺在同底色上的「舌头」跨过缝、盖住描边，四角用内凹（mask 挖掉四分之一圆）
 *  收口，于是选中的会话看起来是从内容区里伸出来的一格，而不是并排的另一个胶囊卡片)。
 *
 * 这里只有几何与「什么时候真的写一次」：测量/写变量在 useSessionFusion 里，
 * 画在 WorkspaceShell 的 .session-fusion 上（它必须画在聊天卡之上，所以不能放在会话栏里）。
 */

export interface FusionGeometry {
  visible: boolean
  top: number
  height: number
  /** 选中行自己的填充要往右多铺多少像素，才能正好接上连接处（缝 + 侧栏内边距）。 */
  rowBleed: number
}

export const NO_FUSION: FusionGeometry = { visible: false, top: 0, height: 0, rowBleed: 0 }

/**
 * user:“连接处上下用内凹圆角过渡”+(几何只认两个数：行在视口里的上下沿，和会话栏的右缘；
 * 往右铺多少由两者之差算出，不写死侧栏内边距，换密度/换宽度都自动对）。
 * user:“dev 界面卡死、未响应…审计并加固这条回路”+
 * (三个数一律取整：子像素抖动会让“值相等短路”永远不成立，等于每帧都真写一次)。
 */
/** 行高亮伪元素本身比行盒左右各外扩这么多（与 .conversation::before 的 -space-2 对应）。 */
export const ROW_FILL_INSET = 8

export function fusionGeometry(
  row: { top: number; bottom: number; right: number } | null,
  drawerInnerRight: number,
  fillInset = ROW_FILL_INSET,
): FusionGeometry {
  if (!row) return NO_FUSION
  const top = Math.round(row.top)
  const height = Math.round(row.bottom - row.top)
  if (height <= 0) return NO_FUSION
  // user:“选中行底色只在侧栏内部铺满…不得越过侧栏右缘…若保留 row-bleed：row 右缘 + bleed = 侧栏内缘，不能大于”+
  // (行高亮的 ::before 自己已经比行盒外扩 8px，所以 bleed 要把这 8px 扣掉；
  //  以前直接拿 侧栏右缘 - 行右缘，多铺了 8px + 1px 描边，就成了截图里悬在缝里的那块深色)。
  const visibleRight = row.right + fillInset
  return { visible: true, top, height, rowBleed: Math.round(Math.max(0, drawerInnerRight - visibleRight)) }
}

/** 一次测量结果的指纹：几何没变就一个字节都不写。 */
export function fusionKey(geometry: FusionGeometry | null): string {
  if (!geometry || !geometry.visible) return 'none'
  return `${geometry.top}|${geometry.height}|${geometry.rowBleed}`
}

export interface FusionWriterOptions<T> {
  /** 读 DOM，算这一次该画成什么；返回 null 表示“这次不该画”。 */
  measure: () => T | null
  /** 把结论写到 DOM 上（只有指纹变化时才会被调用）。 */
  write: (value: T | null) => void
  /** 指纹：默认按 FusionGeometry 算，其他载荷自己给。 */
  keyOf?: (value: T | null) => string
  raf?: (callback: () => void) => number
  cancelRaf?: (handle: number) => void
}

export interface FusionWriter {
  /** 请求一次测量：同一帧内多次请求只跑一次（合并到单个 rAF）。 */
  schedule: () => void
  /** 丢掉比较基线：下一次一定真写一次（换会话、侧栏开合后用）。 */
  invalidate: () => void
  /** 停掉：取消挂起的帧，之后的所有 schedule 都是空操作。 */
  dispose: () => void
}

/**
 * user:“写入前做值相等短路；所有测量合并到单个 rAF，并在 onBeforeUnmount 停掉”+
 * (这条回路以前每帧都无条件写自定义属性——而写在 .workspace-shell 上的自定义属性会被整棵子树继承，
 *  每写一次就把整个界面标脏一次，下一帧的 getBoundingClientRect 又强制一次全量布局；
 *  滚动时这就是一台永动的“强制布局 + 全树重算”机器，dev 下直接表现为界面未响应)。
 * 现在：同一帧只量一次；量与上次一样就只读不写；卸载后彻底停。
 */
export function createFusionWriter<T>(options: FusionWriterOptions<T>): FusionWriter {
  const hasRaf = typeof requestAnimationFrame === 'function'
  const raf = options.raf ?? (hasRaf ? (callback: () => void) => requestAnimationFrame(callback) : (callback: () => void) => { callback(); return 0 })
  const cancelRaf = options.cancelRaf ?? (hasRaf ? (handle: number) => cancelAnimationFrame(handle) : () => {})
  const keyOf = options.keyOf ?? ((value: T | null) => fusionKey(value as FusionGeometry | null))
  let handle = 0
  let pending = false
  let disposed = false
  // null = 未知：第一次一定写一次，之后才有“相等就不写”的短路。
  let last: string | null = null

  function flush() {
    pending = false
    handle = 0
    if (disposed) return
    const value = options.measure()
    const key = keyOf(value)
    if (key === last) return
    last = key
    options.write(value)
  }

  return {
    schedule() {
      if (disposed || pending) return
      pending = true
      handle = raf(flush)
    },
    invalidate() { last = null },
    dispose() {
      disposed = true
      if (handle) cancelRaf(handle)
      handle = 0
      pending = false
    },
  }
}

/**
 * user:“补一条断言：选中行右缘与内容区左缘之间的缝隙宽度为 0”+
 * (连接处是三层东西拼起来的：选中行自己的填充（往右多铺 rowBleed）、连接层（从会话栏右缘开始、
 *  往右伸 inset 到内容区里）、以及两者共同的底色。任何一段少铺一点，就会露出中缝或 1px 断线)。
 */
export interface FusionSeamInput {
  /** 选中行元素自身的右缘（CSS px，视口坐标）。 */
  rowRight: number
  /** 行填充往右多铺的量（= 会话栏右缘 - rowRight）。 */
  rowBleed: number
  /** 连接层的左缘（= 会话栏右缘）。 */
  plateLeft: number
  /** 连接层的宽度（= 内容区左缘 - 会话栏右缘 + inset）。 */
  plateWidth: number
  /** 内容区（主区/内容卡片）左缘。 */
  contentLeft: number
}

/** 返回未被覆盖的缝隙宽度；正常应为 0。 */
export function fusionSeamGap(input: FusionSeamInput): number {
  const rowEnd = input.rowRight + input.rowBleed
  const needed = Math.max(0, input.contentLeft - rowEnd)
  const covered = Math.max(0, input.plateLeft + input.plateWidth - rowEnd)
  return Math.max(0, needed - covered)
}

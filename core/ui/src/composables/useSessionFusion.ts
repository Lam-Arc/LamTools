/**
 * 测量并广播「选中会话与内容区的连接处」几何。
 *
 * user:“当前选中的会话与右侧内容区形成连续轮廓…连接处上下用内凹圆角过渡”+
 * (连接处必须画在聊天卡之上，所以那一层在 WorkspaceShell 里；会话栏只知道行在哪，
 *  把三个数写到 DOM 上就够了，两边不用互相引用组件)。
 *
 * user:“dev 界面卡死、未响应…审计并加固这条回路”+
 * (这条回路原来有三个放大器：window 捕获阶段监听滚动 = 全应用任何滚动都触发；
 *  每次触发无条件写 --session-fusion-* = 写在 .workspace-shell 上的自定义属性被子树继承，
 *  等于每帧把整个界面标脏一次；下一帧的 getBoundingClientRect 又强制一次全量布局。
 *  现在：只监听会话栏自己的滚动容器、合并到单个 rAF、值相等就不写、
 *  写变量落到真正用到它的元素上（连接处图层 / 选中的那一行），不再写在外壳上放大到全树。
 */
import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import { createFusionWriter, fusionGeometry, type FusionGeometry } from './sessionFusion'

/** 选中行统一挂这个类：项目列表和「最近」两处都用它标出来。 */
export const SESSION_FUSION_CLASS = 'is-fused'
/** 连接处图层（在 WorkspaceShell 里画）。 */
const FUSION_PLATE = '.session-fusion'
/** 只有真的“两层并排”的形态才画连接处；窄窗里会话栏是抽屉浮层。 */
const NARROW_QUERY = '(max-width: 640px)'

// user:“在 dev 里用 data-session-fusion="on" 与 --session-fusion-* 是否写入自证”+
// (不写日志就只能靠肉眼；这里把“为什么没画”和“画成了什么”都打出来，下一次跑 dev 就能对齐)。
let lastSkipReason = ''
function skip(reason: string): null {
  if (import.meta.env?.DEV && lastSkipReason !== reason) {
    lastSkipReason = reason
    console.warn('[session-fusion]', { skipped: reason })
  }
  return null
}

export function useSessionFusion(rootRef: Ref<HTMLElement | null>) {
  const drawer = () => rootRef.value?.closest<HTMLElement>('.drawer-left') ?? null
  const shell = () => rootRef.value?.closest<HTMLElement>('.workspace-shell') ?? null
  const selectedRow = () =>
    rootRef.value?.querySelector<HTMLElement>(`.conversation.${SESSION_FUSION_CLASS}`)
    ?? rootRef.value?.querySelector<HTMLElement>(`[data-session-row].${SESSION_FUSION_CLASS}`)
    ?? null
  const scroller = () => rootRef.value?.closest<HTMLElement>('.sidebar-body') ?? rootRef.value
  const narrow = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(NARROW_QUERY).matches

  // 图层与上一行的缓存：写变量落到具体元素上，别落到外壳上（那会把整棵子树标脏）。
  let plate: HTMLElement | null = null
  let bleedTarget: HTMLElement | null = null
  let lastBleed: number | null = null

  const writer = createFusionWriter<FusionGeometry>({
    /**
     * user:“无选中项/侧栏收起时直接不写”+(量不到该画的东西就返回 null：
     * 没有选中会话、会话栏收起、窄窗抽屉形态、行滚出会话栏可见带、行高度为 0——一律不写)。
     */
    measure: () => {
      const host = shell()
      const row = selectedRow()
      const box = drawer()
      // user:“先修测量前置（侧栏 open、行在可见带、.workspace-shell 能取到）”+
      // (固定住的侧栏在 LeftSidebarShell 里是 `pinned` 而不是 `open`；只看 open 会让连接层永远不画)。
      const drawerVisible = Boolean(box) && (box!.classList.contains('open') || box!.classList.contains('pinned'))
      if (!host) return skip('no-host')
      if (!row) return skip('no-row')
      if (!box || !drawerVisible) return skip('drawer-hidden')
      if (narrow()) return skip('narrow')
      const rowRect = row.getBoundingClientRect()
      const boxRect = box.getBoundingClientRect()
      // 侧栏内缘：盒子右缘扣掉那条描边（.left-open 下描边宽度是 0，这里算出来自然一致）。
      const borderRight = Number.parseFloat(getComputedStyle(box).borderRightWidth || '0') || 0
      // 行不在会话栏的可见带里：没有“连接”可画，也不要画到别处去。
      if (rowRect.bottom <= boxRect.top || rowRect.top >= boxRect.bottom) return null
      // 图层是相对外壳定位的（position: absolute），所以坐标要减掉外壳的原点。
      const shellRect = host.getBoundingClientRect()
      const geometry = fusionGeometry(
        { top: rowRect.top - shellRect.top, bottom: rowRect.bottom - shellRect.top, right: rowRect.right },
        boxRect.right - borderRight,
      )
      return geometry.visible ? geometry : null
    },
    write: geometry => {
      const host = shell()
      if (!host) return
      if (!plate || !plate.isConnected) plate = host.querySelector<HTMLElement>(FUSION_PLATE)
      if (!geometry) {
        // 收起来：只改一次属性，变量留在那儿也不影响（图层已经不画了）。
        if (host.hasAttribute('data-session-fusion')) host.removeAttribute('data-session-fusion')
        return
      }
      if (plate) {
        // user:“写入前做值相等短路”+(图层只用到 top/height，写在它自己身上，重绘范围就只有这一条)。
        plate.style.setProperty('--session-fusion-top', `${geometry.top}px`)
        plate.style.setProperty('--session-fusion-height', `${geometry.height}px`)
      }
      // row-bleed 只被选中行用到：写在那一行上，并且只在真的变了才写。
      const row = selectedRow()
      if (row && (row !== bleedTarget || geometry.rowBleed !== lastBleed)) {
        row.style.setProperty('--session-fusion-row-bleed', `${geometry.rowBleed}px`)
        bleedTarget = row
        lastBleed = geometry.rowBleed
      }
      if (host.getAttribute('data-session-fusion') !== 'on') host.setAttribute('data-session-fusion', 'on')
    },
  })

  let resizeObserver: ResizeObserver | null = null
  let drawerObserver: MutationObserver | null = null
  let container: HTMLElement | null = null

  const schedule = () => writer.schedule()
  const scheduleAfterChange = () => { writer.invalidate(); writer.schedule() }

  onMounted(() => {
    schedule()
    window.addEventListener('resize', schedule, { passive: true })
    // user:“无界重排”+(只监听会话栏自己的滚动容器，不再用 window 捕获阶段吃掉全应用的滚动：
    //  聊天区流式输出时的自动滚动跟这条装饰一点关系都没有)。
    container = scroller()
    container?.addEventListener('scroll', schedule, { passive: true })
    const box = drawer()
    if (typeof ResizeObserver !== 'undefined' && box) {
      resizeObserver = new ResizeObserver(schedule)
      resizeObserver.observe(box)
    }
    if (typeof MutationObserver !== 'undefined' && box) {
      // 展开/收起只改 class，不触发 resize 也不滚动：跟着那一下重量一次（并丢掉基线）。
      drawerObserver = new MutationObserver(scheduleAfterChange)
      drawerObserver.observe(box, { attributes: true, attributeFilter: ['class'] })
    }
    // 抽屉滑入是 280ms 过渡：过渡结束后再量一次，最终位置才准（中间帧错了也只是短暂偏移）。
    box?.addEventListener('transitionend', schedule, { passive: true })
  })

  onBeforeUnmount(() => {
    writer.dispose()
    window.removeEventListener('resize', schedule)
    container?.removeEventListener('scroll', schedule)
    container = null
    const box = drawer()
    box?.removeEventListener('transitionend', schedule)
    resizeObserver?.disconnect()
    resizeObserver = null
    drawerObserver?.disconnect()
    drawerObserver = null
    plate = null
    bleedTarget = null
    lastBleed = null
    shell()?.removeAttribute('data-session-fusion')
  })

  return { refresh: scheduleAfterChange }
}

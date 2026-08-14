import { nextTick, type ObjectDirective } from 'vue'
import { coreIsScrollNearBottom } from '../composables/useCoreAutoFollowScroll'

/**
 * Core 自动跟随滚动 —— 内层面板指令（v-auto-follow-scroll）
 *
 * 适用目标：消息/流块内部自身就是可滚动容器的面板
 * （`.reasoning-body`、`.tool-output`、`.context-tool-output` 等，
 * 它们都是 max-height + overflow:auto 的真实滚动元素）。
 * 若指令挂在不可滚动元素上，则向上解析最近的可滚动祖先作为滚动目标
 * （防御性，真实使用时面板自身即滚动容器）。
 *
 * 与容器级控制器（useCoreAutoFollowScroll）分工：
 *  - 控制器管线程窗口（.thread / 对话框 timeline）：大滚动容器 + "回到最新"按钮。
 *  - 指令管消息内面板：面板自己的内容流式增长时跟随到底部；用户上翻面板内容
 *    则暂停，回到底部自动恢复。互不嵌套干扰。
 *
 * 实现要点（对照易错点清单）：
 *  - **ResizeObserver 观察滚动容器自身无法捕获内容增长**：scrollHeight 变化并不
 *    改变 layout box（RO 只看 content/border box 尺寸）。因此 observer 同时观察
 *    滚动目标 + 其全部直接子元素——流式内容变长由子元素尺寸变化触发回调；观察
 *    目标自身 box 变化（展开/折叠动画、字体换行）也触发。二者是同一回调（易错点 9）。
 *  - 不依赖 Vue `updated` 钩子做主要驱动（易错点 12/13）：`updated` 在组件每次
 *    重渲都触发（绑定值引用未变也触发），逐帧滚就是旧版卡顿路径。`updated` 仅两个
 *    窄用途：① 绑定值字符串确实变化（oldValue !== value）时补一次滚（内容变了但
 *    尺寸未变的极端兜底）；② 把后挂载的直接子元素补进 observer（v-if 晚挂载内容）。
 *  - 回调内 gating（易错点 10）：仅"跟随中"才滚到底；用户上翻（scrollTop 远离
 *    底部）自动置 follow=false，回到底部自动恢复 —— 与容器控制器同判据。
 *  - 帧与帧之间只写一次 scrollTop，且只在内容确实变高时二次校正（易错点 5/6）。
 *  - 面板刚挂载（mounted）即自动跟随一次到底（易错点 16 的首次进入语义）。
 *  - unmount 时断开 observer、移除监听、清空 WeakMap（防泄漏）。
 */

interface AutoFollowState {
  follow: boolean
  observer: ResizeObserver | null
  onScroll: () => void
  onWheel: (event: WheelEvent) => void
  /** 程序化滚动标记：下一次 scroll 事件消费，期间不判定"离开底部" */
  programmatic: boolean
  /** mounted 首滚已完成；observer 首次回调若在首滚前到达则跳过，避免双滚 */
  bootstrapped: boolean
}

const states = new WeakMap<HTMLElement, AutoFollowState>()

function isScrollable(el: HTMLElement): boolean {
  let ov = ''
  const cs = typeof getComputedStyle === 'function' ? getComputedStyle(el) : null
  ov = cs?.overflowY || el.style.overflowY || el.style.overflow || ''
  return ov === 'auto' || ov === 'scroll' || ov === 'overlay'
}

/** 滚动目标：自身可滚动用自身，否则向上找最近可滚动祖先（找不到回退自身） */
function resolveScrollTarget(element: HTMLElement): HTMLElement {
  if (isScrollable(element)) return element
  let parent = element.parentElement
  while (parent) {
    if (isScrollable(parent)) return parent
    parent = parent.parentElement
  }
  return element
}

/** 把滚动目标的全部直接子元素补进 observer —— 捕获内容增长（RO 不观察滚动溢出） */
function observeChildren(observer: ResizeObserver, target: HTMLElement) {
  for (const child of Array.from(target.children)) {
    if (child instanceof HTMLElement) observer.observe(child)
  }
}

function scrollToBottom(element: HTMLElement, target: HTMLElement, state: AutoFollowState) {
  if (!state.follow) return
  state.programmatic = true
  target.scrollTop = target.scrollHeight
  // 二次校正：等一帧后若内容又长了（流式 tick），补一次 —— 单通道单写原则
  void nextTick().then(() => {
    if (!state.follow) return
    if (target.scrollTop !== target.scrollHeight) {
      state.programmatic = true
      target.scrollTop = target.scrollHeight
    }
  })
}

export const autoFollowScrollDirective: ObjectDirective<HTMLElement, string> = {
  mounted(element, binding) {
    const target = resolveScrollTarget(element)
    const state: AutoFollowState = {
      follow: true,
      observer: null,
      programmatic: false,
      bootstrapped: false,
      onScroll: () => {
        // 程序化滚动产生的 scroll 事件：仅消费标记，不判定（防误伤易错点 16）
        if (state.programmatic) {
          state.programmatic = false
          return
        }
        // 双向同步：不近底部 => 停止跟随；回到近底部 => 恢复跟随
        state.follow = coreIsScrollNearBottom(target)
      },
      onWheel: (event) => {
        // 用户上翻立即抢占，不等 scroll 事件
        if (event.deltaY < 0) {
          state.follow = false
          state.programmatic = false
        }
      },
    }
    states.set(element, state)
    target.addEventListener('scroll', state.onScroll, { passive: true })
    target.addEventListener('wheel', state.onWheel, { passive: true })
    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(() => {
        if (!state.bootstrapped) {
          // mounted 首滚尚未完成：由 mounted 统一做首滚，这里只等
          return
        }
        // 补 observe 晚挂载的直接子元素（v-if 内容），然后跟随
        observeChildren(observer, target)
        scrollToBottom(element, target, state)
      })
      state.observer = observer
      observer.observe(target)
      observeChildren(observer, target)
    }
    // mounted 首滚 —— 无论有无 observer 都执行一次（内容可能已就绪）
    state.bootstrapped = true
    scrollToBottom(element, target, state)
  },
  updated(element, binding) {
    const state = states.get(element)
    if (!state) return
    // ① 把后挂载的直接子元素补进 observer（v-if 晚挂载内容）
    if (state.observer) observeChildren(state.observer, resolveScrollTarget(element))
    // ② 仅绑定值（内容字符串）确实变化时触发一次跟随 —— 兜底"内容变了但尺寸未变"
    if (binding.oldValue === undefined) return
    if (binding.value === binding.oldValue) return
    if (state.bootstrapped) scrollToBottom(element, resolveScrollTarget(element), state)
  },
  unmounted(element) {
    const state = states.get(element)
    if (!state) return
    state.observer?.disconnect()
    state.observer = null
    const target = resolveScrollTarget(element)
    target.removeEventListener('scroll', state.onScroll)
    target.removeEventListener('wheel', state.onWheel)
    states.delete(element)
  },
}
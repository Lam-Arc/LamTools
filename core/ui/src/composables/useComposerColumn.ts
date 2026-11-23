/**
 * 用「主内容列」的**实测矩形**约束输入栏。
 *
 * user:“输入栏必须限制在主内容列内——这一条上一轮已经改过…但从截图看没有生效…若某些形态下主列几何变量缺失，
 * 就回退到「主区容器 getBoundingClientRect()」而不是 100vw——宽度绝不允许多于主列”+
 * (上一轮只把实测值写成 CSS 变量，指望级联把它送到输入栏上：要连续命中两跳——
 *  `.workspace-shell--split` 类在壳上、`--composer-measured-*` 被子树继承。
 *  任何一跳失配，`var()` 就回退到 100vw，输入栏于是又横跨到右侧分屏上。
 *  现在改成：量 `.workspace-main` 的真实矩形，把 left/width/max-width 直接写成**内联样式**落在输入栏本体上。
 *  内联优先级最高，不需要选择器命中、不依赖变量继承，也无法被任何规则顶掉。
 *  不在分屏形态时立刻撤掉内联值，原样交还给 CSS 的居中/底部那几套规则。)
 */
import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import { composerColumnStyle } from '@/composer/composerColumn'

/** 只由这里接管的三条内联属性；撤掉时也只撤这三条，不碰别的内联样式。 */
const INLINE_PROPERTIES = ['left', 'width', 'max-width'] as const

function clearInline(element: HTMLElement) {
  INLINE_PROPERTIES.forEach(property => element.style.removeProperty(property))
}

export function useComposerColumn(shellRef: Ref<HTMLElement | null>) {
  let observer: ResizeObserver | null = null
  let shellObserver: MutationObserver | null = null
  let frame = 0
  let retries: Array<ReturnType<typeof setTimeout>> = []
  // 每实例一份基线（原来在模块作用域，第二个壳会跟第一个抢着短路）。
  let lastKey = ''

  /**
   * 主区那条输入栏本体。
   *
   * user:“输入栏从聊天区一直横跨到右侧分屏上方，压住了打开内容/辅助对话按钮”+
   * (壳改版后 `composer-root` 不再一定是壳的一级子节点：只扫直接子节点会一个都找不到，
   *  内联约束就静默失效、退回 CSS 的 100vw 兜底，输入栏于是又横跨到分屏上。
   *  现在从整棵壳里找，并排除子代理/侧屏复用的嵌入式输入栏。
   *  另外量不到时不是“什么都不做”，而是记账后重试——见 measure() 与 retries)。
   */
  function composerElement(): HTMLElement | null {
    const shell = shellRef.value
    if (!shell) return null
    const candidates = Array.from(shell.querySelectorAll<HTMLElement>('.floating-composer'))
    return candidates.find(element => !element.closest('.composer-root--embedded')) ?? null
  }

  function measure() {
    frame = 0
    const shell = shellRef.value
    if (!shell) return
    const main = shell.querySelector<HTMLElement>('.workspace-main')
    const rect = main?.getBoundingClientRect()
    // 主区还没布局（宽为 0）时什么都不写：下一帧再量。
    if (!rect || rect.width <= 0) return
    const element = composerElement()
    const split = shell.classList.contains('workspace-shell--split')
    const key = `${split ? 'split' : 'single'}|${Math.round(rect.left)}|${Math.round(rect.width)}|${element ? 1 : 0}`
    if (key === lastKey) return
    lastKey = key
    if (!element) return
    if (!split) { clearInline(element); return }
    const style = composerColumnStyle({ x: rect.left, y: rect.top, width: rect.width, height: rect.height })
    element.style.setProperty('left', style.left)
    element.style.setProperty('width', style.width)
    element.style.setProperty('max-width', style.maxWidth)
    // user:“先自证规则是否生效…把结果写进汇报”+
    // (dev 里量一次只打一行，且已经被上面的值相等短路挡住，不会刷屏；
    //  前端控制台落盘到 core/data/core-agent/frontend-console.log，扒一行就能核对类名与真实像素)。
    if (import.meta.env?.DEV) {
      console.debug('[composer-column]', {
        shellHasSplitClass: split,
        mainLeft: Math.round(rect.left),
        mainWidth: Math.round(rect.width),
        left: style.left,
        width: style.width,
        maxWidth: style.maxWidth,
      })
    }
  }

  function schedule() {
    if (frame) return
    frame = typeof requestAnimationFrame === 'function' ? requestAnimationFrame(measure) : (measure(), 0)
  }

  /** 分屏开关只改壳上的 class，不触发 resize：跟着那一下重量一次。 */
  function invalidate() {
    lastKey = ''
    schedule()
  }

  onMounted(() => {
    schedule()
    // user:“从截图看没有生效”+(首次挂载时输入栏/主区可能还没布局完：补两次重试；
    //  量到了会被 lastKey 短路，不会重复写样式)。
    retries = [120, 400].map(delay => setTimeout(schedule, delay))
    window.addEventListener('resize', schedule, { passive: true })
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(schedule)
      const main = shellRef.value?.querySelector<HTMLElement>('.workspace-main')
      if (main) observer.observe(main)
    }
    if (typeof MutationObserver !== 'undefined' && shellRef.value) {
      shellObserver = new MutationObserver(schedule)
      shellObserver.observe(shellRef.value, { attributes: true, attributeFilter: ['class'] })
    }
  })
  onBeforeUnmount(() => {
    retries.forEach(handle => clearTimeout(handle))
    retries = []
    if (frame && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frame)
    window.removeEventListener('resize', schedule)
    observer?.disconnect()
    observer = null
    shellObserver?.disconnect()
    shellObserver = null
    const element = composerElement()
    if (element) clearInline(element)
    lastKey = ''
  })

  return { refresh: invalidate }
}

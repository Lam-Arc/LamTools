/**
 * 灯箱的状态是单例。
 *
 * user:“灯箱：浮层盖在会话上，看完即关，不打断对话…空状态/多目标暂不做，先保证单目标正确”+
 * (同一时刻只有一份预览：打开即替换目标。灯箱没有 pane，因此刻意不复用分屏的标签状态。)
 */
import { computed, ref } from 'vue'
import { previewTargetKey, previewTargetTitle, type PreviewTarget } from './target'

const target = ref<PreviewTarget | null>(null)
const open = ref(false)
/** 打开前持有焦点的元素；关闭后要把焦点还回去，键盘用户不能掉进文档根部。 */
const returnFocus = ref<HTMLElement | null>(null)

export interface OpenInLightboxOptions {
  /** 明确指定打开前焦点该还到哪里；默认取当前 activeElement。 */
  restoreFocusTo?: HTMLElement | null
}

/**
 * user:“提供 openInLightbox(target) 与至少一个真实入口”+
 * (所有入口都走这一个函数：它只登记"要预览什么"，不关心渲染，也不依赖调用方在被覆盖的浮层里)。
 */
export function openInLightbox(next: PreviewTarget, options: OpenInLightboxOptions = {}): void {
  if (typeof document !== 'undefined') {
    const explicit = options.restoreFocusTo
    const active = explicit ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
    returnFocus.value = active
  }
  target.value = next
  open.value = true
}

/**
 * 关闭灯箱时的选项。
 *
 * user:“『引用』…直接加入输入框”+(引用成功后要直接关掉灯箱，但输入框刚拿到焦点，
 * 不能又被「还给打开灯箱的那个元素」抢走，所以这一种关闭跳过焦点归还)。
 */
export interface CloseLightboxOptions {
  restoreFocus?: boolean
}

/** 这一轮关闭是否跳过焦点归还（由 close 决定，reset 时清掉）。 */
let skipRestoreFocus = false

/** 关闭灯箱；焦点归还在过渡结束后由 `restorePreviewLightboxFocus` 完成。 */
export function closePreviewLightbox(options: CloseLightboxOptions = {}): void {
  skipRestoreFocus = options.restoreFocus === false
  open.value = false
}

/**
 * user:“灯箱加上切换用的左右键”+(换的是「同一个灯箱里的内容」，不是重开一次：
 * 目标一换，解析、查看器、标注状态都按既有规则重来；打开/关闭与焦点归还保持不变)。
 */
export function switchPreviewTarget(next: PreviewTarget): void {
  target.value = next
}

/** 过渡结束后把焦点还给打开它的那个元素。 */
export function restorePreviewLightboxFocus(): void {
  if (skipRestoreFocus) {
    skipRestoreFocus = false
    returnFocus.value = null
    return
  }
  const previous = returnFocus.value
  returnFocus.value = null
  if (previous && typeof previous.focus === 'function' && previous.isConnected) previous.focus()
}

/** 关闭并清空目标（过渡完毕时调用）。 */
export function resetPreviewLightbox(): void {
  open.value = false
  target.value = null
  skipRestoreFocus = false
}

/**
 * 灯箱宿主是否在场。
 *
 * user:“至少接一个真实入口证明可用”+(同一份文件引用组件也会出现在没有灯箱宿主的窗口里；
 * 那里点了媒体不应该静默失败，所以要能判断"灯箱能不能接"，不能接就走原来的通道)。
 */
const hostCount = ref(0)

export function registerPreviewLightboxHost(): () => void {
  hostCount.value += 1
  return () => { hostCount.value = Math.max(0, hostCount.value - 1) }
}

export function previewLightboxAvailable(): boolean {
  return hostCount.value > 0
}

export function usePreviewLightbox() {
  return {
    // 用 computed 而不是 readonly()：只读包装会把手写类型摊成 DeepReadonly，
    // 组件里按 target.kind 分支时会丢掉联合类型的收窄。
    target: computed(() => target.value),
    open: computed(() => open.value),
    title: computed(() => previewTargetTitle(target.value)),
    targetKey: computed(() => previewTargetKey(target.value)),
    openLightbox: openInLightbox,
    closeLightbox: closePreviewLightbox,
    restoreFocus: restorePreviewLightboxFocus,
    reset: resetPreviewLightbox,
  }
}

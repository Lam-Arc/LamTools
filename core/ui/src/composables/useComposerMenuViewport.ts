import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'

export function useComposerMenuViewport(root: Ref<HTMLElement | null>, panel?: Ref<HTMLElement | null>) {
  const bottom = ref(0)
  const floatingStyle = ref('')
  let observer: ResizeObserver | undefined

  function updateViewportPosition(): void {
    const element = root.value
    if (!element) return
    const gap = Number.parseFloat(getComputedStyle(element).getPropertyValue('--space-2')) || 8
    const anchor = element.getBoundingClientRect()
    bottom.value = Math.max(0, window.innerHeight - anchor.top + gap)
    if (panel?.value) {
      // user:“被异常截断了”+(顶层菜单按窗口坐标定位，脱离输入栏与分屏的裁切；靠近窗口上缘时向下展开)。
      const popup = panel.value, margin = 12
      const width = popup.getBoundingClientRect().width
      const left = Math.max(margin, Math.min(window.innerWidth - width - margin, anchor.left + anchor.width / 2 - width / 2))
      const above = Math.max(0, anchor.top - gap - margin)
      const below = Math.max(0, window.innerHeight - anchor.bottom - gap - margin)
      const placement = above >= Math.min(240, below) ? 'above' : 'below'
      popup.dataset.placement = placement
      floatingStyle.value = `--composer-menu-left: ${left}px; --composer-menu-top: ${placement === 'below' ? `${anchor.bottom + gap}px` : 'auto'}; --composer-menu-bottom: ${placement === 'above' ? `${bottom.value}px` : 'auto'}; --composer-menu-max-height: ${placement === 'above' ? above : below}px`
    }
  }

  const viewportStyle = computed(() => panel ? floatingStyle.value : `--composer-menu-bottom: ${bottom.value}px`)

  onMounted(() => {
    window.addEventListener('resize', updateViewportPosition)
    window.addEventListener('orientationchange', updateViewportPosition)
    if (panel) {
      window.addEventListener('scroll', updateViewportPosition, true)
      if (typeof ResizeObserver !== 'undefined') {
        observer = new ResizeObserver(updateViewportPosition)
        if (root.value) observer.observe(root.value)
      }
    }
  })

  onUnmounted(() => {
    window.removeEventListener('resize', updateViewportPosition)
    window.removeEventListener('orientationchange', updateViewportPosition)
    window.removeEventListener('scroll', updateViewportPosition, true)
    observer?.disconnect()
  })

  return { updateViewportPosition, viewportStyle }
}

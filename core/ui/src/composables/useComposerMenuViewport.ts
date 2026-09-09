import { computed, onMounted, onUnmounted, ref, type Ref } from 'vue'

export function useComposerMenuViewport(root: Ref<HTMLElement | null>) {
  const bottom = ref(0)

  function updateViewportPosition(): void {
    const element = root.value
    if (!element) return
    const gap = Number.parseFloat(getComputedStyle(element).getPropertyValue('--space-2')) || 8
    bottom.value = Math.max(0, window.innerHeight - element.getBoundingClientRect().top + gap)
  }

  const viewportStyle = computed(() => `--composer-menu-bottom: ${bottom.value}px`)

  onMounted(() => {
    window.addEventListener('resize', updateViewportPosition)
    window.addEventListener('orientationchange', updateViewportPosition)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', updateViewportPosition)
    window.removeEventListener('orientationchange', updateViewportPosition)
  })

  return { updateViewportPosition, viewportStyle }
}

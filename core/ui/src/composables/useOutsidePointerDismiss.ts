import { onMounted, onUnmounted, type Ref } from 'vue'

export interface OutsidePointerDismissOptions {
  /** The overlay that owns the backdrop. Events from other overlays are ignored. */
  overlay: Ref<HTMLElement | null>
  /** The card/popover that must not be treated as backdrop space. */
  card: Ref<HTMLElement | null>
  /** Whether the overlay is currently interactive (for conditional popovers). */
  isActive?: () => boolean
  /** Called after a complete outside pointer click. */
  onDismiss: () => void
}

function contains(element: HTMLElement | null, target: EventTarget | null): boolean {
  return Boolean(element && target instanceof Node && element.contains(target))
}

function isPrimaryPointer(event: PointerEvent): boolean {
  if (event.isPrimary === false) return false
  return event.pointerType !== 'mouse' || event.button === 0
}

/**
 * Dismiss an overlay only when one pointer starts and ends outside its card.
 *
 * A click handler alone can be delivered to the backdrop after a pointer is
 * pressed in the card and dragged out of it. Tracking both ends on the
 * document capture phase preserves the intended complete-outside-click rule,
 * including when a WebView temporarily captures the pointer on an ancestor.
 */
export function useOutsidePointerDismiss(options: OutsidePointerDismissOptions): void {
  let pointerId: number | null = null
  let startedOnOverlay = false
  let startedOutsideCard = false

  const isActive = options.isActive ?? (() => true)

  function reset(): void {
    pointerId = null
    startedOnOverlay = false
    startedOutsideCard = false
  }

  function onPointerDown(event: PointerEvent): void {
    reset()
    if (!isActive() || !options.overlay.value || !options.card.value || !isPrimaryPointer(event)) return

    // Do not let a nested/teleported overlay dismiss its parent. The initial
    // press must belong to this overlay's DOM subtree.
    if (!contains(options.overlay.value, event.target)) return

    pointerId = event.pointerId
    startedOnOverlay = true
    startedOutsideCard = !contains(options.card.value, event.target)
  }

  function onPointerUp(event: PointerEvent): void {
    if (pointerId === null || pointerId !== event.pointerId) return

    const completeOutsideClick =
      isActive() &&
      startedOnOverlay &&
      startedOutsideCard &&
      !contains(options.card.value, event.target)
    reset()
    if (completeOutsideClick) options.onDismiss()
  }

  function onPointerCancel(event: PointerEvent): void {
    if (pointerId === event.pointerId) reset()
  }

  onMounted(() => {
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('pointerup', onPointerUp, true)
    document.addEventListener('pointercancel', onPointerCancel, true)
  })

  onUnmounted(() => {
    document.removeEventListener('pointerdown', onPointerDown, true)
    document.removeEventListener('pointerup', onPointerUp, true)
    document.removeEventListener('pointercancel', onPointerCancel, true)
    reset()
  })
}

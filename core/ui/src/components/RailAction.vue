<template>
  <div
    ref="rootEl"
    class="rail-action"
    :class="{ 'is-tipped': tipOpen }"
    @mouseenter="openTip"
    @mouseleave="closeTip"
    @focusin="openTip"
    @focusout="onFocusOut"
  >
    <button
      class="rail-action__button"
      type="button"
      :aria-label="label"
      :aria-describedby="tipOpen ? tipId : undefined"
      :data-rail-action="actionId"
      @click="emit('click')"
    >
      <slot />
    </button>
    <div
      v-if="tipOpen"
      :id="tipId"
      class="rail-action__tip"
      :class="`rail-action__tip--${tipPlacement}`"
      role="tooltip"
      @mouseleave="infoOpen = false"
    >
      <div class="rail-action__tip-head">
        <span class="rail-action__tip-label">{{ label }}</span>
        <button
          class="rail-action__info"
          type="button"
          :aria-label="`${label}说明`"
          :aria-expanded="infoOpen"
          :data-rail-action-info="actionId"
          @mouseenter="infoOpen = true"
          @focus="infoOpen = true"
          @click.stop="infoOpen = !infoOpen"
        >
          <CircleAlert :size="12" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
      <p v-if="infoOpen" class="rail-action__tip-body" data-rail-action-intro>{{ description }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * RailAction — one icon-only entry in the left rail (the top toolbar row and the
 * bottom footer row).
 *
 * The label lives in a tip; the tip carries an alert glyph that reveals the
 * entry's one-line introduction. Hover or keyboard focus keeps the tip open, so
 * a rail row can stay a row of icons even in the compact width.
 *
 * The introduction is rendered above the label row and the label row is pinned
 * to the tip's edge the pointer sits next to (see the tip's column-reverse):
 * revealing the introduction must not move the glyph the pointer is resting on,
 * otherwise hover and un-hover alternate every frame. Closing hangs off the
 * tip's own leave, so crossing the tip — including the seam between the glyph
 * and the text it just revealed — cannot collapse what is being read.
 *
 * The tip is laid out against the row (`.sidebar-toolbar` / `.drawer-footer-row`
 * is the positioned ancestor) rather than the button: the compact rail is only
 * ~130px wide, and a per-button tip on the rightmost icons would be clipped by
 * the drawer's overflow.
 */
import { ref, useId } from 'vue'
import { CircleAlert } from 'lucide-vue-next'

withDefaults(defineProps<{
  /** Stable hook for host tests and styling, e.g. `arrange`. */
  actionId: string
  /** Short label shown in the tip. */
  label: string
  /** One-line introduction revealed from the tip's alert glyph. */
  description: string
  /** Which side of the row the tip opens on; the toolbar row opens downwards. */
  tipPlacement?: 'above' | 'below'
}>(), {
  tipPlacement: 'above',
})

const emit = defineEmits<{ click: [] }>()

const tipId = `${useId()}-rail-tip`
const rootEl = ref<HTMLElement | null>(null)
const tipOpen = ref(false)
const infoOpen = ref(false)

function openTip(): void {
  tipOpen.value = true
}

function closeTip(): void {
  tipOpen.value = false
  infoOpen.value = false
}

// Moving focus between the button and the tip's alert glyph stays inside the
// wrapper; only a focus that actually leaves it may close the tip.
function onFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget
  if (next instanceof Node && rootEl.value?.contains(next)) return
  closeTip()
}
</script>

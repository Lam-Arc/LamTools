<template>
  <Teleport to="body">
    <Transition name="core-confirm">
      <div
        v-if="open"
        ref="backdropEl"
        class="core-confirm__backdrop"
        @keydown.esc.prevent="cancel"
      >
        <section
          ref="dialogEl"
          class="core-confirm"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          :aria-describedby="descriptionId"
          :aria-busy="loading"
        >
          <div class="core-confirm__body">
            <h2 :id="titleId">{{ title }}</h2>
            <p :id="descriptionId">{{ description }}</p>
            <p v-if="detail" class="core-confirm__detail" :title="detail">{{ detail }}</p>
            <p v-if="error" class="core-confirm__error" role="alert">{{ error }}</p>
          </div>
          <footer class="core-confirm__actions">
            <button type="button" class="core-confirm__cancel" :disabled="loading" @click="cancel">
              取消
            </button>
            <button
              ref="confirmButtonEl"
              type="button"
              class="core-confirm__submit"
              :disabled="loading || confirmDisabled"
              @click="$emit('confirm')"
            >
              {{ loading ? '打开中…' : confirmLabel }}
            </button>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, useId, watch } from 'vue'
import { useOutsidePointerDismiss } from '../composables/useOutsidePointerDismiss'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description: string
  detail?: string
  confirmLabel?: string
  /** Additional caller-controlled guard for confirmations that require a delay. */
  confirmDisabled?: boolean
  loading?: boolean
  error?: string
}>(), {
  detail: '',
  confirmLabel: '确认',
  confirmDisabled: false,
  loading: false,
  error: '',
})

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const instanceId = useId()
const titleId = `core-confirm-title-${instanceId}`
const descriptionId = `core-confirm-description-${instanceId}`
const backdropEl = ref<HTMLElement | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
const confirmButtonEl = ref<HTMLButtonElement | null>(null)
let restoreFocus: HTMLElement | null = null

watch(() => props.open, async open => {
  if (open) {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    confirmButtonEl.value?.focus()
  } else {
    restoreFocus?.focus()
    restoreFocus = null
  }
}, { immediate: true })

onBeforeUnmount(() => {
  restoreFocus?.focus()
  restoreFocus = null
})

function cancel(): void {
  if (!props.loading) emit('cancel')
}

useOutsidePointerDismiss({
  overlay: backdropEl,
  card: dialogEl,
  isActive: () => props.open,
  onDismiss: cancel,
})
</script>

<style scoped>
.core-confirm__backdrop {
  --text: var(--theme-main-text);
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: color-mix(in srgb, var(--theme-backdrop-text) 20%, transparent);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}

.core-confirm {
  width: min(400px, 100%);
  overflow: hidden;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  box-shadow: var(--shadow-lg);
  color: var(--text);
}

.core-confirm__body {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-4);
}

.core-confirm h2,
.core-confirm p {
  margin: 0;
}

.core-confirm h2 {
  font-size: 16px;
  font-weight: 720;
  line-height: 1.35;
}

.core-confirm p {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 13px;
  line-height: 1.5;
}

.core-confirm .core-confirm__detail {
  overflow: hidden;
  color: var(--text);
  font-weight: 680;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-confirm .core-confirm__error {
  color: var(--red);
}

.core-confirm__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  border-top: 1px solid var(--theme-main-border);
  padding: var(--space-3) var(--space-4);
  background: var(--theme-main-soft-background);
}

.core-confirm__actions button {
  min-width: 72px;
  height: 34px;
  border-radius: var(--radius-sm);
  padding: 0 var(--space-3);
  font: inherit;
  font-size: 13px;
  font-weight: 680;
}

.core-confirm__cancel {
  border: 1px solid color-mix(in srgb, var(--theme-control-text) var(--alpha-active), transparent);
  background: transparent;
  color: var(--theme-control-text);
}

.core-confirm__cancel:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), transparent);
}

.core-confirm__cancel:active:not(:disabled) {
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), transparent);
}

.core-confirm__submit {
  border: 1px solid var(--theme-control-background);
  background: var(--theme-control-background);
  color: var(--theme-control-text);
}

.core-confirm__submit:hover:not(:disabled) {
  filter: brightness(.94);
}

.core-confirm__actions button:disabled {
  opacity: .45;
}

.core-confirm-enter-active,
.core-confirm-leave-active {
  transition: opacity 160ms ease-out;
}

.core-confirm-enter-active .core-confirm,
.core-confirm-leave-active .core-confirm {
  transition: transform 160ms ease-out, opacity 160ms ease-out;
}

.core-confirm-enter-from,
.core-confirm-leave-to,
.core-confirm-enter-from .core-confirm,
.core-confirm-leave-to .core-confirm {
  opacity: 0;
}

.core-confirm-enter-from .core-confirm,
.core-confirm-leave-to .core-confirm {
  transform: translateY(8px) scale(.98);
}

@media (prefers-reduced-motion: reduce) {
  .core-confirm-enter-active,
  .core-confirm-leave-active,
  .core-confirm-enter-active .core-confirm,
  .core-confirm-leave-active .core-confirm {
    transition-duration: 0ms;
  }
}
</style>

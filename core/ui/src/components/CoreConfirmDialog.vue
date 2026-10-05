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
          :aria-busy="loading"
        >
          <span :id="titleId" class="core-confirm__title">{{ title }}</span>
          <input
            v-if="input"
            ref="inputEl"
            class="core-confirm__input"
            :value="inputValue"
            :placeholder="inputPlaceholder"
            :aria-label="title"
            spellcheck="false"
            @input="$emit('update:inputValue', ($event.target as HTMLInputElement).value)"
            @keydown.enter.prevent="confirm"
          />
          <!-- 一格说明位：平时显示对象名（文件/项目/插件…），出错时由错误文本顶上。 -->
          <span
            v-else-if="error || detail"
            class="core-confirm__detail"
            :class="{ 'core-confirm__detail--error': Boolean(error) }"
            :title="error || detail"
          >{{ error || detail }}</span>
          <span class="core-confirm__spacer" aria-hidden="true"></span>
          <span class="core-confirm__actions">
            <button type="button" class="core-confirm__cancel" :disabled="loading" @click="cancel">
              取消
            </button>
            <button
              ref="confirmButtonEl"
              type="button"
              class="core-confirm__submit"
              :disabled="loading || confirmDisabled"
              @click="confirm"
            >
              确认
            </button>
          </span>
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
  /** 一行标题，说清要做什么（如「删除项目？」）。 */
  title: string
  /** 对象名等一行补充；与 error 共用同一格，出错时显示错误。 */
  detail?: string
  /** 需要用户填一个名字时给 true（如资料库归档的文件夹名）。 */
  input?: boolean
  inputValue?: string
  inputPlaceholder?: string
  /** Additional caller-controlled guard for confirmations that require a delay. */
  confirmDisabled?: boolean
  loading?: boolean
  error?: string
}>(), {
  detail: '',
  input: false,
  inputValue: '',
  inputPlaceholder: '',
  confirmDisabled: false,
  loading: false,
  error: '',
})

const emit = defineEmits<{
  confirm: []
  cancel: []
  'update:inputValue': [value: string]
}>()

const instanceId = useId()
const titleId = `core-confirm-title-${instanceId}`
const backdropEl = ref<HTMLElement | null>(null)
const dialogEl = ref<HTMLElement | null>(null)
const confirmButtonEl = ref<HTMLButtonElement | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)
let restoreFocus: HTMLElement | null = null

watch(() => props.open, async open => {
  if (open) {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    await nextTick()
    if (props.input) inputEl.value?.focus()
    else confirmButtonEl.value?.focus()
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

function confirm(): void {
  if (props.loading || props.confirmDisabled) return
  emit('confirm')
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
}

/* 胶囊：一行说清做什么，两端是取消与确认。 */
.core-confirm {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: min(520px, 100%);
  border-radius: 999px;
  padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
  background: var(--theme-main-background);
  box-shadow: var(--shadow-lg);
  color: var(--text);
}

.core-confirm__title {
  flex: 0 0 auto;
  font-size: 13px;
  font-weight: 680;
  white-space: nowrap;
}

.core-confirm__detail {
  overflow: hidden;
  min-width: 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-confirm__detail--error {
  color: var(--red);
}

.core-confirm__spacer {
  flex: 1 1 auto;
}

.core-confirm__input {
  flex: 1 1 auto;
  min-width: 0;
  height: 30px;
  border: 0;
  border-radius: 999px;
  padding: 0 var(--space-3);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
  font: inherit;
  font-size: 12px;
}

.core-confirm__input::placeholder {
  color: color-mix(in srgb, var(--text) 45%, transparent);
}

.core-confirm__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex: 0 0 auto;
}

.core-confirm__actions button {
  min-width: 56px;
  height: 30px;
  border: 0;
  border-radius: 999px;
  padding: 0 var(--space-3);
  font: inherit;
  font-size: 12px;
  font-weight: 680;
}

.core-confirm__cancel {
  background: transparent;
  color: color-mix(in srgb, var(--theme-control-text) 65%, transparent);
}

.core-confirm__cancel:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-hover), transparent);
  color: var(--theme-control-text);
}

.core-confirm__cancel:active:not(:disabled) {
  background: color-mix(in srgb, var(--theme-control-text) var(--alpha-active), transparent);
}

.core-confirm__submit {
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

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { useCoreToast, type CoreToast } from '@/composables/useCoreToast.ts'

const { toasts, dismiss } = useCoreToast()

function activate(toast: CoreToast): void {
  try {
    toast.action?.run()
  } finally {
    dismiss(toast.id)
  }
}
</script>

<template>
  <div
    class="core-toast-host"
    aria-live="polite"
  >
    <TransitionGroup name="core-toast">
      <div
        v-for="toast in toasts"
        :key="toast.id"
        :class="['core-toast', `core-toast--${toast.kind}`]"
        :role="toast.kind === 'error' ? 'alert' : 'status'"
        aria-atomic="true"
      >
        <button
          v-if="toast.action"
          type="button"
          class="core-toast__text core-toast__action"
          :title="toast.action.label"
          @click="activate(toast)"
        >{{ toast.text }}</button>
        <span v-else class="core-toast__text">{{ toast.text }}</span>
        <button
          type="button"
          class="core-toast__dismiss"
          :aria-label="t('关闭提示：{0}', { 0: toast.text })"
          @click="dismiss(toast.id)"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup lang="ts">
import { useCoreToast } from '../composables/useCoreToast'

const { toasts, dismiss } = useCoreToast()
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
        <span class="core-toast__text">{{ toast.text }}</span>
        <button
          type="button"
          class="core-toast__dismiss"
          :aria-label="`关闭提示：${toast.text}`"
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

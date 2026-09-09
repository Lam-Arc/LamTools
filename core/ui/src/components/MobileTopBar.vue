<template>
  <nav v-show="!hidden" ref="root" class="mobile-top-bar" aria-label="移动端快捷操作">
    <button
      class="mobile-top-bar__button"
      type="button"
      aria-label="打开左侧会话栏"
      title="会话与项目"
      data-mobile-sidebar-button
      @click="emit('open-sidebar')"
    >
      <PanelLeft :size="18" :stroke-width="1.8" aria-hidden="true" />
    </button>

    <div
      v-show="syncing"
      class="mobile-top-bar__sync"
      role="status"
      aria-live="polite"
    >
      <span ref="syncIcon" class="mobile-top-bar__sync-icon" aria-hidden="true">
        <RefreshCw :size="14" :stroke-width="1.9" />
      </span>
      <span>正在同步</span>
    </div>

    <button
      class="mobile-top-bar__button mobile-top-bar__button--account"
      type="button"
      aria-label="打开账号与连接"
      title="账号与连接"
      data-mobile-account-button
      @click="emit('open-account')"
    >
      <UserRound :size="17" :stroke-width="1.9" aria-hidden="true" />
    </button>
  </nav>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { PanelLeft, RefreshCw, UserRound } from 'lucide-vue-next'
import { gsap } from 'gsap'

const props = withDefaults(defineProps<{
  hidden?: boolean
  syncing?: boolean
}>(), {
  hidden: false,
  syncing: false,
})

const emit = defineEmits<{
  'open-sidebar': []
  'open-account': []
}>()

const root = ref<HTMLElement | null>(null)
const syncIcon = ref<HTMLElement | null>(null)
let motion: ReturnType<typeof gsap.matchMedia> | null = null
let syncTween: gsap.core.Tween | null = null

onMounted(() => {
  if (!root.value) return
  motion = gsap.matchMedia()
  motion.add('(prefers-reduced-motion: no-preference)', () => {
    const stop = watch(
      () => [props.syncing, props.hidden] as const,
      ([syncing, hidden]) => {
        syncTween?.kill()
        syncTween = null
        const icon = syncIcon.value
        if (!icon) return
        if (!syncing || hidden) {
          gsap.set(icon, { rotation: 0 })
          return
        }
        syncTween = gsap.to(icon, {
          rotation: 360,
          duration: 1.1,
          ease: 'none',
          repeat: -1,
          transformOrigin: '50% 50%',
        })
      },
      { immediate: true },
    )

    return () => {
      stop()
      syncTween?.kill()
      syncTween = null
    }
  }, root.value)
})

onUnmounted(() => {
  syncTween?.kill()
  syncTween = null
  motion?.revert()
  motion = null
})
</script>

<style scoped>
.mobile-top-bar {
  --text: var(--theme-control-text);
  position: fixed;
  top: max(var(--space-2), env(safe-area-inset-top, 0px));
  right: var(--space-3);
  left: var(--space-3);
  z-index: var(--z-popover);
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) 44px;
  align-items: center;
  pointer-events: none;
}

.mobile-top-bar__button {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  pointer-events: auto;
  backdrop-filter: blur(12px);
  -webkit-tap-highlight-color: transparent;
}

.mobile-top-bar__button--account {
  justify-self: end;
}

.mobile-top-bar__button:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.mobile-top-bar__button:active {
  background: color-mix(in srgb, var(--text) var(--alpha-press), transparent);
}

.mobile-top-bar__button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 72%, transparent);
  outline-offset: var(--space-1);
}

.mobile-top-bar__sync {
  justify-self: center;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 32px;
  padding: 0 var(--space-3);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-control-soft-background);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  box-shadow: var(--shadow-sm);
  font-size: 12px;
  font-weight: 650;
  pointer-events: none;
  backdrop-filter: blur(12px);
}

.mobile-top-bar__sync-icon {
  display: grid;
  place-items: center;
}

@media (prefers-reduced-motion: reduce) {
  .mobile-top-bar__sync-icon {
    transform: none !important;
  }
}
</style>

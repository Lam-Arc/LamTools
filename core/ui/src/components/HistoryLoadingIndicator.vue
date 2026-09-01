<template>
  <div
    ref="rootEl"
    class="history-loading"
    role="status"
    aria-live="polite"
    aria-label="正在加载历史消息"
    :aria-hidden="!active"
  >
    <span class="sr-only">正在加载历史消息</span>
    <div class="history-loading-stack" aria-hidden="true">
      <div
        v-for="(message, index) in loadingMessages"
        :key="index"
        class="history-loading-message"
        :class="`history-loading-message--${message.side}`"
      >
        <div
          class="history-loading-bubble"
          :class="`history-loading-bubble--${message.size}`"
          data-history-loading-bubble
        >
          <span
            v-for="(line, lineIndex) in message.lines"
            :key="lineIndex"
            class="history-loading-line"
            :class="`history-loading-line--${line}`"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { gsap } from 'gsap'

defineOptions({ name: 'HistoryLoadingIndicator' })

const props = withDefaults(defineProps<{
  active?: boolean
}>(), {
  active: false,
})
const rootEl = ref<HTMLElement | null>(null)

const loadingMessages = [
  { side: 'assistant', size: 'wide', lines: ['long', 'medium', 'short'] },
  { side: 'user', size: 'compact', lines: ['long', 'short'] },
  { side: 'assistant', size: 'medium', lines: ['long', 'medium'] },
  { side: 'user', size: 'wide', lines: ['medium', 'long', 'short'] },
  { side: 'assistant', size: 'compact', lines: ['long', 'medium'] },
] as const

let motionMedia: gsap.MatchMedia | null = null
let enterTimeline: gsap.core.Timeline | null = null
let idleTween: gsap.core.Tween | null = null
let exitTween: gsap.core.Tween | null = null

function bubbleElements(): HTMLElement[] {
  return rootEl.value
    ? Array.from(rootEl.value.querySelectorAll<HTMLElement>('[data-history-loading-bubble]'))
    : []
}

function killMotion(): void {
  enterTimeline?.kill()
  enterTimeline = null
  idleTween?.kill()
  idleTween = null
  exitTween?.kill()
  exitTween = null
  motionMedia?.revert()
  motionMedia = null
  if (rootEl.value) gsap.killTweensOf(rootEl.value)
  bubbleElements().forEach((bubble) => gsap.killTweensOf(bubble))
}

function show(): void {
  const root = rootEl.value
  if (!root) return

  killMotion()
  const bubbles = bubbleElements()
  gsap.set(root, { display: 'grid', autoAlpha: 1, y: 0 })
  gsap.set(bubbles, { autoAlpha: 0, y: 8, scale: 0.94 })

  motionMedia = gsap.matchMedia()
  motionMedia.add('(prefers-reduced-motion: no-preference)', () => {
    enterTimeline = gsap.timeline({ defaults: { overwrite: 'auto' } })
      .to(bubbles, {
        autoAlpha: 0.78,
        y: 0,
        scale: 1.018,
        duration: 0.42,
        stagger: 0.08,
        ease: 'back.out(1.45)',
      })
      .call(() => {
        if (!props.active) return
        idleTween = gsap.to(bubbles, {
          y: -1,
          scale: 1.008,
          duration: 1.2,
          stagger: { each: 0.08, from: 'start' },
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut',
        })
      })
  })
  motionMedia.add('(prefers-reduced-motion: reduce)', () => {
    gsap.set(bubbles, { autoAlpha: 0.58, y: 0, scale: 1 })
  })
}

function hide(): void {
  const root = rootEl.value
  if (!root) return

  killMotion()
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  if (reduceMotion) {
    gsap.set(root, { display: 'none', clearProps: 'autoAlpha,transform' })
    return
  }

  exitTween = gsap.to(root, {
    autoAlpha: 0,
    y: -6,
    duration: 0.18,
    ease: 'power2.out',
    overwrite: true,
    onComplete: () => {
      exitTween = null
      if (props.active) {
        show()
        return
      }
      gsap.set(root, { display: 'none', clearProps: 'autoAlpha,transform' })
    },
  })
}

watch(() => props.active, (active) => {
  if (active) show()
  else hide()
})

onMounted(() => {
  if (props.active) show()
})

onBeforeUnmount(() => {
  killMotion()
  if (rootEl.value) gsap.set(rootEl.value, { clearProps: 'all' })
})
</script>

<style scoped>
.history-loading {
  display: none;
  place-items: center;
  width: 100%;
  min-height: min(56vh, 420px);
  padding: var(--space-6) var(--space-4);
  pointer-events: none;
}

.history-loading-stack {
  display: grid;
  gap: var(--space-3);
  width: min(100%, 520px);
}

.history-loading-message {
  display: flex;
  width: 100%;
}

.history-loading-message--user {
  justify-content: flex-end;
}

.history-loading-bubble {
  position: relative;
  display: grid;
  gap: var(--space-2);
  overflow: hidden;
  width: 72%;
  padding: var(--space-3) var(--space-4);
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-text) 4%, transparent);
}

.history-loading-bubble::after {
  position: absolute;
  inset: 0;
  content: '';
  background: linear-gradient(
    105deg,
    transparent 24%,
    color-mix(in srgb, var(--theme-main-text) 10%, transparent) 50%,
    transparent 76%
  );
  transform: translateX(-100%);
  animation: history-loading-shimmer 1.7s ease-in-out infinite;
}

.history-loading-bubble--wide {
  width: 82%;
}

.history-loading-bubble--medium {
  width: 68%;
}

.history-loading-bubble--compact {
  width: 54%;
}

.history-loading-line {
  display: block;
  height: var(--space-2);
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text) 13%, transparent);
}

.history-loading-line--long { width: 88%; }
.history-loading-line--medium { width: 64%; }
.history-loading-line--short { width: 38%; }

@keyframes history-loading-shimmer {
  to { transform: translateX(100%); }
}

@media (prefers-reduced-motion: reduce) {
  .history-loading-bubble::after {
    animation: none;
    opacity: 0;
  }
}
</style>

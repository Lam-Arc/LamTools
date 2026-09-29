<template>
  <button
    ref="buttonElement"
    class="core-send-stop-button"
    :class="{ 'core-send-stop-button--stop': visualMode === 'stop' }"
    :data-state="visualMode"
    type="submit"
    :disabled="disabled"
    :title="actionMode === 'stop' ? stopTitle : sendTitle"
    :aria-label="actionMode === 'stop' ? stopTitle : sendTitle"
    :aria-pressed="visualMode === 'stop'"
    @pointermove="handlePointerMove"
    @pointerleave="handlePointerLeave"
  >
    <span class="core-send-stop-button__label" aria-hidden="true">
      {{ actionMode === 'stop' ? stopLabel : sendLabel }}
    </span>
  </button>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { gsap } from 'gsap'

type ActionMode = 'send' | 'stop'

const props = withDefaults(defineProps<{
  actionMode?: ActionMode
  disabled?: boolean
  sendLabel?: string
  stopLabel?: string
  sendTitle?: string
  stopTitle?: string
}>(), {
  actionMode: 'send',
  disabled: false,
  sendLabel: 'send',
  stopLabel: 'stop',
  sendTitle: '发送',
  stopTitle: '停止运行',
})

const buttonElement = ref<HTMLButtonElement | null>(null)
const visualMode = ref<ActionMode>(props.actionMode)
let mounted = false
let busy = false
let transitionTarget: ActionMode | null = null
let activeTimeline: gsap.core.Timeline | null = null
let animationContext: gsap.Context | null = null
let xTo: ((value: number) => gsap.core.Tween) | null = null
let yTo: ((value: number) => gsap.core.Tween) | null = null
let rotationTo: ((value: number) => gsap.core.Tween) | null = null

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

function setVisualMode(mode: ActionMode) {
  visualMode.value = mode
}

function settleButton(timeline: gsap.core.Timeline, position: number) {
  timeline
    .to(buttonElement.value, {
      scaleX: 0.94,
      scaleY: 1.07,
      duration: 0.09,
      ease: 'power2.out',
    }, position)
    .to(buttonElement.value, {
      scaleX: 1.025,
      scaleY: 0.985,
      duration: 0.11,
      ease: 'power2.inOut',
    })
    .to(buttonElement.value, {
      scaleX: 1,
      scaleY: 1,
      duration: 0.14,
      ease: 'expo.out',
    })
}

function finishTransition() {
  busy = false
  transitionTarget = null
  activeTimeline = null
}

function animateTo(mode: ActionMode) {
  const button = buttonElement.value
  if (!button) {
    setVisualMode(mode)
    return
  }

  transitionTarget = mode
  activeTimeline?.kill()
  activeTimeline = null

  if (prefersReducedMotion()) {
    setVisualMode(mode)
    gsap.set(button, {
      '--glyph-x': '0px',
      '--glyph-y': '0px',
      '--glyph-scale-x': 1,
      '--glyph-scale-y': 1,
      '--glyph-rotate': '0deg',
      '--glyph-opacity': 1,
      '--trail-scale': 0,
      '--trail-opacity': 0,
      clearProps: 'scale,scaleX,scaleY',
    })
    finishTransition()
    return
  }

  busy = true
  const timeline = gsap.timeline({
    defaults: { overwrite: 'auto' },
    onComplete: finishTransition,
  })
  activeTimeline = timeline

  if (mode === 'stop') {
    timeline
      .to(button, {
        scaleX: 1.1,
        scaleY: 0.86,
        duration: 0.085,
        ease: 'power2.in',
      })
      .to(button, {
        '--glyph-x': '15px',
        '--glyph-y': '-24px',
        '--glyph-scale-x': 0.72,
        '--glyph-scale-y': 1.25,
        '--glyph-rotate': '12deg',
        '--glyph-opacity': 0,
        '--trail-scale': 1,
        '--trail-opacity': 0.58,
        duration: 0.16,
        ease: 'power3.in',
      }, 0.045)
      .call(() => {
        setVisualMode('stop')
        gsap.set(button, {
          '--glyph-x': '0px',
          '--glyph-y': '8px',
          '--glyph-scale-x': 0.5,
          '--glyph-scale-y': 0.5,
          '--glyph-rotate': '0deg',
          '--glyph-opacity': 0,
          '--trail-scale': 0,
          '--trail-opacity': 0,
        })
      }, [], 0.205)
      .to(button, {
        '--glyph-y': '0px',
        '--glyph-scale-x': 1,
        '--glyph-scale-y': 1,
        '--glyph-opacity': 1,
        duration: 0.13,
        ease: 'expo.out',
      }, 0.205)
    settleButton(timeline, 0.205)
    return
  }

  timeline
    .to(button, {
      scaleX: 1.08,
      scaleY: 0.88,
      '--glyph-scale-x': 0.68,
      '--glyph-scale-y': 0.68,
      duration: 0.09,
      ease: 'power2.in',
    })
    .to(button, {
      '--glyph-opacity': 0,
      '--glyph-rotate': '-9deg',
      duration: 0.07,
      ease: 'power2.in',
    }, 0.055)
    .call(() => {
      setVisualMode('send')
      gsap.set(button, {
        '--glyph-x': '-8px',
        '--glyph-y': '7px',
        '--glyph-scale-x': 0.55,
        '--glyph-scale-y': 0.55,
        '--glyph-rotate': '-18deg',
        '--glyph-opacity': 0,
        '--trail-scale': 0,
        '--trail-opacity': 0,
      })
    }, [], 0.125)
    .to(button, {
      '--glyph-x': '0px',
      '--glyph-y': '0px',
      '--glyph-scale-x': 1,
      '--glyph-scale-y': 1,
      '--glyph-rotate': '0deg',
      '--glyph-opacity': 1,
      duration: 0.15,
      ease: 'expo.out',
    }, 0.125)
  settleButton(timeline, 0.125)
}

function handlePointerMove(event: PointerEvent) {
  if (prefersReducedMotion() || props.disabled || busy || event.pointerType === 'touch') return
  const button = buttonElement.value
  if (!button || !xTo || !yTo || !rotationTo) return
  const bounds = button.getBoundingClientRect()
  const dx = (event.clientX - bounds.left) / bounds.width - 0.5
  const dy = (event.clientY - bounds.top) / bounds.height - 0.5
  xTo(dx * 5)
  yTo(dy * 5)
  rotationTo(dx * 2.5)
}

function handlePointerLeave() {
  xTo?.(0)
  yTo?.(0)
  rotationTo?.(0)
}

watch(
  () => props.actionMode,
  (mode) => {
    if (!mounted) {
      setVisualMode(mode)
      return
    }
    if (mode === visualMode.value && !activeTimeline) return
    if (mode === visualMode.value && activeTimeline && transitionTarget !== mode) {
      activeTimeline.kill()
      activeTimeline = null
      busy = false
      transitionTarget = null
      return
    }
    animateTo(mode)
  },
)

onMounted(() => {
  const button = buttonElement.value
  if (!button) return
  mounted = true
  animationContext = gsap.context(() => {
    xTo = gsap.quickTo(button, 'x', { duration: 0.24, ease: 'power3.out' })
    yTo = gsap.quickTo(button, 'y', { duration: 0.24, ease: 'power3.out' })
    rotationTo = gsap.quickTo(button, 'rotation', { duration: 0.24, ease: 'power3.out' })
  }, button)
})

onUnmounted(() => {
  activeTimeline?.kill()
  animationContext?.revert()
  xTo = null
  yTo = null
  rotationTo = null
  mounted = false
})
</script>

<style scoped>
.core-send-stop-button {
  --glyph-x: 0px;
  --glyph-y: 0px;
  --glyph-scale-x: 1;
  --glyph-scale-y: 1;
  --glyph-rotate: 0deg;
  --glyph-opacity: 1;
  --trail-x: -7.2px;
  --trail-scale: 0;
  --trail-opacity: 0;
  position: relative;
  /* 80% of the previous 28px; glyph and trail scale with it. */
  width: 22.4px;
  height: 22.4px;
  min-width: 22.4px;
  padding: 0;
  border: 0;
  border-radius: 999px;
  display: grid;
  place-items: center;
  flex: 0 0 22.4px;
  background: var(--theme-composer-text);
  box-shadow: var(--shadow-sm);
  font-size: 0;
  line-height: 0;
  cursor: pointer;
  isolation: isolate;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
  will-change: transform;
}

.core-send-stop-button::before,
.core-send-stop-button::after {
  position: absolute;
  top: 50%;
  left: 50%;
  content: '';
  pointer-events: none;
}

.core-send-stop-button::before {
  width: 10.4px;
  height: 10.4px;
  background: var(--theme-composer-background);
  clip-path: polygon(4% 45%, 94% 7%, 68% 95%, 48% 62%, 31% 79%, 31% 57%);
  opacity: var(--glyph-opacity);
  transform: translate(calc(-50% + var(--glyph-x)), calc(-50% + var(--glyph-y)))
    rotate(var(--glyph-rotate)) scale(var(--glyph-scale-x), var(--glyph-scale-y));
  transform-origin: 50% 55%;
  will-change: transform, opacity;
}

.core-send-stop-button::after {
  z-index: -1;
  width: 14.4px;
  height: 4px;
  border-radius: 999px;
  background: var(--theme-composer-background);
  opacity: var(--trail-opacity);
  filter: blur(3px);
  transform: translate(calc(-50% + var(--trail-x)), -50%) scaleX(var(--trail-scale));
  transform-origin: right center;
  will-change: transform, opacity;
}

.core-send-stop-button--stop {
  background: var(--theme-composer-text);
  border-radius: var(--radius-sm);
}

.core-send-stop-button--stop:hover:not(:disabled),
.core-send-stop-button--stop:active:not(:disabled) {
  background: var(--theme-composer-text);
}

.core-send-stop-button--stop::before {
  width: 8.8px;
  height: 8.8px;
  border-radius: var(--space-1);
  clip-path: inset(0 round var(--space-1));
}

.core-send-stop-button:hover:not(:disabled) {
  filter: brightness(.96);
}

.core-send-stop-button:active:not(:disabled) {
  filter: brightness(.92);
}

.core-send-stop-button:disabled {
  opacity: .38;
  cursor: default;
}

.core-send-stop-button:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--theme-composer-text) 72%, transparent);
  outline-offset: var(--space-1);
}

.core-send-stop-button__label {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (prefers-reduced-motion: reduce) {
  .core-send-stop-button {
    will-change: auto;
  }
}

@media (pointer: coarse) {
  /* Touch keeps the 44px minimum target; only the pointer-driven size follows
     the 80% reduction. */
  .core-send-stop-button {
    width: 44px;
    height: 44px;
    min-width: 44px;
    flex-basis: 44px;
  }

  .core-send-stop-button::before {
    width: 17px;
    height: 17px;
  }

  .core-send-stop-button--stop::before {
    width: 14px;
    height: 14px;
  }
}
</style>

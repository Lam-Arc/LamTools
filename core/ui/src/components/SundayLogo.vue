<template>
  <span
    ref="rootEl"
    class="sunday-logo"
    :class="{ 'sunday-logo--surface': surface, 'sunday-logo--animated': animated }"
    :style="{ '--sunday-logo-size': `${size}px` }"
    :role="decorative ? undefined : 'img'"
    :aria-label="decorative ? undefined : label"
    :aria-hidden="decorative ? 'true' : undefined"
  >
    <svg ref="markEl" viewBox="0 0 1254 1254" fill="none" focusable="false">
      <defs>
        <linearGradient :id="warmId" x1="240" y1="608" x2="445" y2="243" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#FD4754"/><stop offset=".25" stop-color="#FC614A"/><stop offset=".5" stop-color="#FD843E"/><stop offset=".75" stop-color="#FDAB36"/><stop offset="1" stop-color="#FECA30"/>
        </linearGradient>
        <linearGradient :id="sweepId" x1="80" y1="645" x2="971" y2="1160" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#10AEFD"/><stop offset=".25" stop-color="#1690FC"/><stop offset=".5" stop-color="#1C6BFC"/><stop offset=".75" stop-color="#3B53FB"/><stop offset="1" stop-color="#823CFC"/>
        </linearGradient>
        <linearGradient :id="archId" x1="717" y1="492" x2="1078" y2="266" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#0453FD"/><stop offset=".25" stop-color="#3055FC"/><stop offset=".5" stop-color="#695BFB"/><stop offset=".75" stop-color="#9F55FB"/><stop offset="1" stop-color="#C745FD"/>
        </linearGradient>
      </defs>
      <ellipse ref="warmEl" cx="380.5" cy="447" rx="215.5" ry="212.5" :fill="`url(#${warmId})`"/>
      <path ref="archEl" :fill="`url(#${archId})`" d="M1172 440c-4-20-13-37-25-50-28-32-74-56-128-69-57-14-114-4-151 13-34 15-62 33-89 58-25 23-46 50-58 78-11 26-1 51 19 65 18 13 42 13 60 3 17-9 27-25 43-41 29-28 68-37 107-36 47 0 84 21 119 59 17 17 43 15 60 6 30-16 50-47 43-86Z"/>
      <path ref="sweepEl" :fill="`url(#${sweepId})`" d="M1209 700c-3-22-12-38-26-47-19-13-41-10-61-3-32 12-53 34-75 56-34 37-62 67-96 97-49 43-112 73-183 95-58 18-114 22-172 17-48-4-95-16-139-31-58-20-102-47-144-85-43-38-80-83-117-120-19-19-44-30-67-33-27-4-51 7-65 28-16 24-13 54-3 84 15 45 40 90 69 127 46 58 90 99 141 135 55 38 115 63 179 82 96 28 200 30 303 11 77-14 143-43 195-72 57-32 102-70 144-116 38-42 61-79 80-112 24-42 42-84 37-113Z"/>
    </svg>
  </span>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref, useId } from 'vue'
import { gsap } from 'gsap'

const props = withDefaults(defineProps<{
  size?: number
  surface?: boolean
  animated?: boolean
  decorative?: boolean
  label?: string
}>(), {
  size: 96,
  surface: false,
  animated: false,
  decorative: false,
  label: 'Sunday',
})

const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const warmId = `sunday-warm-${uid}`
const sweepId = `sunday-sweep-${uid}`
const archId = `sunday-arch-${uid}`
const rootEl = ref<HTMLElement | null>(null)
const markEl = ref<SVGSVGElement | null>(null)
const warmEl = ref<SVGElement | null>(null)
const archEl = ref<SVGElement | null>(null)
const sweepEl = ref<SVGElement | null>(null)
let motionMedia: gsap.MatchMedia | null = null

onMounted(() => {
  if (!props.animated || !rootEl.value || !markEl.value) return
  const root = rootEl.value
  const mark = markEl.value
  motionMedia = gsap.matchMedia()
  motionMedia.add('(prefers-reduced-motion: no-preference)', () => {
    const intro = gsap.timeline({ defaults: { ease: 'power4.out' } })
      .fromTo(mark, {
        autoAlpha: 0,
        y: 9,
        scaleX: .91,
        scaleY: 1.08,
        rotation: -1.5,
        transformOrigin: '50% 58%',
      }, {
        autoAlpha: 1,
        y: 0,
        scaleX: 1.045,
        scaleY: .965,
        rotation: .45,
        duration: .38,
      })
      .to(mark, { scaleX: 1, scaleY: 1, rotation: 0, duration: .3, ease: 'power3.out' })

    const breathe = gsap.timeline({ repeat: -1, yoyo: true, defaults: { ease: 'sine.inOut' } })
      .to(mark, { y: -2, scaleX: 1.012, scaleY: .99, duration: 2.8 }, 0)
      .to(warmEl.value, { y: -5, scale: 1.025, transformOrigin: '50% 50%', duration: 3.15 }, 0)
      .to(archEl.value, { y: 2, rotation: .7, transformOrigin: '50% 50%', duration: 3.35 }, 0)
      .to(sweepEl.value, { scaleX: 1.008, scaleY: .994, transformOrigin: '50% 55%', duration: 3.05 }, 0)

    const xTo = gsap.quickTo(root, 'x', { duration: .5, ease: 'power3.out' })
    const yTo = gsap.quickTo(root, 'y', { duration: .5, ease: 'power3.out' })
    const rotateTo = gsap.quickTo(root, 'rotation', { duration: .55, ease: 'power3.out' })
    const dotXTo = gsap.quickTo(warmEl.value, 'x', { duration: .62, ease: 'power3.out' })

    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      const rect = root.getBoundingClientRect()
      const nx = ((event.clientX - rect.left) / rect.width - .5) * 2
      const ny = ((event.clientY - rect.top) / rect.height - .5) * 2
      xTo(nx * 4)
      yTo(ny * 3)
      rotateTo(nx * 1.4)
      dotXTo(nx * -3)
    }
    const handlePointerLeave = () => {
      xTo(0)
      yTo(0)
      rotateTo(0)
      dotXTo(0)
    }
    root.addEventListener('pointermove', handlePointerMove)
    root.addEventListener('pointerleave', handlePointerLeave)

    return () => {
      root.removeEventListener('pointermove', handlePointerMove)
      root.removeEventListener('pointerleave', handlePointerLeave)
      intro.kill()
      breathe.kill()
    }
  }, root)
})

onUnmounted(() => {
  motionMedia?.revert()
  motionMedia = null
})
</script>

<style scoped>
.sunday-logo {
  width: var(--sunday-logo-size);
  height: var(--sunday-logo-size);
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
}

.sunday-logo > svg {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

.sunday-logo--surface {
  box-sizing: border-box;
  padding: 1px;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent);
  border-radius: var(--radius-sm);
  background: linear-gradient(145deg, #ffffff 0%, #fffdf8 58%, #f8f2f8 100%);
  box-shadow: 0 2px 6px rgb(23 36 81 / 12%);
}

.sunday-logo--animated > svg {
  will-change: transform, opacity;
}

.sunday-logo--animated {
  will-change: transform;
}

@media (prefers-reduced-motion: reduce) {
  .sunday-logo--animated,
  .sunday-logo--animated > svg { will-change: auto; }
}
</style>

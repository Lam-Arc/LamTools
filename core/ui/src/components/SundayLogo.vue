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
    <img
      v-if="surface"
      class="sunday-logo__app-icon"
      :src="surfaceTheme === 'light' ? appIconLightUrl : appIconDarkUrl"
      alt=""
      draggable="false"
    />
    <svg v-else ref="markEl" viewBox="0 0 1024 1024" fill="none" focusable="false">
      <ellipse ref="eyeEl" cx="367.5" cy="421.7" rx="64.1" ry="63.7" fill="currentColor"/>
      <path ref="winkEl" d="M599.8 442.4C647.1 408.3 694.7 405.8 726.3 435.3" fill="none" stroke="currentColor" stroke-width="45.7" stroke-linecap="round"/>
      <path ref="smileEl" d="M318.1 581.4C410.9 697.3 603.9 694.6 703.4 582.6" fill="none" stroke="currentColor" stroke-width="58" stroke-linecap="round"/>
    </svg>
  </span>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { gsap } from 'gsap'
import appIconDarkUrl from '../assets/sunday-app-icon-dark-display.png'
import appIconLightUrl from '../assets/sunday-app-icon-light-display.png'

const props = withDefaults(defineProps<{
  size?: number
  surface?: boolean
  surfaceTheme?: 'light' | 'dark'
  animated?: boolean
  decorative?: boolean
  label?: string
}>(), {
  size: 96,
  surface: false,
  surfaceTheme: 'dark',
  animated: false,
  decorative: false,
  label: 'Sunday',
})

const rootEl = ref<HTMLElement | null>(null)
const markEl = ref<SVGSVGElement | null>(null)
const eyeEl = ref<SVGElement | null>(null)
const winkEl = ref<SVGElement | null>(null)
const smileEl = ref<SVGElement | null>(null)
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
      .to(eyeEl.value, { y: -5, scale: 1.025, transformOrigin: '50% 50%', duration: 3.15 }, 0)
      .to(winkEl.value, { y: 2, rotation: .7, transformOrigin: '50% 50%', duration: 3.35 }, 0)
      .to(smileEl.value, { scaleX: 1.008, scaleY: .994, transformOrigin: '50% 55%', duration: 3.05 }, 0)

    const xTo = gsap.quickTo(root, 'x', { duration: .5, ease: 'power3.out' })
    const yTo = gsap.quickTo(root, 'y', { duration: .5, ease: 'power3.out' })
    const rotateTo = gsap.quickTo(root, 'rotation', { duration: .55, ease: 'power3.out' })
    const eyeXTo = gsap.quickTo(eyeEl.value, 'x', { duration: .62, ease: 'power3.out' })

    const handlePointerMove = (event: PointerEvent) => {
      if (event.pointerType === 'touch') return
      const rect = root.getBoundingClientRect()
      const nx = ((event.clientX - rect.left) / rect.width - .5) * 2
      const ny = ((event.clientY - rect.top) / rect.height - .5) * 2
      xTo(nx * 4)
      yTo(ny * 3)
      rotateTo(nx * 1.4)
      eyeXTo(nx * -3)
    }
    const handlePointerLeave = () => {
      xTo(0)
      yTo(0)
      rotateTo(0)
      eyeXTo(0)
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

.sunday-logo > svg,
.sunday-logo__app-icon {
  width: 100%;
  height: 100%;
  display: block;
}

.sunday-logo > svg {
  overflow: visible;
}

.sunday-logo__app-icon {
  object-fit: contain;
  user-select: none;
}

.sunday-logo--surface {
  color: inherit;
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

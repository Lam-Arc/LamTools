<template>
  <div
    ref="rootEl"
    class="sunday-thinking-slider"
    :class="{ 'is-dragging': dragging, 'is-disabled': isDisabled }"
  >
    <div
      ref="bodyEl"
      class="sunday-thinking-slider__body"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <div
        ref="railEl"
        class="sunday-thinking-slider__rail"
        role="slider"
        :tabindex="isDisabled ? -1 : 0"
        aria-orientation="vertical"
        :aria-label="label"
        :aria-valuemin="0"
        :aria-valuemax="Math.max(0, levels.length - 1)"
        :aria-valuenow="selectedIndex"
        :aria-valuetext="selectedLabel"
        :aria-disabled="isDisabled ? 'true' : undefined"
        data-core-thinking-slider
        @keydown="onRailKeydown"
      >
        <span class="sunday-thinking-slider__track" aria-hidden="true">
          <span
            ref="fillEl"
            class="sunday-thinking-slider__fill"
            aria-hidden="true"
            :style="fillStyle"
          />

          <!-- user:“刻度点应该在条内用白灰点表示”+(刻度点收进轨道，点击仍可直接跳到该等级)。 -->
          <!-- user:“白条换成白点吧，越向下越透明，然后消散”+(只在 max 档出现的轨道内下落白点)。 -->
          <div v-if="isMax" class="sunday-thinking-slider__max-dots" aria-hidden="true">
            <span v-for="dot in 6" :key="dot" class="sunday-thinking-slider__max-dot" />
          </div>

          <div class="sunday-thinking-slider__ticks" :class="{ 'is-single': levels.length <= 1 }">
            <button
              v-for="(level, visualIndex) in levelsTopDown"
              :key="level.value"
              class="sunday-thinking-slider__tick"
              :class="{ 'is-active': visualIndex === activeVisualIndex }"
              type="button"
              tabindex="-1"
              aria-hidden="true"
              :disabled="isDisabled"
              :data-model-thinking-level-option="level.value"
              @click="setLevel(levelIndexForVisual(visualIndex))"
            >
              <span class="sunday-thinking-slider__tick-dot" aria-hidden="true" />
            </button>
          </div>
        </span>
        <span ref="thumbEl" class="sunday-thinking-slider__thumb" aria-hidden="true" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  thinkingLevelColor,
  thinkingRank,
} from '@/composer/thinkingPalette.ts'

defineOptions({ name: 'ThinkingIntensitySlider' })

const props = withDefaults(defineProps<{
  modelValue: string
  options: Array<{ value: string; label: string }>
  label: string
  disabled?: boolean
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const KNOB_SIZE = 32
const MAGNET_WINDOW = 0.14
const MAGNET_STRENGTH = 0.62

const rootEl = ref<HTMLElement | null>(null)
const bodyEl = ref<HTMLElement | null>(null)
const railEl = ref<HTMLElement | null>(null)
const thumbEl = ref<HTMLElement | null>(null)
const fillEl = ref<HTMLElement | null>(null)

const levels = computed(() => [...props.options].sort(
  (left, right) => thinkingRank(left.value) - thinkingRank(right.value),
))
const levelsTopDown = computed(() => [...levels.value].reverse())
const levelColors = computed(() => levels.value.map((level) => thinkingLevelColor(level.value)))
const isDisabled = computed(() => props.disabled || levels.value.length <= 1)

const selectedIndex = ref(Math.max(
  0,
  levels.value.findIndex((level) => level.value === props.modelValue),
))
const selectedLabel = computed(() => (
  levels.value[selectedIndex.value]?.label ?? props.label
))
const activeVisualIndex = computed(() => (
  levels.value.length <= 1 ? 0 : levels.value.length - 1 - selectedIndex.value
))
const isMax = computed(() => thinkingRank(levels.value[selectedIndex.value]?.value ?? '') === 5)

const dragging = ref(false)
const railHeight = ref(0)
const displayPos = ref(0)
const targetPos = ref(0)

// user:“那个变色不是整个条都是渐变的”+(填充条只用当前等级的一个实色，不铺整条渐变)。
const activeColour = computed(() => levelColors.value[selectedIndex.value] ?? '#9aa0a8')
const fillStyle = computed(() => ({ background: activeColour.value }))

let velocity = 0
let frameId = 0
let lastFrame = 0
let resizeObserver: ResizeObserver | null = null

const motionQuery = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia('(prefers-reduced-motion: reduce)')
  : null
const reducedMotion = motionQuery?.matches ?? true
const canAnimate = !reducedMotion && typeof window.requestAnimationFrame === 'function'

function posForIndex(index: number): number {
  if (levels.value.length <= 1) return 0.5
  return Math.min(1, Math.max(0, index / (levels.value.length - 1)))
}

function indexForPos(position: number): number {
  if (levels.value.length <= 1) return 0
  return Math.round(Math.min(1, Math.max(0, position)) * (levels.value.length - 1))
}

function levelIndexForVisual(visualIndex: number): number {
  return Math.max(0, levels.value.length - 1 - visualIndex)
}

function syncFromProp(): void {
  const index = levels.value.findIndex((level) => level.value === props.modelValue)
  selectedIndex.value = index >= 0 ? index : 0
  // 拖拽中父级回传的新等级不能覆盖磁吸目标，否则吸附会在松手前被瞬间抹平。
  if (!dragging.value) targetPos.value = posForIndex(selectedIndex.value)
  if (railHeight.value <= 0 || !canAnimate) displayPos.value = targetPos.value
  if (canAnimate) ensureLoop()
}

function emitForIndex(index: number): void {
  const level = levels.value[index]
  if (!level || level.value === props.modelValue) return
  emit('update:modelValue', level.value)
}

function setLevel(index: number): void {
  if (isDisabled.value) return
  const next = Math.min(levels.value.length - 1, Math.max(0, index))
  selectedIndex.value = next
  targetPos.value = posForIndex(next)
  emitForIndex(next)
  if (!canAnimate || railHeight.value <= 0) {
    displayPos.value = targetPos.value
    render()
    return
  }
  ensureLoop()
}

function onRailKeydown(event: KeyboardEvent): void {
  if (isDisabled.value) return
  let next = selectedIndex.value
  if (event.key === 'ArrowUp' || event.key === 'ArrowRight') next += 1
  else if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') next -= 1
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = levels.value.length - 1
  else return
  event.preventDefault()
  setLevel(next)
}

function updateFromPointer(event: PointerEvent): void {
  const rail = railEl.value
  if (!rail || railHeight.value <= 0) return
  const rect = rail.getBoundingClientRect()
  const usable = Math.max(1, rect.height - KNOB_SIZE)
  const raw = 1 - ((event.clientY - rect.top) - KNOB_SIZE / 2) / usable
  const position = Math.min(1, Math.max(0, raw))
  const index = indexForPos(position)
  const tick = posForIndex(index)
  const distance = Math.abs(position - tick)
  const magnet = distance < MAGNET_WINDOW ? 1 - distance / MAGNET_WINDOW : 0
  targetPos.value = position + (tick - position) * magnet * MAGNET_STRENGTH
  if (index !== selectedIndex.value) {
    selectedIndex.value = index
    emitForIndex(index)
  }
  if (canAnimate) ensureLoop()
  else {
    displayPos.value = targetPos.value
    render()
  }
}

function onPointerDown(event: PointerEvent): void {
  if (isDisabled.value) return
  event.preventDefault()
  dragging.value = true
  bodyEl.value?.setPointerCapture?.(event.pointerId)
  railEl.value?.focus({ preventScroll: true })
  updateFromPointer(event)
}

function onPointerMove(event: PointerEvent): void {
  if (dragging.value) updateFromPointer(event)
}

function onPointerUp(event: PointerEvent): void {
  if (!dragging.value) return
  dragging.value = false
  bodyEl.value?.releasePointerCapture?.(event.pointerId)
  targetPos.value = posForIndex(selectedIndex.value)
  if (canAnimate) ensureLoop()
  else render()
}

function layout(): void {
  const rail = railEl.value
  if (!rail) return
  railHeight.value = rail.clientHeight
  render()
}

function render(): void {
  const rail = railEl.value
  const thumb = thumbEl.value
  const fill = fillEl.value
  if (!rail || !thumb || !fill || railHeight.value <= 0) return

  const usable = Math.max(1, railHeight.value - KNOB_SIZE)
  const centre = KNOB_SIZE / 2 + (1 - displayPos.value) * usable
  thumb.style.transform = `translateY(${centre - KNOB_SIZE / 2}px)`
  fill.style.height = `${Math.max(0, railHeight.value - centre)}px`
}

function ensureLoop(): void {
  if (!canAnimate || frameId) return
  lastFrame = performance.now()
  frameId = window.requestAnimationFrame(frame)
}

function frame(now: number): void {
  const dt = Math.min(0.05, Math.max(0.001, (now - lastFrame) / 1000))
  lastFrame = now
  const target = targetPos.value
  velocity += (target - displayPos.value) * 160 * dt
  velocity *= Math.exp(-20 * dt)
  displayPos.value += velocity * dt
  if (displayPos.value < 0) {
    displayPos.value = 0
    velocity = 0
  } else if (displayPos.value > 1) {
    displayPos.value = 1
    velocity = 0
  }
  if (Math.abs(target - displayPos.value) < 0.0004 && Math.abs(velocity) < 0.0004) {
    displayPos.value = target
    velocity = 0
  }
  render()
  frameId = window.requestAnimationFrame(frame)
}

function stopMotion(): void {
  if (frameId) window.cancelAnimationFrame(frameId)
  frameId = 0
  velocity = 0
}

onMounted(() => {
  syncFromProp()
  void nextTick(() => {
    layout()
    if (canAnimate && targetPos.value > 0) displayPos.value = 0
    else displayPos.value = targetPos.value
    render()
    if (canAnimate) ensureLoop()
  })
  if (typeof ResizeObserver !== 'undefined' && bodyEl.value) {
    resizeObserver = new ResizeObserver(() => layout())
    resizeObserver.observe(bodyEl.value)
  }
  window.addEventListener('resize', layout)
})

onBeforeUnmount(() => {
  stopMotion()
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', layout)
})

watch(
  () => props.modelValue,
  () => {
    syncFromProp()
    if (!canAnimate) render()
  },
)

watch(
  () => props.options.map((option) => option.value).join('|'),
  () => {
    syncFromProp()
    void nextTick(layout)
  },
)
</script>

<style scoped>
.sunday-thinking-slider {
  display: flex;
  flex-direction: column;
  min-height: 0;
  width: 100%;
  height: 100%;
  user-select: none;
}

.sunday-thinking-slider__body {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  justify-content: flex-end;
  padding: 4px 0;
  cursor: ns-resize;
  touch-action: none;
}

.sunday-thinking-slider.is-disabled .sunday-thinking-slider__body {
  cursor: default;
}

/* user:“托块调大至大于竖条宽度”+(26px 胶囊轨道，32px 圆球横向压过轨道，两端贴齐轨道端头)。 */
.sunday-thinking-slider__rail {
  position: relative;
  z-index: 1;
  width: 30px;
  height: 100%;
  min-height: 0;
  cursor: ns-resize;
  outline: none;
}

.sunday-thinking-slider.is-disabled .sunday-thinking-slider__rail {
  cursor: default;
}

.sunday-thinking-slider__rail:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 3px;
  border-radius: 999px;
}

/* user:“思考强度上下搞成圆形的”+(轨道上下端收成完整半圆，不再是 2px 小圆角)。 */
.sunday-thinking-slider__track {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 26px;
  overflow: hidden;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-composer-text) 7%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--theme-composer-text) 5%, transparent);
  transform: translateX(-50%);
}

/* user:“那个变色不是整个条都是渐变的”+(填充段是当前等级的一个实色，用短过渡换色)。 */
.sunday-thinking-slider__fill {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: 999px;
  transition: background-color var(--dur-base) var(--ease-out);
}

/* user:“不用做消散了，但是白点大小不一，大一点”+(白点匀速下落、保持不透明，大小明显不同，只在轨道内)。 */
.sunday-thinking-slider__max-dots {
  position: absolute;
  inset: 0;
  z-index: 1;
  pointer-events: none;
}

.sunday-thinking-slider__max-dot {
  position: absolute;
  top: -4%;
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: #fff;
  opacity: 0.68;
  animation: max-dot-fall 3s linear infinite;
  will-change: top;
}

.sunday-thinking-slider__max-dot:nth-child(1) {
  left: 16%;
  width: 3px;
  height: 3px;
  animation-duration: 2.6s;
  animation-delay: -0.4s;
}

.sunday-thinking-slider__max-dot:nth-child(2) {
  left: 30%;
  width: 4px;
  height: 4px;
  animation-duration: 3.4s;
  animation-delay: -2.1s;
}

.sunday-thinking-slider__max-dot:nth-child(3) {
  left: 46%;
  width: 3.5px;
  height: 3.5px;
  animation-duration: 2.9s;
  animation-delay: -1.3s;
}

.sunday-thinking-slider__max-dot:nth-child(4) {
  left: 62%;
  width: 5px;
  height: 5px;
  animation-duration: 3.7s;
  animation-delay: -3.2s;
}

.sunday-thinking-slider__max-dot:nth-child(5) {
  left: 78%;
  width: 4.5px;
  height: 4.5px;
  animation-duration: 2.7s;
  animation-delay: -1.8s;
}

.sunday-thinking-slider__max-dot:nth-child(6) {
  left: 90%;
  width: 3px;
  height: 3px;
  animation-duration: 3.2s;
  animation-delay: -2.6s;
}

@keyframes max-dot-fall {
  0% {
    top: -4%;
  }
  100% {
    top: 104%;
  }
}

/* user:“刻度点应该在条内用白灰点表示”+(轨道内均匀排布白灰节点，点击可直接选级)。 */
.sunday-thinking-slider__ticks {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  padding: 9px 0;
  pointer-events: none;
}

.sunday-thinking-slider__ticks.is-single {
  justify-content: center;
}

.sunday-thinking-slider__tick {
  display: grid;
  place-items: center;
  width: 14px;
  height: 14px;
  min-height: 14px;
  padding: 0;
  border: 0;
  background: transparent;
  pointer-events: auto;
  cursor: pointer;
}

.sunday-thinking-slider__tick:disabled {
  cursor: default;
}

.sunday-thinking-slider__tick-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #fbf7f0;
  box-shadow: 0 0 0 1px color-mix(in srgb, #000 16%, transparent);
  opacity: 0.82;
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-slow) cubic-bezier(0.34, 1.56, 0.64, 1);
}

.sunday-thinking-slider__tick:hover .sunday-thinking-slider__tick-dot,
.sunday-thinking-slider__tick.is-active .sunday-thinking-slider__tick-dot {
  opacity: 1;
  transform: scale(1.2);
}

/* user:“托块始终使用白底灰边”+(托块不跟随主题和等级换色，固定暖白球体加中灰描边)。 */
.sunday-thinking-slider__thumb {
  position: absolute;
  top: 0;
  left: 50%;
  z-index: 2;
  width: 32px;
  height: 32px;
  margin-left: -16px;
  border: 3px solid #9aa0a8;
  border-radius: 50%;
  background: #fbf7f0;
  box-shadow: 0 1px 4px color-mix(in srgb, #000 26%, transparent);
  pointer-events: none;
  will-change: transform;
  transition: box-shadow var(--dur-base) var(--ease-out);
}

.sunday-thinking-slider.is-dragging .sunday-thinking-slider__thumb {
  box-shadow: 0 2px 7px color-mix(in srgb, #000 32%, transparent);
}

.sunday-thinking-slider.is-disabled .sunday-thinking-slider__thumb {
  opacity: 0.55;
  box-shadow: none;
}

@media (prefers-reduced-motion: reduce) {
  .sunday-thinking-slider__tick-dot,
  .sunday-thinking-slider__fill,
  .sunday-thinking-slider__thumb {
    transition: none;
  }

  .sunday-thinking-slider__max-dots {
    display: none;
  }
}
</style>

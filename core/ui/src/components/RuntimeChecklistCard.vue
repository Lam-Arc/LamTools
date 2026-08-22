<template>
  <section
    v-if="currentStep"
    ref="rootEl"
    class="runtime-checklist-card"
    :data-status="currentStep.status"
    :class="{ 'is-expanded': expanded }"
    :role="expanded ? undefined : 'button'"
    :tabindex="expanded ? undefined : 0"
    :aria-expanded="expanded"
    :aria-controls="detailsId"
    aria-label="当前计划"
    @click="handleCardClick"
    @keydown="handleCardKeydown"
  >
    <div v-if="expanded" class="runtime-checklist-card__header">
      <div class="runtime-checklist-card__heading">
        <span class="runtime-checklist-card__eyebrow">当前计划</span>
        <span class="runtime-checklist-card__status" aria-live="polite">{{ statusLabel(currentStep.status) }}</span>
      </div>
      <button
        type="button"
        class="runtime-checklist-card__toggle"
        :aria-expanded="expanded"
        :aria-controls="detailsId"
        @click.stop="toggleExpanded"
        @keydown.stop="handleToggleKeydown"
      >收起计划</button>
    </div>

    <div v-if="!expanded" class="runtime-checklist-card__compact-row">
      <strong class="runtime-checklist-card__compact-title">第 {{ stepNumber(currentStep) }}：{{ currentStep.title }}</strong>
      <span class="runtime-checklist-card__status" aria-live="polite">{{ statusLabel(currentStep.status) }}</span>
    </div>

    <template v-if="expanded">
      <div v-if="previousCompletedStep" class="runtime-checklist-card__previous" data-status="completed">
        <span class="runtime-checklist-card__indicator" aria-hidden="true">✓</span>
        <span class="runtime-checklist-card__previous-title">第 {{ stepNumber(previousCompletedStep) }} 步：{{ previousCompletedStep.title }}</span>
        <span class="runtime-checklist-card__previous-status">已完成</span>
      </div>
    </template>

    <div v-if="expanded" class="runtime-checklist-card__current" :class="`is-${currentStep.status}`" :data-status="currentStep.status">
      <span
        class="runtime-checklist-card__indicator"
        :class="{ 'runtime-checklist-card__indicator--running': currentStep.status === 'running' }"
        aria-hidden="true"
      >{{ currentStep.status === 'completed' ? '✓' : currentStep.status === 'failed' ? '!' : '' }}</span>
      <div class="runtime-checklist-card__current-body">
        <strong class="runtime-checklist-card__current-title">第 {{ stepNumber(currentStep) }} 步：{{ currentStep.title }}</strong>
        <ul v-if="currentStep.deliverables?.length" class="runtime-checklist-card__deliverables">
          <li v-for="deliverable in currentStep.deliverables" :key="deliverable">{{ deliverable }}</li>
        </ul>
      </div>
      <span class="runtime-checklist-card__current-status">{{ statusLabel(currentStep.status) }}</span>
    </div>

    <Transition
      :css="false"
      @enter="detailsEnter"
      @leave="detailsLeave"
      @enter-cancelled="detailsCancelled"
      @leave-cancelled="detailsCancelled"
    >
      <div
        v-show="expanded"
        :id="detailsId"
        class="runtime-checklist-card__details"
        :aria-hidden="!expanded"
      >
      <section v-for="group in stepGroups" :key="group.id" class="runtime-checklist-card__group">
        <h3 class="runtime-checklist-card__group-title">{{ group.label }}</h3>
        <div
          v-for="step in group.steps"
          :key="step.id"
          class="runtime-checklist-card__step"
          :class="`is-${step.status}`"
          :data-status="step.status"
        >
          <span class="runtime-checklist-card__indicator" :class="{ 'runtime-checklist-card__indicator--running': step.status === 'running' }" aria-hidden="true">
            {{ step.status === 'completed' ? '✓' : '' }}
          </span>
          <div class="runtime-checklist-card__step-body">
            <span class="runtime-checklist-card__step-title">第 {{ stepNumber(step) }} 步：{{ step.title }}</span>
            <ul v-if="step.deliverables?.length" class="runtime-checklist-card__deliverables">
              <li v-for="deliverable in step.deliverables" :key="deliverable">{{ deliverable }}</li>
            </ul>
          </div>
          <span class="runtime-checklist-card__step-status">{{ statusLabel(step.status) }}</span>
        </div>
      </section>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, useId, watch } from 'vue'
import { gsap } from 'gsap'
import type { CoreRuntimeStep, CoreRuntimeStepGroup, CoreRuntimeStepStatus } from '../types'

const props = withDefaults(defineProps<{
  stepGroups?: CoreRuntimeStepGroup[]
}>(), {
  stepGroups: () => [],
})

const expanded = ref(false)
const rootEl = ref<HTMLElement | null>(null)
const detailsId = `runtime-checklist-details-${useId()}`
let gsapCtx: gsap.Context | null = null
let activeTween: gsap.core.Tween | null = null
let reducedMotion = false

function ensureGsapContext() {
  if (gsapCtx || !rootEl.value) return
  gsapCtx = gsap.context(() => {}, rootEl.value)
}

onUnmounted(() => {
  activeTween?.kill()
  activeTween = null
  gsapCtx?.revert()
  gsapCtx = null
})

const orderedSteps = computed(() => props.stepGroups.flatMap((group) => group.steps))
const currentStep = computed(() => {
  const currentId = props.stepGroups
    .map((group) => group.metadata?.current_step_id)
    .find((value): value is string => typeof value === 'string' && value.length > 0)
  if (currentId) {
    const targeted = orderedSteps.value.find((step) => step.id === currentId)
    if (targeted && ['running', 'failed'].includes(targeted.status)) return targeted
  }
  return [...orderedSteps.value].reverse().find((step) => step.status === 'running' || step.status === 'failed')
})
const currentStepIndex = computed(() => currentStep.value ? orderedSteps.value.indexOf(currentStep.value) : -1)

watch(currentStep, async (step) => {
  if (!step) {
    activeTween?.kill()
    activeTween = null
    gsapCtx?.revert()
    gsapCtx = null
    return
  }
  await nextTick()
  ensureGsapContext()
}, { flush: 'post', immediate: true })

const previousCompletedStep = computed<CoreRuntimeStep | undefined>(() => {
  for (let index = currentStepIndex.value - 1; index >= 0; index -= 1) {
    const step = orderedSteps.value[index]
    if (step?.status === 'completed') return step
  }
  return undefined
})

function animateDetails(target: Element, open: boolean, done: () => void) {
  const element = target as HTMLElement
  reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  if (reducedMotion || typeof requestAnimationFrame !== 'function') {
    done()
    return
  }
  ensureGsapContext()
  if (!gsapCtx) {
    done()
    return
  }
  activeTween?.kill()
  let finished = false
  const finish = () => {
    if (finished) return
    finished = true
    activeTween = null
    done()
  }
  gsapCtx.add(() => {
    activeTween = gsap.fromTo(
      element,
      open ? { autoAlpha: 0, y: -6 } : { autoAlpha: 1, y: 0 },
      {
        autoAlpha: open ? 1 : 0,
        y: open ? 0 : -6,
        duration: open ? 0.2 : 0.14,
        ease: 'power2.out',
        overwrite: true,
        clearProps: 'opacity,visibility,transform',
        onComplete: finish,
        onInterrupt: finish,
      },
    )
  })
}

function detailsEnter(element: Element, done: () => void) {
  animateDetails(element, true, done)
}

function detailsLeave(element: Element, done: () => void) {
  animateDetails(element, false, done)
}

function detailsCancelled() {
  activeTween?.kill()
  activeTween = null
}

function stepNumber(step: CoreRuntimeStep): number {
  return orderedSteps.value.findIndex((item) => item.id === step.id) + 1
}

function toggleExpanded() {
  expanded.value = !expanded.value
}

function handleCardClick() {
  if (!expanded.value) toggleExpanded()
}

function handleCardKeydown(event: KeyboardEvent) {
  if (expanded.value || (event.key !== 'Enter' && event.key !== ' ')) return
  event.preventDefault()
  toggleExpanded()
}

function handleToggleKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  toggleExpanded()
}

function statusLabel(status: CoreRuntimeStepStatus): string {
  return ({
    pending: '待处理',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
  } as Record<CoreRuntimeStepStatus, string>)[status]
}
</script>

<style scoped>
.runtime-checklist-card {
  --text: var(--theme-backdrop-text);
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  max-width: 100%;
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent);
  border-radius: var(--radius);
  background: var(--theme-backdrop-background);
  color: var(--text);
  box-shadow: var(--shadow-md);
}
.runtime-checklist-card.is-expanded {
  grid-template-rows: auto auto auto minmax(0, 1fr);
  height: min(
    520px,
    calc(100vh - var(--titlebar-offset, 0px) - 44px - 46px - 12px - 160px)
  );
  max-height: calc(100vh - var(--titlebar-offset, 0px) - 44px - 46px - 12px - 160px);
  overflow: hidden;
}

.runtime-checklist-card__header,
.runtime-checklist-card__heading,
.runtime-checklist-card__compact-row,
.runtime-checklist-card__previous,
.runtime-checklist-card__current,
.runtime-checklist-card__step {
  display: flex;
  align-items: center;
  min-width: 0;
}

.runtime-checklist-card__header {
  justify-content: space-between;
  gap: var(--space-2);
}

.runtime-checklist-card__compact-row {
  width: 100%;
  gap: var(--space-2);
  cursor: pointer;
  min-width: 0;
  white-space: nowrap;
}
.runtime-checklist-card__compact-title {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  line-height: 1.4;
}
.runtime-checklist-card__compact-row .runtime-checklist-card__status {
  flex: 0 0 auto;
}

.runtime-checklist-card__heading {
  gap: var(--space-2);
  min-width: 0;
}

.runtime-checklist-card__eyebrow {
  font-size: 12px;
  font-weight: 700;
}

.runtime-checklist-card__status,
.runtime-checklist-card__current-status {
  color: color-mix(in srgb, var(--green) 76%, var(--text) 24%);
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.runtime-checklist-card__toggle {
  flex-shrink: 0;
  white-space: nowrap;
  padding: var(--space-1) var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 16%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}

.runtime-checklist-card__toggle:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.runtime-checklist-card__toggle:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.runtime-checklist-card__toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 64%, transparent);
  outline-offset: 2px;
}

.runtime-checklist-card__previous,
.runtime-checklist-card__current,
.runtime-checklist-card__step {
  gap: var(--space-2);
  padding: var(--space-1) 0;
}

.runtime-checklist-card__previous {
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 12px;
}

.runtime-checklist-card__previous-title,
.runtime-checklist-card__current-title,
.runtime-checklist-card__step-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.runtime-checklist-card__previous-title {
  flex: 1;
  white-space: nowrap;
}

.runtime-checklist-card__previous-status {
  flex-shrink: 0;
  font-size: 11px;
}

.runtime-checklist-card__current {
  align-items: flex-start;
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--green) 28%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--green) 8%, var(--theme-backdrop-background));
}
.runtime-checklist-card__current.is-failed {
  border-color: color-mix(in srgb, var(--red) 42%, transparent);
  background: color-mix(in srgb, var(--red) 10%, var(--theme-backdrop-background));
}
.runtime-checklist-card__current.is-failed .runtime-checklist-card__current-title,
.runtime-checklist-card__current.is-failed .runtime-checklist-card__current-status {
  color: color-mix(in srgb, var(--red) 78%, var(--text) 22%);
}

.runtime-checklist-card__current-body,
.runtime-checklist-card__step-body {
  display: grid;
  flex: 1;
  gap: var(--space-1);
  min-width: 0;
}

.runtime-checklist-card__current-title {
  color: color-mix(in srgb, var(--green) 78%, var(--text) 22%);
  font-size: 13px;
  line-height: 1.4;
}

.runtime-checklist-card__indicator {
  display: inline-grid;
  flex: 0 0 16px;
  place-items: center;
  width: 16px;
  height: 16px;
  margin-top: 1px;
  border: 1px solid color-mix(in srgb, var(--text) 25%, transparent);
  border-radius: 50%;
  color: var(--green);
  font-size: 11px;
  line-height: 1;
}

.runtime-checklist-card__indicator--running {
  border-color: var(--green);
  animation: runtime-checklist-spin 1.2s linear infinite;
}
.runtime-checklist-card__current.is-failed .runtime-checklist-card__indicator {
  border-color: var(--red);
  color: var(--red);
}

.runtime-checklist-card__deliverables {
  display: grid;
  gap: 2px;
  margin: 0;
  padding: 0;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 11px;
  line-height: 1.35;
  list-style: none;
}

.runtime-checklist-card__deliverables li {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.runtime-checklist-card__deliverables li::before {
  content: '•';
  margin-right: var(--space-1);
  color: color-mix(in srgb, var(--green) 72%, var(--text) 28%);
}

.runtime-checklist-card__details {
  display: grid;
  gap: var(--space-3);
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 12%, transparent);
}

.runtime-checklist-card__group {
  display: grid;
  gap: var(--space-1);
}

.runtime-checklist-card__group-title {
  margin: 0 0 var(--space-1);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
}

.runtime-checklist-card__step {
  align-items: flex-start;
  color: color-mix(in srgb, var(--text) 72%, transparent);
  font-size: 12px;
}

.runtime-checklist-card__step.is-running {
  color: color-mix(in srgb, var(--green) 78%, var(--text) 22%);
}

.runtime-checklist-card__step.is-completed .runtime-checklist-card__indicator {
  border-color: color-mix(in srgb, var(--green) 56%, transparent);
}

.runtime-checklist-card__step-status {
  flex-shrink: 0;
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-size: 11px;
  white-space: nowrap;
}

.runtime-checklist-card__step.is-running .runtime-checklist-card__step-status {
  color: color-mix(in srgb, var(--green) 76%, var(--text) 24%);
}

@keyframes runtime-checklist-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 640px) {
  .runtime-checklist-card.is-expanded {
    height: min(60vh, 520px);
    max-height: calc(100vh - var(--titlebar-offset, 0px) - 58px - 160px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .runtime-checklist-card__indicator--running,
  .runtime-checklist-card__toggle {
    animation: none;
    transition-duration: 0.01ms;
  }
}
</style>

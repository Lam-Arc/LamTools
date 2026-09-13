<template>
  <section
    ref="moduleElement"
    class="right-sidebar-module"
    :class="{
      'right-sidebar-module--collapsed': collapsed,
      'right-sidebar-module--disabled': isDisabled,
      'right-sidebar-module--dragging': dragging,
      'right-sidebar-module--drag-over': dragOver,
    }"
    :data-module-id="module.id"
    :aria-busy="module.status === 'loading' || undefined"
    @dragover.prevent="$emit('dragover', $event)"
    @drop.prevent="$emit('drop', $event)"
  >
    <header class="right-sidebar-module-head">
      <button
        class="right-sidebar-module-drag-handle"
        type="button"
        draggable="true"
        :aria-label="`拖动 ${module.title} 模块排序`"
        title="拖动排序"
        @dragstart="$emit('dragstart', $event)"
        @dragend="$emit('dragend', $event)"
      >
        <GripVertical :size="14" :stroke-width="1.8" aria-hidden="true" />
      </button>
      <component
        :is="module.icon || Circle"
        class="right-sidebar-module-icon"
        :size="15"
        :stroke-width="1.8"
        aria-hidden="true"
      />
      <div class="right-sidebar-module-heading">
        <strong>{{ module.title }}</strong>
        <span v-if="module.description" class="right-sidebar-module-description">{{ module.description }}</span>
      </div>
      <span
        v-if="module.status && module.status !== 'ready'"
        class="right-sidebar-module-status"
        :data-status="module.status"
      >{{ statusLabel }}</span>
      <div class="right-sidebar-module-actions">
        <button
          v-if="showReorderControls"
          class="right-sidebar-module-move"
          type="button"
          :disabled="!canMoveUp"
          :aria-label="`上移 ${module.title}`"
          title="上移"
          @click="$emit('move', -1)"
        >
          <ArrowUp :size="13" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button
          v-if="showReorderControls"
          class="right-sidebar-module-move"
          type="button"
          :disabled="!canMoveDown"
          :aria-label="`下移 ${module.title}`"
          title="下移"
          @click="$emit('move', 1)"
        >
          <ArrowDown :size="13" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button
          class="right-sidebar-module-collapse"
          type="button"
          :aria-expanded="!collapsed"
          :aria-controls="bodyId"
          :aria-label="collapsed ? `展开 ${module.title}` : `折叠 ${module.title}`"
          :title="collapsed ? '展开' : '折叠'"
          @click="$emit('toggle-collapsed')"
        >
          <ChevronRight v-if="collapsed" :size="14" :stroke-width="1.8" aria-hidden="true" />
          <ChevronDown v-else :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
    </header>
    <Transition
      :css="false"
      @before-enter="beforeBodyEnter"
      @enter="enterBody"
      @leave="leaveBody"
      @before-leave="beforeBodyLeave"
      @enter-cancelled="cancelBodyMotion"
      @leave-cancelled="cancelBodyMotion"
    >
      <div
        v-show="!collapsed"
        :id="bodyId"
        class="right-sidebar-module-body"
        :inert="collapsed || isDisabled || undefined"
        :aria-hidden="collapsed || undefined"
      >
        <div class="right-sidebar-module-body-content">
          <div v-if="module.status === 'loading'" class="right-sidebar-module-state" role="status" aria-live="polite">正在加载…</div>
          <div v-else-if="module.status === 'error'" class="right-sidebar-module-state right-sidebar-module-state--error" role="alert">
            {{ module.error || '此模块暂不可用' }}
          </div>
          <div v-else-if="isDisabled" class="right-sidebar-module-state">{{ module.disabledReason || '此模块未启用' }}</div>
          <slot v-else />
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup lang="ts">
import { gsap } from 'gsap'
import { computed, onMounted, onUnmounted, ref, useId } from 'vue'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Circle, GripVertical } from 'lucide-vue-next'
import type { RightSidebarModuleDefinition } from '../right-sidebar/types'

const props = withDefaults(defineProps<{
  module: RightSidebarModuleDefinition
  collapsed?: boolean
  canMoveUp?: boolean
  canMoveDown?: boolean
  showReorderControls?: boolean
  dragging?: boolean
  dragOver?: boolean
}>(), {
  collapsed: false,
  canMoveUp: false,
  canMoveDown: false,
  showReorderControls: false,
  dragging: false,
  dragOver: false,
})

defineEmits<{
  'toggle-collapsed': []
  move: [direction: -1 | 1]
  dragstart: [event: DragEvent]
  dragend: [event: DragEvent]
  dragover: [event: DragEvent]
  drop: [event: DragEvent]
}>()

const bodyId = `right-sidebar-module-body-${useId()}`
const moduleElement = ref<HTMLElement | null>(null)
const isDisabled = computed(() => props.module.status === 'disabled')
const statusLabel = computed(() => {
  switch (props.module.status) {
    case 'loading': return '加载中'
    case 'error': return '不可用'
    case 'disabled': return '未启用'
    default: return ''
  }
})

let moduleMotionContext: gsap.Context | null = null
let bodyMotionTween: gsap.core.Tween | null = null
let bodyMotionRevision = 0

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function canAnimateBody(): boolean {
  return Boolean(moduleMotionContext)
    && typeof requestAnimationFrame === 'function'
    && !prefersReducedMotion()
}

function clearBodyMotion(target: HTMLElement): void {
  bodyMotionRevision += 1
  bodyMotionTween?.kill()
  bodyMotionTween = null
  gsap.set(target, { clearProps: 'gridTemplateRows,opacity,visibility,overflow,willChange' })
}

function beforeBodyEnter(el: Element): void {
  const target = el as HTMLElement
  clearBodyMotion(target)
  if (!canAnimateBody()) return
  moduleMotionContext?.add(() => {
    gsap.set(target, {
      gridTemplateRows: '0fr',
      autoAlpha: 0,
      overflow: 'hidden',
      willChange: 'grid-template-rows,opacity',
    })
  })
}

function beforeBodyLeave(el: Element): void {
  const target = el as HTMLElement
  clearBodyMotion(target)
  if (!canAnimateBody()) return
  moduleMotionContext?.add(() => {
    gsap.set(target, {
      gridTemplateRows: '1fr',
      autoAlpha: 1,
      overflow: 'hidden',
      willChange: 'grid-template-rows,opacity',
    })
  })
}

function runBodyMotion(
  el: Element,
  from: { gridTemplateRows: string; autoAlpha: number },
  to: { gridTemplateRows: string; autoAlpha: number },
  done: () => void,
): void {
  const target = el as HTMLElement
  bodyMotionTween?.kill()
  bodyMotionTween = null
  const revision = ++bodyMotionRevision
  if (!canAnimateBody()) {
    gsap.set(target, { ...to, clearProps: 'gridTemplateRows,opacity,visibility,overflow,willChange' })
    done()
    return
  }

  moduleMotionContext?.add(() => {
    bodyMotionTween = gsap.fromTo(target, from, {
      ...to,
      duration: 0.2,
      ease: 'power2.out',
      overwrite: 'auto',
      clearProps: 'gridTemplateRows,opacity,visibility,overflow,willChange',
      onComplete: () => {
        if (revision !== bodyMotionRevision) return
        bodyMotionTween = null
        done()
      },
    })
  })
}

function enterBody(el: Element, done: () => void): void {
  runBodyMotion(
    el,
    { gridTemplateRows: '0fr', autoAlpha: 0 },
    { gridTemplateRows: '1fr', autoAlpha: 1 },
    done,
  )
}

function leaveBody(el: Element, done: () => void): void {
  runBodyMotion(
    el,
    { gridTemplateRows: '1fr', autoAlpha: 1 },
    { gridTemplateRows: '0fr', autoAlpha: 0 },
    done,
  )
}

function cancelBodyMotion(el: Element): void {
  clearBodyMotion(el as HTMLElement)
}

onMounted(() => {
  if (moduleElement.value) {
    moduleMotionContext = gsap.context(() => {}, moduleElement.value)
  }
})

onUnmounted(() => {
  bodyMotionRevision += 1
  bodyMotionTween?.kill()
  bodyMotionTween = null
  moduleMotionContext?.revert()
  moduleMotionContext = null
})
</script>

<style scoped>
.right-sidebar-module {
  --module-text: var(--theme-backdrop-text);
  min-width: 0;
  border-bottom: 1px solid color-mix(in srgb, var(--module-text) 10%, transparent);
  color: var(--module-text);
  transition: background-color var(--dur-base) var(--ease-out), opacity var(--dur-base) var(--ease-out), box-shadow var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
}
.right-sidebar-module:first-child { border-top: 1px solid color-mix(in srgb, var(--module-text) 10%, transparent); }
.right-sidebar-module--drag-over {
  background: color-mix(in srgb, var(--module-text) var(--alpha-hover), transparent);
  box-shadow: inset 2px 0 0 color-mix(in srgb, var(--blue) 72%, transparent);
}
.right-sidebar-module--dragging {
  position: relative;
  z-index: 1;
  transform: translateY(-2px) scale(1.005);
  box-shadow: var(--shadow-sm);
  will-change: transform;
}
.right-sidebar-module--disabled { opacity: .62; }
.right-sidebar-module-head {
  min-height: 40px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
}
.right-sidebar-module-drag-handle,
.right-sidebar-module-move,
.right-sidebar-module-collapse {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  min-width: 28px;
  min-height: 28px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--module-text) 50%, transparent);
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.right-sidebar-module-drag-handle { cursor: grab; }
.right-sidebar-module-drag-handle:active { cursor: grabbing; }
.right-sidebar-module-drag-handle:hover,
.right-sidebar-module-move:hover:not(:disabled),
.right-sidebar-module-collapse:hover {
  background: color-mix(in srgb, var(--module-text) var(--alpha-hover), transparent);
  color: var(--module-text);
}
.right-sidebar-module-drag-handle:focus-visible,
.right-sidebar-module-move:focus-visible,
.right-sidebar-module-collapse:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent);
  outline-offset: 1px;
}
.right-sidebar-module-move:disabled { opacity: .26; cursor: default; }
.right-sidebar-module-icon { flex: 0 0 auto; color: color-mix(in srgb, var(--module-text) 66%, transparent); }
.right-sidebar-module-heading { min-width: 0; flex: 1 1 auto; display: grid; gap: 1px; }
.right-sidebar-module-heading strong { min-width: 0; overflow: hidden; font-size: 12px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.right-sidebar-module-description { overflow: hidden; color: color-mix(in srgb, var(--module-text) 48%, transparent); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.right-sidebar-module-status { flex: 0 0 auto; color: color-mix(in srgb, var(--module-text) 58%, transparent); font-size: 10px; }
.right-sidebar-module-status[data-status="error"] { color: color-mix(in srgb, var(--red) 72%, var(--module-text) 28%); }
.right-sidebar-module-status[data-status="loading"] { color: var(--blue); }
.right-sidebar-module-actions { display: inline-flex; align-items: center; gap: var(--space-1); flex: 0 0 auto; }
.right-sidebar-module-body { display: grid; grid-template-rows: 1fr; min-width: 0; overflow: visible; opacity: 1; }
.right-sidebar-module-body-content { min-width: 0; min-height: 0; padding: 0 var(--space-3) var(--space-3); overflow: visible; }
.right-sidebar-module-state { padding: var(--space-1) 0; color: color-mix(in srgb, var(--module-text) 56%, transparent); font-size: 12px; line-height: 1.45; }
.right-sidebar-module-state--error { color: color-mix(in srgb, var(--red) 70%, var(--module-text) 30%); }
@media (max-width: 640px) {
  .right-sidebar-module-head { min-height: 48px; padding-block: var(--space-1); }
  .right-sidebar-module-drag-handle,
  .right-sidebar-module-move,
  .right-sidebar-module-collapse { min-width: 44px; min-height: 44px; }
  .right-sidebar-module-drag-handle { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .right-sidebar-module,
  .right-sidebar-module-drag-handle,
  .right-sidebar-module-move,
  .right-sidebar-module-collapse { transition: none; }
  .right-sidebar-module--dragging { transform: none; will-change: auto; }
}
</style>

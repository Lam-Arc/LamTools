<template>
  <article
    class="wf-canvas-element"
    :class="[`kind-${element.kind}`, { 'is-collapsed': element.collapsed }]"
    :style="elementStyle"
    :aria-label="`${element.title || element.id}，${kindLabel}`"
    role="group"
    tabindex="0"
    @keydown.enter.prevent="startEditing"
    @dblclick="handleDoubleClick"
  >
    <template v-if="resizable">
      <button type="button" class="wf-resize-handle is-east nodrag nopan" aria-label="向右调整宽度" title="拖动调整宽度" @pointerdown.stop.prevent="startResize($event, 'east')" />
      <button type="button" class="wf-resize-handle is-south nodrag nopan" aria-label="向下调整高度" title="拖动调整高度" @pointerdown.stop.prevent="startResize($event, 'south')" />
      <button type="button" class="wf-resize-handle is-southeast nodrag nopan" aria-label="调整宽高" title="拖动调整宽高" @pointerdown.stop.prevent="startResize($event, 'southeast')" />
    </template>
    <template v-if="element.kind === 'reroute'">
      <span class="wf-reroute-dot" aria-hidden="true" />
      <span class="sr-only">{{ element.title || '中继' }}</span>
    </template>
    <template v-else>
      <header class="wf-decoration-head">
        <input
          v-model="localTitle"
          class="wf-decoration-title"
          type="text"
          :aria-label="`${kindLabel}标题`"
          @blur="pushUpdate"
          @keydown.stop
        />
        <span class="wf-decoration-kind" aria-hidden="true">{{ kindLabel }}</span>
      </header>
      <textarea
        v-model="localText"
        class="wf-decoration-text"
        :aria-label="`${kindLabel}内容`"
        :placeholder="placeholder"
        :readonly="!editing && element.kind !== 'note' && element.kind !== 'comment'"
        @blur="pushUpdate"
        @keydown.stop
      />
    </template>
  </article>
</template>

<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import type { WorkflowCanvasElement } from './canvas'

const props = defineProps<{
  data: { element: WorkflowCanvasElement }
  selected?: boolean
}>()

const element = computed(() => props.data.element)
const localTitle = ref(element.value.title)
const localText = ref(element.value.text)
const localWidth = ref(element.value.width)
const localHeight = ref(element.value.height)
const editing = ref(false)
const updateElement = inject<(id: string, patch: Partial<WorkflowCanvasElement>) => void>('wf-update-canvas-element', () => {})
const selectElementContents = inject<(id: string) => void>('wf-select-canvas-element-contents', () => {})
const isCanvasLocked = inject<() => boolean>('wf-canvas-locked', () => false)
const { viewport } = useVueFlow()
const resizable = computed(() => props.selected === true && element.value.kind !== 'reroute' && !isCanvasLocked())

const kindLabel = computed(() => {
  if (element.value.kind === 'group') return '分组'
  if (element.value.kind === 'frame') return '框架'
  if (element.value.kind === 'reroute') return '中继'
  if (element.value.kind === 'comment') return '注释'
  return '便签'
})
const placeholder = computed(() => element.value.kind === 'comment' ? '写下注释…' : '写下想法…')
const elementStyle = computed(() => ({
  width: `${localWidth.value}px`,
  height: `${localHeight.value}px`,
  ...(element.value.color ? { '--wf-decoration-color': element.value.color } : {}),
}))

watch(() => props.data.element, (next) => {
  localTitle.value = next.title
  localText.value = next.text
  localWidth.value = next.width
  localHeight.value = next.height
}, { deep: true })

type ResizeAxis = 'east' | 'south' | 'southeast'
let resizeState: { axis: ResizeAxis; x: number; y: number; width: number; height: number } | null = null

function startResize(event: PointerEvent, axis: ResizeAxis): void {
  if (!resizable.value) return
  resizeState = { axis, x: event.clientX, y: event.clientY, width: localWidth.value, height: localHeight.value }
  window.addEventListener('pointermove', resizeElement)
  window.addEventListener('pointerup', finishResize, { once: true })
}

function resizeElement(event: PointerEvent): void {
  if (!resizeState) return
  const zoom = Math.max(viewport.value.zoom || 1, 0.01)
  if (resizeState.axis !== 'south') localWidth.value = Math.max(120, Math.round(resizeState.width + (event.clientX - resizeState.x) / zoom))
  if (resizeState.axis !== 'east') localHeight.value = Math.max(80, Math.round(resizeState.height + (event.clientY - resizeState.y) / zoom))
}

function finishResize(): void {
  window.removeEventListener('pointermove', resizeElement)
  if (resizeState && (localWidth.value !== element.value.width || localHeight.value !== element.value.height)) {
    updateElement(element.value.id, { width: localWidth.value, height: localHeight.value })
  }
  resizeState = null
}

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', resizeElement)
  window.removeEventListener('pointerup', finishResize)
})

function handleDoubleClick(event: MouseEvent): void {
  if (element.value.kind === 'frame' || element.value.kind === 'group') {
    event.preventDefault()
    event.stopPropagation()
    selectElementContents(element.value.id)
    return
  }
  startEditing()
}

function startEditing(): void {
  if (element.value.kind !== 'reroute') editing.value = true
}

function pushUpdate(): void {
  if (localTitle.value !== element.value.title || localText.value !== element.value.text) {
    updateElement(element.value.id, { title: localTitle.value, text: localText.value })
  }
  editing.value = false
}
</script>

<style scoped>
.wf-canvas-element {
  position: relative;
  box-sizing: border-box;
  min-width: 20px;
  min-height: 20px;
  border: 1px solid color-mix(in srgb, var(--wf-decoration-color, var(--theme-main-text)) 30%, var(--theme-main-border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--wf-decoration-color, var(--theme-main-text)) 6%, var(--theme-main-background));
  color: var(--theme-main-text);
  box-shadow: var(--shadow-sm);
  outline: 0;
}
.wf-canvas-element:focus-visible { box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue) 70%, transparent), var(--shadow-sm); }
.wf-canvas-element.kind-group,
.wf-canvas-element.kind-frame { border-style: dashed; background: color-mix(in srgb, var(--wf-decoration-color, var(--blue)) 4%, transparent); box-shadow: none; }
.wf-canvas-element.kind-frame { border-width: 2px; }
.wf-canvas-element.kind-note { background: color-mix(in srgb, var(--yellow, #d59f27) 17%, var(--theme-main-background)); }
.wf-canvas-element.kind-comment { background: color-mix(in srgb, var(--purple) 10%, var(--theme-main-background)); }
.wf-canvas-element.kind-reroute { display: grid; place-items: center; border-radius: 50%; background: var(--theme-main-background); }
.wf-resize-handle {
  position: absolute;
  z-index: 2;
  border: 0;
  background: transparent;
  padding: 0;
}
.wf-resize-handle.is-east { top: var(--space-2); right: -4px; bottom: var(--space-2); width: 8px; cursor: ew-resize; }
.wf-resize-handle.is-south { right: var(--space-2); bottom: -4px; left: var(--space-2); height: 8px; cursor: ns-resize; }
.wf-resize-handle.is-southeast { right: -4px; bottom: -4px; width: 12px; height: 12px; cursor: nwse-resize; }
.wf-resize-handle.is-southeast::after {
  content: '';
  position: absolute;
  right: 3px;
  bottom: 3px;
  width: 4px;
  height: 4px;
  border-right: 1px solid color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}
.wf-reroute-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--wf-decoration-color, var(--blue)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--wf-decoration-color, var(--blue)) 18%, transparent); }
.wf-decoration-head { display: flex; align-items: center; gap: var(--space-1); min-height: 26px; padding: var(--space-1) var(--space-2); }
.wf-decoration-title { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: inherit; font-size: 11px; font-weight: 650; }
.wf-decoration-kind { flex: 0 0 auto; color: color-mix(in srgb, var(--theme-main-text) 52%, transparent); font-size: 9px; }
.wf-decoration-text { display: block; width: calc(100% - var(--space-3)); height: calc(100% - 34px); margin: 0 var(--space-2) var(--space-2); box-sizing: border-box; border: 0; outline: 0; resize: none; background: transparent; color: inherit; font: inherit; font-size: 11px; line-height: 1.45; }
.wf-decoration-text[readonly] { cursor: text; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) { .wf-canvas-element { transition: none; animation: none; } }
</style>

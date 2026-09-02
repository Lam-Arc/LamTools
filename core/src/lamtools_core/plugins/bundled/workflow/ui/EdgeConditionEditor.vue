<template>
  <section
    ref="rootEl"
    class="wf-edge-condition-editor"
    role="dialog"
    aria-label="编辑连线条件"
    :style="editorStyle"
    @pointerdown.stop
    @click.stop
    @keydown.esc.prevent="$emit('close')"
  >
    <header class="wf-edge-condition-head">
      <span>编辑连线条件</span>
      <button class="text-btn" type="button" aria-label="关闭" @click="$emit('close')">
        <X :size="14" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </header>

    <div class="wf-edge-condition-body">
      <label class="wf-edge-condition-field">
        <span>Python 表达式</span>
        <AutoTextarea
          v-model="draft"
          :min-rows="2"
          :max-rows="5"
          placeholder="例如：quality >= 0.8"
          @keydown.esc.prevent="$emit('close')"
          @keydown.ctrl.enter.prevent="apply"
          @keydown.meta.enter.prevent="apply"
        />
      </label>
      <p>空值表示无条件；表达式不满足时，下游会跳过。</p>
    </div>

    <footer class="wf-edge-condition-foot">
      <button class="small-btn" type="button" @click="$emit('close')">取消</button>
      <button class="small-btn primary" type="button" @click="apply">应用</button>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { X } from 'lucide-vue-next'
import AutoTextarea from '../../../../../../ui/src/components/AutoTextarea.vue'

const props = defineProps<{
  value: string
  anchor: { x: number; y: number }
}>()

const emit = defineEmits<{
  close: []
  save: [value: string]
}>()

const rootEl = ref<HTMLElement | null>(null)
const draft = ref(props.value)

const editorStyle = computed(() => {
  const width = 320
  const height = 220
  const margin = 12
  const viewportWidth = typeof window === 'undefined' ? width + margin * 2 : window.innerWidth
  const viewportHeight = typeof window === 'undefined' ? height + margin * 2 : window.innerHeight
  const maxLeft = Math.max(margin, viewportWidth - width - margin)
  const maxTop = Math.max(margin, viewportHeight - height - margin)
  return {
    left: `${Math.min(Math.max(props.anchor.x, margin), maxLeft)}px`,
    top: `${Math.min(Math.max(props.anchor.y, margin), maxTop)}px`,
  }
})

function apply(): void {
  emit('save', draft.value)
}

function closeOnOutsidePointerDown(event: PointerEvent): void {
  if (event.target instanceof Node && !rootEl.value?.contains(event.target)) emit('close')
}

onMounted(() => {
  document.addEventListener('pointerdown', closeOnOutsidePointerDown, true)
  void nextTick(() => rootEl.value?.querySelector<HTMLTextAreaElement>('textarea')?.focus())
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', closeOnOutsidePointerDown, true)
})
</script>

<style scoped>
.wf-edge-condition-editor {
  position: fixed;
  z-index: var(--z-popover, 60);
  width: 320px;
  max-width: calc(100vw - var(--space-4));
  box-sizing: border-box;
  overflow: hidden;
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-md);
}

.wf-edge-condition-head,
.wf-edge-condition-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.wf-edge-condition-head {
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--theme-main-border);
  font-size: 13px;
  font-weight: 650;
}

.wf-edge-condition-body {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
}

.wf-edge-condition-field {
  display: grid;
  gap: var(--space-1);
  font-size: 12px;
}

.wf-edge-condition-body p {
  margin: 0;
  color: color-mix(in srgb, var(--theme-main-text) 60%, transparent);
  font-size: 11px;
  line-height: 1.4;
}

.wf-edge-condition-foot {
  justify-content: flex-end;
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid var(--theme-main-border);
}

@media (prefers-reduced-motion: reduce) {
  .wf-edge-condition-editor {
    scroll-behavior: auto;
  }
}
</style>

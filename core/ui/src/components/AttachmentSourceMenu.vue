<template>
  <div ref="root" class="attachment-source" data-attachment-source>
    <button
      class="composer-attachment-button"
      type="button"
      title="添加附件"
      aria-label="添加附件"
      :aria-expanded="categorized ? open : undefined"
      :disabled="disabled"
      @click="handleTrigger"
    >
      <Paperclip :size="17" :stroke-width="1.9" aria-hidden="true" />
    </button>

    <div v-if="categorized && open" class="attachment-source__menu optical-glass" role="menu" aria-label="选择附件来源">
      <button type="button" role="menuitem" @click="select('file')">
        <FileUp :size="18" :stroke-width="1.8" aria-hidden="true" />
        <span><strong>文件</strong><small>从设备文件中选择</small></span>
      </button>
      <button type="button" role="menuitem" @click="select('photos')">
        <Image :size="18" :stroke-width="1.8" aria-hidden="true" />
        <span><strong>相册</strong><small>选择已有照片</small></span>
      </button>
      <button type="button" role="menuitem" @click="select('camera')">
        <Camera :size="18" :stroke-width="1.8" aria-hidden="true" />
        <span><strong>相机</strong><small>拍摄一张新照片</small></span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { Camera, FileUp, Image, Paperclip } from 'lucide-vue-next'
import type { RuntimeFileSource } from '../app/runtime'

const props = withDefaults(defineProps<{
  categorized?: boolean
  disabled?: boolean
}>(), {
  categorized: false,
  disabled: false,
})

const emit = defineEmits<{
  select: [source: RuntimeFileSource]
}>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)

function handleTrigger(): void {
  if (props.categorized) open.value = !open.value
  else emit('select', 'file')
}

function select(source: RuntimeFileSource): void {
  open.value = false
  emit('select', source)
}

function handlePointerDown(event: PointerEvent): void {
  if (event.target instanceof Node && root.value?.contains(event.target)) return
  open.value = false
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') open.value = false
}

onMounted(() => {
  document.addEventListener('pointerdown', handlePointerDown)
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('pointerdown', handlePointerDown)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.attachment-source {
  position: relative;
  flex: 0 0 auto;
}

.composer-attachment-button {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border-radius: var(--radius-sm);
  color: color-mix(in srgb, var(--theme-composer-text) 72%, transparent);
  transition: background var(--dur-base) var(--ease-out), color var(--dur-base) var(--ease-out);
  -webkit-tap-highlight-color: transparent;
}

.composer-attachment-button:hover:not(:disabled),
.composer-attachment-button[aria-expanded='true'] {
  background: var(--theme-composer-soft-background);
  color: var(--theme-composer-text);
}

.composer-attachment-button:disabled {
  cursor: not-allowed;
  opacity: .45;
}

.attachment-source__menu {
  --text: var(--theme-control-text);
  position: absolute;
  bottom: calc(100% + var(--space-2));
  left: 0;
  z-index: var(--z-popover);
  display: grid;
  width: min(236px, calc(100vw - var(--space-6)));
  padding: var(--space-1);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  color: var(--text);
}

.attachment-source__menu button {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  align-items: center;
  gap: var(--space-2);
  min-height: 50px;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  text-align: left;
  -webkit-tap-highlight-color: transparent;
}

.attachment-source__menu button:hover,
.attachment-source__menu button:focus-visible {
  background: color-mix(in srgb, var(--text) 8%, transparent);
}

.attachment-source__menu span,
.attachment-source__menu strong,
.attachment-source__menu small {
  display: block;
  min-width: 0;
}

.attachment-source__menu strong {
  font-size: 13px;
  font-weight: 650;
}

.attachment-source__menu small {
  margin-top: 2px;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: 11px;
}

@media (prefers-reduced-motion: reduce) {
  .composer-attachment-button { transition: none; }
}
</style>

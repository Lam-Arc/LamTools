<template>
  <div class="composer-root" :class="'composer-root--' + variant">
    <form
      class="floating-composer"
      :class="[{ dragover: dragOver }, 'composer-bar--' + variant]"
      @submit.prevent="$emit('submit')"
      @dragover.prevent="dragOver = true"
      @dragleave="dragOver = false"
      @drop.prevent="$emit('drop', $event); dragOver = false"
    >
      <div class="composer-ambient" :class="{ 'composer-ambient--on': active }" aria-hidden="true">
        <span v-for="i in 7" :key="i" class="composer-particle" :style="{ '--i': i - 1 }" />
      </div>
      <slot name="preamble" />
      <div class="composer-main-card">
        <slot name="status" />
        <slot name="textarea">
          <textarea
            :value="modelValue"
            :placeholder="placeholder"
            :aria-label="textareaAriaLabel || placeholder"
            :disabled="disabled"
            rows="1"
            @input="$emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
            @keydown.enter.exact="onEnterKey"
          />
        </slot>
        <div class="composer-bottom">
          <div class="tool-row">
            <slot name="attach-button" />
            <slot name="tools" />
          </div>
          <slot name="action">
            <button
              class="send"
              :class="{ 'send--stop': actionMode === 'stop' }"
              type="submit"
              :disabled="actionMode === 'send' && (disabled || !(modelValue || '').trim())"
              :title="actionMode === 'stop' ? stopTitle : sendTitle"
              :aria-label="actionMode === 'stop' ? stopTitle : sendTitle"
            >{{ actionMode === 'stop' ? stopLabel : sendLabel }}</button>
          </slot>
        </div>
      </div>
      <div class="drop-hint">拖拽到这里上传</div>
    </form>
    <slot name="extras" />
  </div>
</template>

<script setup lang="ts">
/**
 * ComposerBar — floating composer bar (composer layer in the four-layer system)
 *
 * Renders a floating or embedded textarea with toolbar and send button.
 * Drag-and-drop support via slots and events.
 */
import { ref } from 'vue'

withDefaults(defineProps<{
  modelValue?: string
  placeholder?: string
  textareaAriaLabel?: string
  disabled?: boolean
  actionMode?: 'send' | 'stop'
  variant?: 'floating' | 'embedded'
  sendLabel?: string
  stopLabel?: string
  sendTitle?: string
  stopTitle?: string
  /** 运行时：背景粒子浮动层亮起（仅运行时出现的动效） */
  active?: boolean
}>(), {
  modelValue: '',
  placeholder: '输入内容...',
  textareaAriaLabel: '',
  actionMode: 'send',
  variant: 'floating',
  sendLabel: 'send',
  stopLabel: 'stop',
  sendTitle: '发送',
  stopTitle: '停止运行',
  active: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  drop: [event: DragEvent]
}>()

const dragOver = ref(false)

// IME guard: the composition-confirm Enter must not submit the message
// (audit 19 S3 — the default textarea previously emitted submit on any
// plain Enter, which misfired for CJK users).
function onEnterKey(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  emit('submit')
}
</script>

<style scoped>
.composer-root--embedded {
  min-width: 0;
  width: 100%;
}

/* ── 背景粒子层：运行时亮起，粒子沿 y 轴浮动（stagger 100ms）── */
.composer-ambient {
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: 0;
  transition: opacity .3s ease;
  /* 上下边缘渐隐，粒子浮出边界时柔化消失，避免硬裁剪 */
  -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 22%, #000 78%, transparent 100%);
  mask-image: linear-gradient(180deg, transparent 0, #000 22%, #000 78%, transparent 100%);
}
.composer-ambient--on {
  opacity: 1;
}
.composer-ambient:not(.composer-ambient--on) .composer-particle {
  animation-play-state: paused;
}
.composer-particle {
  position: absolute;
  border-radius: 50%;
  background: color-mix(in srgb, var(--green) 10%, transparent);
  animation: composer-particle-float 3s ease-in-out infinite;
  animation-delay: calc(var(--i) * 100ms);
}
/* 7 个粒子：位置错落、大小不一 */
.composer-particle:nth-child(1) { left: 12%; top: 24%; width: 8px; height: 8px; }
.composer-particle:nth-child(2) { left: 27%; top: 72%; width: 5px; height: 5px; }
.composer-particle:nth-child(3) { left: 39%; top: 32%; width: 10px; height: 10px; }
.composer-particle:nth-child(4) { left: 53%; top: 64%; width: 7px; height: 7px; }
.composer-particle:nth-child(5) { left: 66%; top: 28%; width: 5px; height: 5px; }
.composer-particle:nth-child(6) { left: 78%; top: 68%; width: 8px; height: 8px; }
.composer-particle:nth-child(7) { left: 90%; top: 44%; width: 7px; height: 7px; }
@keyframes composer-particle-float {
  0%, 100% { transform: translateY(-50px); }
  50% { transform: translateY(50px); }
}
@media (prefers-reduced-motion: reduce) {
  .composer-particle {
    animation: none;
  }
}

.composer-root .floating-composer.composer-bar--embedded {
  position: relative;
  inset: auto;
  left: auto;
  bottom: auto;
  width: 100%;
  max-width: none;
  transform: none;
  z-index: auto;
  border-radius: var(--radius);
  box-shadow: none;
  transition: border-color 160ms cubic-bezier(.25, 1, .5, 1);
}

@media (prefers-reduced-motion: reduce) {
  .composer-root .floating-composer.composer-bar--embedded {
    transition: none;
  }
}
</style>

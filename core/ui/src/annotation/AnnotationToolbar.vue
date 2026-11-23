<template>
  <!-- user:“复用ping的框选那里的标注功能与样式，将这一个功能抽出来共用”+
       (工具条只负责“选哪个工具、什么颜色”，画什么由 `annotation/draw.ts` 决定；
        宿主用 CSS 变量换皮：Ping 保持截图窗口的深色玻璃，灯箱用会话主题色)。 -->
  <div class="annotation-toolbar" role="toolbar" aria-label="标注工具">
    <button
      v-for="entry in tools"
      :key="entry.tool"
      type="button"
      class="annotation-toolbar__tool"
      :class="{ 'is-active': active && tool === entry.tool }"
      :title="entry.label"
      :aria-label="entry.label"
      :aria-pressed="active && tool === entry.tool"
      :disabled="disabled"
      @click="$emit('update:tool', entry.tool)"
    >
      <svg v-if="entry.tool === 'arrow'" class="annotation-toolbar__arrow" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M3.2 12.8 L11.1 4.9" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
        <path d="M7.5 3.2 L12.8 3.2 L12.8 8.5 Z" fill="currentColor" />
      </svg>
      <HelpCircle v-else-if="entry.tool === 'question'" :size="15" :stroke-width="1.8" aria-hidden="true" />
      <AlertCircle v-else-if="entry.tool === 'exclamation'" :size="15" :stroke-width="1.8" aria-hidden="true" />
      <Type v-else-if="entry.tool === 'text'" :size="15" :stroke-width="1.8" aria-hidden="true" />
      <PenLine v-else :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>

    <div class="annotation-toolbar__palette-wrap" @pointerenter="paletteOpen = true" @pointerleave="paletteOpen = false">
      <button
        type="button"
        class="annotation-toolbar__tool"
        :class="{ 'is-active': paletteOpen }"
        title="颜色"
        aria-label="颜色"
        :disabled="disabled"
        @click="paletteOpen = !paletteOpen"
      >
        <Palette :size="15" :stroke-width="1.8" aria-hidden="true" />
        <span class="annotation-toolbar__dot" :style="{ background: annotationColor(tool, color) }" />
      </button>
      <div v-if="paletteOpen" class="annotation-toolbar__palette">
        <button
          v-for="swatch in ANNOTATION_PALETTE"
          :key="swatch"
          type="button"
          class="annotation-toolbar__swatch"
          :class="{ 'is-active': color === swatch }"
          :style="{ '--swatch': swatch }"
          :title="swatch"
          :aria-label="swatch"
          @click="choose(swatch)"
        />
      </div>
    </div>

    <slot name="extra" />

    <span class="annotation-toolbar__divider" aria-hidden="true" />

    <button type="button" class="annotation-toolbar__tool" title="撤销" aria-label="撤销" :disabled="disabled || !canUndo" @click="$emit('undo')">
      <Undo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button type="button" class="annotation-toolbar__tool" title="重做" aria-label="重做" :disabled="disabled || !canRedo" @click="$emit('redo')">
      <Redo2 :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>
    <button
      v-if="clearable"
      type="button"
      class="annotation-toolbar__tool"
      title="清空"
      aria-label="清空"
      :disabled="disabled || !canUndo"
      @click="$emit('clear')"
    >
      <Eraser :size="15" :stroke-width="1.8" aria-hidden="true" />
    </button>

    <slot name="end" />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { AlertCircle, Eraser, HelpCircle, Palette, PenLine, Redo2, Type, Undo2 } from 'lucide-vue-next'
import { ANNOTATION_PALETTE, annotationColor, type AnnotationTool } from './model'

/**
 * user:“支持修改标注（可以复用ping的框选那里的标注功能与样式）”+
 * (工具集与顺序照搬 Ping：箭头、问号、叹号、文字块；画笔在 Ping 里本来就能画，
 *  只是没有按钮，这里补上，两边共用同一套绘制代码。)
 */
const tools: { tool: AnnotationTool; label: string }[] = [
  { tool: 'arrow', label: '箭头' },
  { tool: 'question', label: '问号' },
  { tool: 'exclamation', label: '叹号' },
  { tool: 'text', label: '文字块' },
  { tool: 'pen', label: '画笔' },
]

withDefaults(defineProps<{
  tool: AnnotationTool
  /** 用户选的颜色；null 表示跟随工具默认色。 */
  color?: string | null
  disabled?: boolean
  canUndo?: boolean
  canRedo?: boolean
  /** Ping 的清空会连框选一起清，由宿主决定要不要这个按钮。 */
  clearable?: boolean
  /** 宿主正处于别的模式（例如 Ping 的框选）时，不让任何工具显示为选中。 */
  active?: boolean
}>(), {
  color: null,
  disabled: false,
  canUndo: false,
  canRedo: false,
  clearable: true,
  active: true,
})

const emit = defineEmits<{
  'update:tool': [tool: AnnotationTool]
  'update:color': [color: string]
  undo: []
  redo: []
  clear: []
}>()

const paletteOpen = ref(false)

function choose(color: string): void {
  emit('update:color', color)
  paletteOpen.value = false
}
</script>

<style scoped>
.annotation-toolbar {
  display: flex;
  align-items: center;
  gap: 2px;
}

.annotation-toolbar__tool {
  position: relative;
  flex: none;
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--annotation-fg, rgba(238, 243, 251, 0.62));
  cursor: pointer;
  transition: background 120ms ease-out, color 120ms ease-out;
}

.annotation-toolbar__tool:hover {
  background: var(--annotation-hover, rgba(238, 243, 251, 0.1));
  color: var(--annotation-fg-strong, #eef3fb);
}

.annotation-toolbar__tool.is-active {
  background: var(--annotation-active, rgba(238, 243, 251, 0.16));
  color: var(--annotation-fg-strong, #eef3fb);
}

.annotation-toolbar__tool:disabled {
  opacity: 0.45;
  cursor: default;
}

.annotation-toolbar__arrow {
  display: block;
  width: 16px;
  height: 16px;
}

.annotation-toolbar__divider {
  flex: none;
  width: 1px;
  height: 16px;
  margin: 0 4px;
  background: var(--annotation-divider, rgba(238, 243, 251, 0.16));
}

.annotation-toolbar__palette-wrap {
  position: relative;
  display: flex;
}

.annotation-toolbar__dot {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  box-shadow: 0 0 0 1px var(--annotation-dot-ring, rgba(0, 0, 0, 0.35));
  pointer-events: none;
}

.annotation-toolbar__palette {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 10px);
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--annotation-menu-border, rgba(238, 243, 251, 0.14));
  border-radius: 999px;
  background: var(--annotation-menu-bg, rgba(20, 23, 28, 0.94));
  -webkit-backdrop-filter: blur(16px) saturate(1.15);
  backdrop-filter: blur(16px) saturate(1.15);
  box-shadow: 0 14px 34px rgba(0, 0, 0, 0.32);
  white-space: nowrap;
}

/* 鼠标从按钮移到色板上时不要断开 hover，否则色板一离开按钮就消失。 */
.annotation-toolbar__palette::after {
  content: '';
  position: absolute;
  top: 100%;
  right: 0;
  left: 0;
  height: 12px;
}

.annotation-toolbar__swatch {
  flex: none;
  width: 18px;
  height: 18px;
  padding: 0;
  border: 1px solid var(--annotation-swatch-ring, rgba(255, 255, 255, 0.26));
  border-radius: 50%;
  background: var(--swatch);
  cursor: pointer;
  transition: transform 120ms ease-out;
}

.annotation-toolbar__swatch:hover {
  transform: scale(1.14);
}

.annotation-toolbar__swatch.is-active {
  box-shadow: 0 0 0 2px var(--annotation-swatch-active-ring, #14171c), 0 0 0 3.5px var(--swatch);
}

@media (prefers-reduced-motion: reduce) {
  .annotation-toolbar__tool,
  .annotation-toolbar__swatch {
    transition-duration: 0ms;
  }
}
</style>

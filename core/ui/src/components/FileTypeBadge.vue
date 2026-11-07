<template>
  <span
    class="file-type-badge"
    :class="{ 'file-type-badge--failed': failed }"
    :style="badgeStyle"
    :data-label="badge.label"
    :title="title || undefined"
    aria-hidden="true"
  ></span>
</template>

<script setup lang="ts">
// user:“把那个@的符号去掉 换成对应的文件图标……用一个 30% 的圆角”+
// (用文件类型徽标代替 @：按扩展名显示 TS/JS/V/CSS/PDF 等彩色小方块，圆角 30%。
// 标签用 CSS content 显示，不进入文本节点，复制/选文仍只拿到文件名。)
import { computed } from 'vue'
import { fileTypeBadge } from '@/helpers/fileTypeBadge'

const props = withDefaults(defineProps<{
  name: string
  size?: number
  failed?: boolean
  title?: string
}>(), {
  size: 18,
  failed: false,
  title: '',
})

const badge = computed(() => fileTypeBadge(props.name, props.failed))
const badgeStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  borderRadius: '30%',
  background: badge.value.background,
  color: badge.value.color,
  fontSize: `${Math.max(6, Math.min(9, Math.round(props.size * 0.4)))}px`,
}))
</script>

<style scoped>
.file-type-badge {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  box-sizing: border-box;
  overflow: hidden;
  line-height: 1;
  font-family: var(--font-sans, ui-sans-serif, sans-serif);
  font-weight: 800;
  letter-spacing: -0.02em;
  user-select: none;
}
.file-type-badge::before {
  content: attr(data-label);
  transform: scale(0.94);
}
</style>

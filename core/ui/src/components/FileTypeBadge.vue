<template>
  <span
    class="file-type-badge"
    :class="{ 'file-type-badge--failed': failed }"
    :style="badgeStyle"
    aria-hidden="true"
    v-html="glyph"
  ></span>
</template>

<script setup lang="ts">
// user:“把那个@的符号去掉 换成对应的文件图标……用一个 30% 的圆角”+
// (用文件类型图标代替 @：30% 圆角的彩色小方块。)
// user:“重新设计各附件的图标，最好一眼就能看出来这是个什么类型文件”+
// (统一改成线稿类别图标：图片/视频/音频/PDF/Word/表格/演示/压缩包/代码/JSON 一眼可辨；
// 纯文字标签不再进入文本节点，复制/选文仍只拿到文件名。)
import { computed } from 'vue'
import { fileTypeBadge } from '@/helpers/fileTypeBadge'
import { fileTypeIconMarkup } from '@/helpers/fileTypeIcon'

const props = withDefaults(defineProps<{
  name: string
  size?: number
  failed?: boolean
}>(), {
  size: 18,
  failed: false,
})

const badge = computed(() => fileTypeBadge(props.name, props.failed))
const glyph = computed(() => fileTypeIconMarkup(props.name, Math.max(9, Math.round(props.size * 0.66))))
const badgeStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  borderRadius: '30%',
  background: badge.value.background,
  color: badge.value.color,
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
  user-select: none;
}
.file-type-badge :deep(svg) {
  display: block;
}
.file-type-badge--failed {
  background: var(--red) !important;
}
</style>

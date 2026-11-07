<template>
  <!-- user:“更适配新的UI”+(引用在独立原文栏展示；保留原始文本节点供选文定位，避免辅助对话中的标记偏移)。 -->
  <span v-if="prefix" hidden aria-hidden="true" data-auxiliary-reference-prefix>{{ prefix }}</span>
  <template v-for="(segment, index) in segments" :key="index"><a v-if="segment.path" href="#" class="user-file-reference" :title="actions.absolute(segment.path)" @click.prevent="actions.open(segment.path)" @contextmenu.stop="actions.menu($event, segment.path)"><FileTypeBadge :name="segment.path" :size="13" /><span>{{ segment.text }}</span></a><template v-else>{{ segment.text }}</template></template>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import FileTypeBadge from '@/components/FileTypeBadge.vue'
import { referenceSpans } from '@/composer/fileReferences'
import { useReferenceActions } from '@/helpers/referenceActions'
const props = defineProps<{ text: string; foldedPrefix?: string }>()
const prefix = computed(() => props.foldedPrefix && props.text.startsWith(props.foldedPrefix) ? props.foldedPrefix : '')
const visibleText = computed(() => props.text.slice(prefix.value.length))
const actions = useReferenceActions()
const segments = computed(() => {
  const result: { text: string; path?: string }[] = []
  let end = 0
  for (const span of referenceSpans(visibleText.value)) {
    // user:“把那个@的符号去掉 换成对应的文件图标”+(气泡里的引用也只显示
    // 文件类型徽标 + 文件名，不再显示 @；底层原文仍保留完整路径)。
    result.push({ text: visibleText.value.slice(end, span.from) }, { text: span.name, path: span.path }); end = span.to
  }
  result.push({ text: visibleText.value.slice(end) }); return result
})
</script>
<style scoped>
/* user:“文件路径标蓝渲染成@文件名”+(用户气泡与正文采用同样的引用显示)。 */
.user-file-reference { display: inline-flex; align-items: center; gap: 3px; color: var(--blue); text-decoration: none; cursor: pointer; vertical-align: baseline; }
.user-file-reference:hover { text-decoration: underline; }
</style>

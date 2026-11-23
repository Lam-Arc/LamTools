<script setup lang="ts">
import { ref } from 'vue'
import ComposerBar from '@/components/ComposerBar.vue'
import InlineFileComposer from '@/components/InlineFileComposer.vue'
import AttachmentSourceMenu from '@/components/AttachmentSourceMenu.vue'

// user:“交互测试”+(输入、引用和发送只作用于本地示例，不连接会话或文件)。
const draft = ref(''), sent = ref(''), opened = ref(''), attachmentRequested = ref(false)
const suggestions = [{ name: '笔记.md', path: 'C:/示例/笔记.md', description: '本地示例文件' }, { name: '背景', path: '示例上下文', description: '本地示例上下文', context: true }]
function submit() { if (!draft.value.trim()) return; sent.value = draft.value; draft.value = '' }
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && !event.isComposing) { event.preventDefault(); submit() }
}
// user:“把胶囊做了……它只是现在输入栏的形态变体，不是新样式”+
// (胶囊形态就用真组件展示：同一套卡片、描边、底色与发送键，只把形态收成一行。)
const compactDraft = ref(''), compactSent = ref('')
function submitCompact() { if (!compactDraft.value.trim()) return; compactSent.value = compactDraft.value; compactDraft.value = '' }
function onCompactKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && !event.isComposing) { event.preventDefault(); submitCompact() }
}
</script>

<template>
  <div class="composer-example" @contextmenu.capture.prevent.stop>
    <ComposerBar v-model="draft" variant="embedded" @submit="submit">
      <!-- user:“这个组内的 UI 设计与风格”+(展示生产输入框的附件入口，点击只记本地操作)。 -->
      <template #attach-button><AttachmentSourceMenu @select="attachmentRequested = true" /></template>
      <template #textarea><InlineFileComposer v-model="draft" :suggestions="suggestions" placeholder="输入示例，输入 @ 引用文件" @keydown="onKeydown" @preview-file="opened = $event" /></template>
    </ComposerBar>
    <span v-if="sent" data-gallery-composer-sent>本地发送：{{ sent }}</span>
    <span v-if="opened">本地预览：{{ opened }}</span>
    <span v-if="attachmentRequested" role="status">示例操作：选择附件</span>
  </div>
  <div class="composer-example composer-example--compact" data-gallery-composer-compact @contextmenu.capture.prevent.stop>
    <ComposerBar v-model="compactDraft" variant="compact" @submit="submitCompact">
      <template #textarea><InlineFileComposer v-model="compactDraft" :suggestions="suggestions" placeholder="还没开始写时，输入栏就收成这一行" @keydown="onCompactKeydown" @preview-file="opened = $event" /></template>
    </ComposerBar>
    <span v-if="compactSent" data-gallery-composer-compact-sent>本地发送：{{ compactSent }}</span>
    <small class="composer-example__note">单行胶囊：没有文字、没有待发附件、没有在运行、也没有聚焦时收起；一点进去或一开始写就换回完整形态。</small>
  </div>
</template>

<style scoped>
.composer-example { width: 100%; min-width: 0; }
.composer-example--compact { margin-top: 12px; }
.composer-example__note { display: block; margin-top: 6px; color: var(--muted); font-size: 12px; }
/* 产品里的胶囊挂在浮动输入栏的固定锚点上；展厅只借外形，所以把它放回文档流里展示。 */
.composer-example--compact :deep(.composer-root--compact > .floating-composer) {
  position: relative;
  inset: auto;
  width: 100%;
  max-width: none;
  transform: none;
}
</style>

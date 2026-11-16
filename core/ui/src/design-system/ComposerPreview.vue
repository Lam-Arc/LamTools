<script setup lang="ts">
import { ref } from 'vue'
import ComposerBar from '@/components/ComposerBar.vue'
import InlineFileComposer from '@/components/InlineFileComposer.vue'

// user:“交互测试”+(输入、引用和发送只作用于本地示例，不连接会话或文件)。
const draft = ref(''), sent = ref(''), opened = ref('')
const suggestions = [{ name: '笔记.md', path: 'C:/示例/笔记.md', description: '本地示例文件' }, { name: '背景', path: '示例上下文', description: '本地示例上下文', context: true }]
function submit() { if (!draft.value.trim()) return; sent.value = draft.value; draft.value = '' }
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey && !event.isComposing) { event.preventDefault(); submit() }
}
</script>

<template>
  <div class="composer-example" @contextmenu.capture.prevent.stop>
    <ComposerBar v-model="draft" variant="embedded" @submit="submit">
      <template #textarea><InlineFileComposer v-model="draft" :suggestions="suggestions" placeholder="输入示例，输入 @ 引用文件" @keydown="onKeydown" @preview-file="opened = $event" /></template>
    </ComposerBar>
    <span v-if="sent" data-gallery-composer-sent>本地发送：{{ sent }}</span>
    <span v-if="opened">本地预览：{{ opened }}</span>
  </div>
</template>

<style scoped>
.composer-example { width: 100%; min-width: 0; }
</style>

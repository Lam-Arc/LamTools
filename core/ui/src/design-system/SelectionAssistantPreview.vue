<script setup lang="ts">
import { onBeforeUnmount, provide, ref } from 'vue'
import SelectionAssistant from '@/study/SelectionAssistant.vue'
import { CORE_PLUGIN_MODE_CONTEXT, type CorePluginModeContext } from '@/plugins/context'
import { normalizeMark } from '@/study/api'
import { marks, showMark } from '@/study/annotations'

// user:“交互测试”+(解释请求和标记只在展厅内存中模拟，卸载后恢复原状态)。
const previousMarks = marks.value
const failed = ref(false)
const sample = normalizeMark({ id: 'gallery-selection', anchor: { document_id: 'gallery-example', quote: '示例文本', session_id: 'gallery' }, explain: '', translate: '', thread: [] })
let responseMark = { ...sample }
const requestRpc = async (method: string, params?: Record<string, unknown>) => {
  if (method === 'study.marks') return { marks: [], total: 0 }
  if (method === 'study.text') {
    if (failed.value) throw new Error('示例回答失败')
    if (params?.action === 'translate') responseMark = { ...responseMark, translate: '这是本地示例翻译' }
    else if (params?.action === 'ask') responseMark = { ...responseMark, thread: [...responseMark.thread, { role: 'user', content: String(params.question || '') }, { role: 'assistant', content: '这是本地示例回答' }] }
    else responseMark = { ...responseMark, explain: '这是本地示例解释' }
    return { mark: responseMark }
  }
  return {}
}
provide(CORE_PLUGIN_MODE_CONTEXT, { requestRpc, selectedModelId: ref('sample'), lastEvent: ref(null), setRuntimeStatus: () => {} } as unknown as CorePluginModeContext)
onBeforeUnmount(() => { marks.value = previousMarks })
</script>

<template>
  <div class="selection-assistant-preview">
    <label><input v-model="failed" type="checkbox" class="sunday-checkbox" />模拟回答失败</label>
    <button type="button" class="btn btn--secondary" @click.stop="showMark(sample, 'explain')">打开解释示例</button>
    <SelectionAssistant session-id="gallery" mode="gallery" theme-mode="light" :jump="async () => {}" />
  </div>
</template>

<style scoped>
.selection-assistant-preview { display: grid; gap: var(--space-3); width: 100%; }
</style>

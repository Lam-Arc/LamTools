<script setup lang="ts">
import { ref } from 'vue'
import MarksPanel from '@/study/MarksPanel.vue'
import { normalizeMark } from '@/study/api'
import type { StudyMark, TextAction } from '@/study/types'
import '@/study/study.css'

// user:“交互测试”+(标记与事件仅保存在展厅内存)。
function sample(): StudyMark { return normalizeMark({ id: 'sample', anchor: { quote: '示例标记文本' }, explain: '示例解释', translate: '示例翻译', thread: [{ role: 'user', content: '示例问题' }] }) }
const items = ref([sample()]), result = ref('')
const labels: Record<TextAction, string> = { mark: '标记', explain: '解释', translate: '翻译', ask: '询问' }
function show(_mark: StudyMark, action: TextAction) { result.value = labels[action] }
function remove(mark: StudyMark) { items.value = items.value.filter(item => item.id !== mark.id); result.value = '删除' }
</script>

<template>
  <div class="study-marks-preview">
    <button type="button" class="btn btn--secondary" @click="items = [sample()]; result = ''">重置示例</button>
    <div class="study-marks-preview__surface"><MarksPanel :items="items" :on-show="show" :on-jump="() => { result = '定位' }" :on-delete="remove" /></div>
    <span v-if="result">本地操作：{{ result }}</span>
  </div>
</template>

<style scoped>
.study-marks-preview { display: grid; gap: var(--space-3); width: 100%; }
.study-marks-preview__surface { padding: var(--space-3); background: var(--theme-backdrop-background); border-radius: var(--radius); }
</style>

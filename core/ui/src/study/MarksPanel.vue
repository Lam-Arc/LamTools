<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { Languages, Lightbulb, MessageCircle, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'
import { marks, showMark, jumpMark, deleteMark } from '@/study/annotations.ts'
import type { StudyMark, TextAction } from '@/study/types.ts'

// user:“交互测试”+(可注入隔离的标记与操作，实际应用默认沿用共享标记和事件)。
const props = defineProps<{ items?: StudyMark[]; onShow?: (mark: StudyMark, action: TextAction) => void; onJump?: (mark: StudyMark) => void; onDelete?: (mark: StudyMark) => void }>()
const displayed = computed(() => props.items ?? marks.value)
function show(mark: StudyMark, action: TextAction) { (props.onShow ?? showMark)(mark, action) }
function jump(mark: StudyMark) { (props.onJump ?? jumpMark)(mark) }
function remove(mark: StudyMark) { (props.onDelete ?? deleteMark)(mark) }
</script>
<template>
  <div class="study-marks">
    <p v-if="!displayed.length">{{ t("选中文字后右键，即可解释、询问或翻译。") }}</p>
    <div v-for="mark in displayed" :key="mark.id" class="study-mark-row">
      <button class="btn btn--ghost study-mark-quote" :title="mark.anchor.quote" @click="jump(mark)">{{ mark.anchor.quote }}</button>
      <button v-if="mark.translate" class="btn btn--ghost" :title="t('翻译')" :aria-label="t('翻译')" @click="show(mark, 'translate')"><Languages :size="14" /></button>
      <button v-if="mark.explain" class="btn btn--ghost" :title="t('解释')" :aria-label="t('解释')" @click="show(mark, 'explain')"><Lightbulb :size="14" /></button>
      <button v-if="mark.thread.length" class="btn btn--ghost" :title="t('询问')" :aria-label="t('询问')" @click="show(mark, 'ask')"><MessageCircle :size="14" /></button>
      <button class="btn btn--ghost" :title="t('删除标记')" :aria-label="t('删除标记')" @click="remove(mark)"><Trash2 :size="14" /></button>
    </div>
  </div>
</template>
<style scoped>
.study-marks { color: var(--theme-backdrop-text); }
.study-marks p { font-size: 12px; line-height: 1.5; }
.study-mark-row { display: flex; align-items: center; gap: var(--space-1); min-width: 0; padding-block: var(--space-1); }
.study-mark-quote { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; justify-content: start !important; }
</style>

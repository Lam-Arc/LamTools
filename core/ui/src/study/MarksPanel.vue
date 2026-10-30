<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { Languages, Lightbulb, MessageCircle, Trash2 } from 'lucide-vue-next'
import { marks, showMark, jumpMark, deleteMark } from '@/study/annotations.ts'
</script>
<template>
  <div class="study-marks">
    <p v-if="!marks.length">{{ t("选中文字后右键，即可解释、询问或翻译。") }}</p>
    <div v-for="mark in marks" :key="mark.id" class="study-mark-row">
      <button class="btn btn--ghost study-mark-quote" :title="mark.anchor.quote" @click="jumpMark(mark)">{{ mark.anchor.quote }}</button>
      <button v-if="mark.translate" class="btn btn--ghost" :title="t('翻译')" :aria-label="t('翻译')" @click="showMark(mark, 'translate')"><Languages :size="14" /></button>
      <button v-if="mark.explain" class="btn btn--ghost" :title="t('解释')" :aria-label="t('解释')" @click="showMark(mark, 'explain')"><Lightbulb :size="14" /></button>
      <button v-if="mark.thread.length" class="btn btn--ghost" :title="t('询问')" :aria-label="t('询问')" @click="showMark(mark, 'ask')"><MessageCircle :size="14" /></button>
      <button class="btn btn--ghost" :title="t('删除标记')" :aria-label="t('删除标记')" @click="deleteMark(mark)"><Trash2 :size="14" /></button>
    </div>
  </div>
</template>
<style scoped>
.study-marks { color: var(--theme-backdrop-text); }
.study-marks p { font-size: 12px; line-height: 1.5; }
.study-mark-row { display: flex; align-items: center; gap: var(--space-1); min-width: 0; padding-block: var(--space-1); }
.study-mark-quote { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; justify-content: start !important; }
</style>

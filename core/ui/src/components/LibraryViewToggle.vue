<template>
  <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(资料、记忆与方案共用网格/列表切换，保留原有按钮语义)。 -->
  <div class="library-view-toggle" role="group" :aria-label="t('视图切换')">
    <button type="button" :class="{ active: model === 'grid' }" :aria-pressed="model === 'grid'" :aria-label="t('网格视图')" :title="t('网格视图')" @click="model = 'grid'"><LayoutGrid :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
    <button type="button" :class="{ active: model === 'list' }" :aria-pressed="model === 'list'" :aria-label="t('列表视图')" :title="t('列表视图')" @click="model = 'list'"><List :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
  </div>
</template>
<script setup lang="ts">
import { LayoutGrid, List } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'
const model = defineModel<'grid' | 'list'>({ required: true })
</script>

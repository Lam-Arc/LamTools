<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import type { StudyNoteResource } from '@/study/types.ts'

defineProps<{
  resources: StudyNoteResource[]
}>()

function resourceLabel(resource: StudyNoteResource): string {
  return resource.title || resource.id || t("未命名来源")
}
function resourceType(resource: StudyNoteResource): string {
  return resource.originalType || resource.original_type || resource.type || resource.kind || 'resource'
}
</script>

<template>
  <footer v-if="resources.length" class="study-note-references" :aria-label="t('笔记来源')">
    <h3>{{ t("来源") }}</h3>
    <ol>
      <li v-for="(resource, index) in resources" :key="resource.id || `${resourceType(resource)}-${index}`">
        <span class="study-note-reference-index">[{{ index + 1 }}]</span>
        <span class="study-note-reference-title">{{ resourceLabel(resource) }}</span>
        <span class="study-note-reference-type">{{ resourceType(resource) }}</span>
        <span v-if="resource.locator" class="study-note-reference-locator">{{ resource.locator }}</span>
      </li>
    </ol>
  </footer>
</template>

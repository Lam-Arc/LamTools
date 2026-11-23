<script setup lang="ts">
import { computed, ref } from 'vue'
import NotesManager from '@/study/NotesManager.vue'
import { normalizeNote } from '@/study/api'
import type { StudyNote } from '@/study/types'
import '@/study/study.css'

// user:“交互测试”+(笔记和保存失败均为内存示例，不读取或修改真实笔记)。
const failSave = ref(false), selectedId = ref('note-a')
const notes = ref([
  normalizeNote({ id: 'note-a', title: '示例笔记', path: '示例笔记.md', body_md: '# 示例笔记\n\n[[note-b|另一篇笔记]]', revision: 1, content_hash: 'a1', resources: [], resource_ids: [], locks: [], links: [], backlinks: [] }),
  normalizeNote({ id: 'note-b', title: '另一篇笔记', path: '另一篇笔记.md', body_md: '# 另一篇笔记\n\n示例内容。', revision: 1, content_hash: 'b1', resources: [], resource_ids: [], locks: [], links: [], backlinks: [] }),
])
const selected = computed(() => notes.value.find(note => note.id === selectedId.value) || null)
function select(note: StudyNote | null) { selectedId.value = note?.id || '' }
async function save(note: StudyNote, bodyMd: string): Promise<StudyNote> {
  if (failSave.value) throw new Error('示例保存失败')
  const updated = { ...note, bodyMd, revision: note.revision + 1, contentHash: `sample-${note.revision + 1}` }
  notes.value = notes.value.map(item => item.id === note.id ? updated : item)
  return updated
}
// user:“参数调整、变体对比”+(模拟外部更新只改变展厅内存中的当前笔记)。
function updateRemote() {
  notes.value = notes.value.map(note => note.id === selectedId.value
    ? { ...note, bodyMd: '# 示例远程更新', revision: note.revision + 1, contentHash: `remote-${note.revision + 1}` }
    : note)
}
</script>

<template>
  <div class="study-notes-preview">
    <label><input v-model="failSave" type="checkbox" class="sunday-checkbox" />模拟保存失败</label>
    <button type="button" class="btn btn--secondary" @click="updateRemote">模拟远程更新</button>
    <div class="study-notes-preview__surface"><NotesManager :notes="notes" :selected="selected" :on-select="select" :on-save-document="save" /></div>
  </div>
</template>

<style scoped>
.study-notes-preview { display: grid; gap: var(--space-3); width: 100%; }
.study-notes-preview__surface { height: 540px; overflow: auto; padding: var(--space-3); background: var(--theme-main-background); border-radius: var(--radius); }
</style>

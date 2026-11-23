<script setup lang="ts">
import { ref } from 'vue'
import StudyNoteTree from '@/study/StudyNoteTree.vue'
import type { StudyNoteTreeNode } from '@/study/types'
import '@/study/study.css'

// user:“交互测试”+(笔记树读取与选择只操作本地示例)。
const failed = ref(false), selected = ref(''), selectedId = ref('')
const tree: StudyNoteTreeNode[] = [{ id: 'course', title: '示例课程', path: '示例课程', kind: 'folder', children: [{ id: 'note', title: '示例笔记', path: '示例课程/示例笔记.md', kind: 'note' }] }]
function select(node: StudyNoteTreeNode) { selected.value = node.title; selectedId.value = node.id }
</script>

<template>
  <div class="study-note-tree-preview">
    <label><input v-model="failed" type="checkbox" class="sunday-checkbox" />模拟读取失败</label>
    <div class="study-note-tree-preview__surface"><StudyNoteTree :tree="tree" :active-id="selectedId" :error="failed ? '示例读取失败' : ''" :on-select="select" :on-refresh="() => { failed = false }" /></div>
    <span v-if="selected">本地选择：{{ selected }}</span>
  </div>
</template>

<style scoped>
.study-note-tree-preview { display: grid; gap: var(--space-3); width: 100%; }
.study-note-tree-preview__surface { padding: var(--space-2); background: var(--theme-backdrop-background); border-radius: var(--radius); }
</style>

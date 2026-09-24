<script setup lang="ts">
import StudyNoteTree from './StudyNoteTree.vue'
import StudySidebar from './StudySidebar.vue'
import type { Course, KnowledgeItem, StudyNoteTreeNode, StudyPin } from './types'

type TreeParent = { id: string; kind: 'course' | 'module'; courseId?: string }

const props = withDefaults(defineProps<{
  noteWorkspaceActive?: boolean
  noteTree?: StudyNoteTreeNode[]
  activeNoteId?: string
  noteTreeLoading?: boolean
  noteTreeError?: string
  selectNote?: (node: StudyNoteTreeNode) => void | Promise<void>
  refreshNoteTree?: () => void | Promise<void>
  leaveNotes?: () => void | Promise<void>
  courses: Course[]
  active: string
  select: (id: string) => void | Promise<void>
  loadChildren?: (parent: TreeParent) => Promise<KnowledgeItem[]>
  openNode?: (node: KnowledgeItem) => void | Promise<void>
  openPin?: (pin: StudyPin) => void | Promise<void>
  openSearch?: () => void
  pins?: StudyPin[]
  togglePin?: (pin: StudyPin) => void | Promise<void>
  notesEnabled?: boolean
}>(), {
  noteWorkspaceActive: false, noteTree: () => [], activeNoteId: '', noteTreeLoading: false,
  noteTreeError: '', selectNote: undefined, refreshNoteTree: undefined, leaveNotes: undefined,
  loadChildren: undefined, openNode: undefined, openPin: undefined, openSearch: undefined,
  pins: () => [], togglePin: undefined, notesEnabled: true,
})
</script>

<template>
  <StudyNoteTree v-if="noteWorkspaceActive" :tree="noteTree" :active-id="activeNoteId" :loading="noteTreeLoading" :error="noteTreeError" :on-select="selectNote" :on-refresh="refreshNoteTree" :on-back="leaveNotes" />
  <StudySidebar v-else :courses="courses" :active="active" :select="select" :load-children="loadChildren" :open-node="openNode" :open-pin="openPin" :open-search="openSearch" :pins="pins" :toggle-pin="togglePin" :notes-enabled="notesEnabled" />
</template>

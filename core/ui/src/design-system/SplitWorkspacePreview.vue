<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import CoreSplitWorkspace from '@/components/CoreSplitWorkspace.vue'
import CoreSplitTextEditor from '@/components/CoreSplitTextEditor.vue'
import { useSplitWorkspace } from '@/split/useSplitWorkspace'
import type { createSplitDocuments, SplitDocumentHandle, SplitDocumentState } from '@/split/documents'

// user:“直接渲染项目真实组件…交互测试”+(分屏及标签仅使用内存样例)。
const controller = useSplitWorkspace(ref('gallery-split'), undefined, undefined, { persist: false })
const pane = controller.split('main', 'right')!
controller.add('editor', '', '示例文档', pane)
controller.add('editor', '', '示例笔记', pane)
const dirtyTabs = reactive(new Set<string>())
const sampleDocuments = new Map<string, SplitDocumentHandle>()
// user:“交互测试”+(真实编辑器的读写和草稿仅存内存，不接触本机文件或备份)。
const documents = {
  get(root: string, path: string, id: string): SplitDocumentHandle {
    const previous = sampleDocuments.get(id)
    if (previous) return previous
    const doc = reactive<SplitDocumentState>({ root, path, content: '', baseline: '', loaded: false, loading: false, saving: false, error: '', recovered: false })
    const handle: SplitDocumentHandle = {
      doc, dirty: computed(() => doc.content !== doc.baseline),
      async load() { doc.loaded = true },
      async save(nextPath = doc.path) { if (!nextPath) { doc.error = '请填写保存路径'; return false }; doc.path = nextPath; doc.baseline = doc.content; doc.error = ''; return true },
      flushDraft() {}, release() {},
    }
    sampleDocuments.set(id, handle)
    return handle
  },
  flush() {}, dispose() {},
} as ReturnType<typeof createSplitDocuments>
function setDirty(id: string, value: boolean) { if (value) dirtyTabs.add(id); else dirtyTabs.delete(id) }
</script>

<template>
  <div data-gallery-split style="position: relative; width: 100%; height: 600px; overflow: hidden">
    <CoreSplitWorkspace :controller="controller" work-root="" :dirty="dirtyTabs">
      <!-- user:“直接渲染项目真实组件”+(真实文本编辑器使用隔离的本地文档)。 -->
      <template #default="{ tab, visible }"><CoreSplitTextEditor v-if="tab.kind === 'editor'" :tab="tab" root="" :visible="visible" :controller="controller" :documents="documents" @dirty="setDirty" /><div v-else class="split-preview-content">{{ tab.title }} · 本地预览内容</div></template>
    </CoreSplitWorkspace>
  </div>
</template>

<style scoped>
/* user:“实时预览”+(分屏定位在展厅的示例区域内，不覆盖整页)。 */
[data-gallery-split] :deep(.split-workspace) { position: absolute; inset: 0; }
.split-preview-content { padding: var(--space-4); }
</style>

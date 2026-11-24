<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import CoreWorkspace from '@/components/CoreWorkspace.vue'
import CoreWorkspaceTabDrawer from '@/components/CoreWorkspaceTabDrawer.vue'
import CoreContentRoot from '@/components/CoreContentRoot.vue'
import CoreSessionTitleEditor from '@/components/CoreSessionTitleEditor.vue'
import CoreSplitTextEditor from '@/components/CoreSplitTextEditor.vue'
import SessionSidebar from '@/components/SessionSidebar.vue'
import WorkspaceShell from '@/components/WorkspaceShell.vue'
import WindowControls from '@/components/TitleBar.vue'
import { showToast } from '@/composables/useCoreToast'
import { t } from '@/i18n'
import '@/styles/split-workspace.css'
import { useWorkspace } from '@/workspace/useWorkspace'
import type { createSplitDocuments, SplitDocumentHandle, SplitDocumentState } from '@/split/documents'

// user:“直接渲染项目真实组件…交互测试”+(分屏及标签仅使用内存样例)。
const controller = useWorkspace(ref('gallery-split'), undefined, undefined, { persist: false, onInsufficient: () => showToast('error', t('当前窗口太小，无法分屏')) })
const pane = controller.split('main', 'right')!
controller.add('editor', '', '示例文档', pane)
controller.add('editor', '', '示例笔记', pane)
const dirtyTabs = reactive(new Set<string>())
const shellGeometry = ref<Record<string, string>>({})
const sessionTitle = ref('示例会话')
// user:“再track目前最大卡顿因素是什么，然后修复”+(展厅用本地会话演示侧栏拖动排序)。
const previewSidebarGroups = [
  { id: 'gallery-project', name: '示例项目', sessions: [
    { id: 'gallery-session-a', title: '整理资料' },
    { id: 'gallery-session-b', title: '验证结果' },
  ] },
]
async function renameSession(title: string) { sessionTitle.value = title }
// user:“标签页过多时应该是这样的”+(展厅用真实分屏标签条演示标题、图标和翻页)。
const previewTabPane = ref<string | null>(null)
function previewTabOverflow() {
  if (previewTabPane.value) return
  const target = controller.split(pane, 'bottom')
  if (!target) return
  previewTabPane.value = target
  for (let index = 1; index <= 20; index++) controller.add('browser', '', `示例网页 ${index}`, target)
}
// user:“找出 3 个及以上优化”+(用子代理和编辑器混排演示统一的分屏页眉)。
const subAgentPreviewReady = ref(false)
function previewSubAgentTab() {
  if (subAgentPreviewReady.value) return
  subAgentPreviewReady.value = Boolean(controller.add('agent', '', '示例子代理', pane))
}
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
  <div data-gallery-split>
    <!-- user:“手动缩回后也应该有打开方式”+(展厅复用真实外壳以演示项目侧栏开关)。 -->
    <WorkspaceShell class="workspace-shell--split" :class="{ 'workspace-shell--main-replaced': Boolean(controller.state.mainTab) }" :collapse-left-sidebar="controller.state.layout === 'browser'" :style="shellGeometry" product-name="Sunday" platform="desktop" storage-key="sunday.gallery.workspace" compact-chrome hide-composer :show-sidebar-header="false" :show-sidebar-search-action="false" :show-sidebar-plugins-action="false" :show-sidebar-settings-action="false" :show-right-panel="false">
      <template #root-entry><CoreContentRoot :controller="controller" variant="axis" /></template>
      <template #primary><div class="core-sidebar-mode-spacer" aria-hidden="true" /></template>
      <template #sidebar-body>
        <button type="button" class="btn btn--ghost" :disabled="Boolean(previewTabPane)" @click="previewTabOverflow">预览标签溢出</button>
        <button type="button" class="btn btn--ghost" :disabled="subAgentPreviewReady || !controller.state.panes[pane]" @click="previewSubAgentTab">预览子代理标签</button>
        <SessionSidebar :project-groups="previewSidebarGroups" />
      </template>
      <template #main-header>
        <!-- user:“此处的页眉与标题不见了”+(展厅用实际分屏几何与会话标题复现并验证页眉)。 -->
        <div class="thread-header" data-session-header>
          <CoreSessionTitleEditor :title="sessionTitle" :rename="renameSession" />
        </div>
      </template>
      <template #workspace-overlays>
        <WindowControls show-in-preview inline><CoreWorkspaceTabDrawer :controller="controller" /></WindowControls>
      </template>
      <template #modals>
        <CoreWorkspace :controller="controller" work-root="" :dirty="dirtyTabs" @geometry="shellGeometry = $event">
          <!-- user:“直接渲染项目真实组件”+(真实文本编辑器使用隔离的本地文档)。 -->
          <template #default="{ tab, visible }"><CoreSplitTextEditor v-if="tab.kind === 'editor'" :tab="tab" root="" :visible="visible" :controller="controller" :documents="documents" @dirty="setDirty" /><div v-else class="split-preview-content">{{ tab.title }} · 本地预览内容</div></template>
        </CoreWorkspace>
      </template>
    </WorkspaceShell>
  </div>
</template>

<style scoped>
/* user:“实时预览”+(分屏定位在展厅的示例区域内，不覆盖整页)。 */
[data-gallery-split] { position: relative; width: 100%; height: 600px; contain: layout paint; }
[data-gallery-split] :deep(.workspace-chrome-overlays) { right: 0; }
.split-preview-content { padding: var(--space-4); }
</style>

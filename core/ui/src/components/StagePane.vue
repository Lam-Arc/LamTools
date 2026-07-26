<template>
  <div class="stage-pane">
    <!-- Tab bar -->
    <div class="stage-tabs">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="stage-tab"
        :class="{ active: tab.id === activeId }"
        @click="$emit('activate', tab.id)"
      >
        <span class="stage-tab-icon" aria-hidden="true">{{ kindIcon(tab.kind) }}</span>
        <span class="stage-tab-label" :title="tab.label">{{ tab.label }}</span>
        <button
          type="button"
          class="stage-tab-close"
          aria-label="关闭"
          @click.stop="$emit('close', tab.id)"
        >×</button>
      </div>
    </div>

    <!-- Content area -->
    <div class="stage-content">
      <template v-if="activeTab">
        <StageCodeEditor
          v-if="activeTab.kind === 'code'"
          ref="codeEditorRef"
          :content="activeTab.content || ''"
          :language="activeTab.language"
          @update:content="(val) => $emit('update-content', { id: activeTab!.id, content: val })"
          @dirty="(val) => codeDirty = val"
          @save="handleSave"
        />
        <StageImagePreview
          v-else-if="activeTab.kind === 'image'"
          :src="activeTab.url || ''"
          :label="activeTab.label"
        />
        <StageMediaPreview
          v-else-if="activeTab.kind === 'video' || activeTab.kind === 'audio'"
          :src="activeTab.url || ''"
          :kind="activeTab.kind"
        />
        <StageBrowser
          v-else-if="activeTab.kind === 'browser' || activeTab.kind === 'pdf'"
          :url="activeTab.url || ''"
        />
        <div v-else-if="activeTab.kind === 'empty'" class="stage-empty">
          <p>从右侧文件树选择文件，或输入网址打开浏览器</p>
        </div>
        <div v-else class="stage-empty">
          <p>不支持预览此文件类型</p>
        </div>
      </template>
      <div v-else class="stage-empty">
        <p>视窗已打开。从右侧文件树选择文件，或输入网址打开浏览器。</p>
      </div>
    </div>

    <!-- Status bar -->
    <div class="stage-status">
      <span v-if="activeTab" class="stage-status-label">{{ activeTab.label }}</span>
      <span v-else>无打开的标签</span>
      <button
        v-if="activeTab?.kind === 'code' && codeDirty"
        type="button"
        class="stage-save-btn"
        :disabled="saving"
        @click="handleSave"
      >{{ saving ? '保存中...' : '保存 ⌘S' }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { StageResource } from '../types'
import StageCodeEditor from './StageCodeEditor.vue'
import StageImagePreview from './StageImagePreview.vue'
import StageMediaPreview from './StageMediaPreview.vue'
import StageBrowser from './StageBrowser.vue'

const props = defineProps<{
  tabs: StageResource[]
  activeId: string | null
}>()

const emit = defineEmits<{
  activate: [id: string]
  close: [id: string]
  'update-content': [payload: { id: string; content: string }]
  save: [payload: { id: string; content: string }]
}>()

const codeEditorRef = ref<InstanceType<typeof StageCodeEditor> | null>(null)
const codeDirty = ref(false)
const saving = ref(false)

const activeTab = computed(() => {
  if (!props.activeId) return null
  return props.tabs.find((t) => t.id === props.activeId) ?? null
})

function handleSave() {
  if (!activeTab.value || saving.value) return
  saving.value = true
  emit('save', { id: activeTab.value.id, content: activeTab.value.content || '' })
}

function onSaved() {
  saving.value = false
  codeDirty.value = false
  codeEditorRef.value?.markSaved()
}

defineExpose({ onSaved })

function kindIcon(kind: StageResource['kind']): string {
  const map: Record<string, string> = {
    code: '{}',
    image: '🖼',
    video: '▶',
    audio: '♪',
    browser: '🌐',
    pdf: 'P',
    markdown: 'M',
    empty: '·',
  }
  return map[kind] ?? '·'
}
</script>

<style scoped>
.stage-pane {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: transparent;
  color: var(--theme-backdrop-text, #f2efeb);
}
.stage-tabs {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0 6px;
  height: 34px;
  min-height: 34px;
  overflow-x: auto;
  scrollbar-width: none;
  background: transparent;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 8%, transparent);
}
.stage-tabs::-webkit-scrollbar { display: none; }
.stage-tab {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 8px 4px 10px;
  border-radius: 6px 6px 0 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 50%, transparent);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  border-bottom: 2px solid transparent;
  transition: background 0.15s, color 0.15s;
}
.stage-tab:hover { background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 4%, transparent); color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 80%, transparent); }
.stage-tab.active {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 6%, transparent);
  color: var(--theme-backdrop-text, #f2efeb);
  border-bottom-color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 30%, transparent);
}
.stage-tab-icon { font-size: 11px; opacity: 0.7; }
.stage-tab-label {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stage-tab-close {
  width: 16px;
  height: 16px;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  display: grid;
  place-items: center;
  opacity: 0.5;
}
.stage-tab-close:hover { opacity: 1; background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 12%, transparent); }
.stage-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.12);
}
.stage-empty {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 35%, transparent);
  font-size: 13px;
}
.stage-status {
  flex: 0 0 auto;
  padding: 3px 12px;
  font-size: 11px;
  color: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 40%, transparent);
  background: transparent;
  border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 4%, transparent);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.stage-status-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stage-save-btn {
  flex: 0 0 auto;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 20%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 8%, transparent);
  color: var(--theme-backdrop-text, #f2efeb);
  padding: 2px 10px;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.15s;
}
.stage-save-btn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-backdrop-text, #f2efeb) 14%, transparent);
}
.stage-save-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>

<template>
  <section class="wf-resources" aria-label="工作流资源">
    <header class="wf-resources-head">
      <div>
        <h3>工作流资源</h3>
        <span>JSON 文件与模板</span>
      </div>
      <span class="wf-resource-format">JSON</span>
    </header>
    <div class="wf-resource-actions">
      <button type="button" @click="openImport">导入 JSON</button>
      <button type="button" :disabled="!workflow || exporting" @click="exportCurrent('native-v2')">Sunday V2</button>
      <button type="button" :disabled="!workflow || exporting" @click="exportCurrent('comfyui-v1')">ComfyUI v1</button>
      <button type="button" :disabled="!workflow || exporting" @click="exportCurrent('comfyui-v0.4')">ComfyUI 0.4</button>
      <input ref="fileInput" class="wf-file-input" type="file" accept="application/json,.json" aria-label="选择工作流 JSON 文件" @change="importFile" />
    </div>
    <p v-if="message" class="wf-resource-message" :class="{ error: messageKind === 'error' }" :role="messageKind === 'error' ? 'alert' : 'status'">{{ message }}</p>
    <div v-if="templates.length" class="wf-templates">
      <h4>模板入口</h4>
      <button v-for="template in templates" :key="template.id" type="button" class="wf-template" :title="template.description" @click="useTemplate(template)">
        <span>{{ template.name }}</span><small>{{ template.description }}</small>
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import {
  parseWorkflowImport,
  type WorkflowExportFormat,
  type WorkflowImportSource,
  type WorkflowTemplate,
} from './resources'
import type { WorkflowDef } from './types'

const props = withDefaults(defineProps<{
  workflow?: WorkflowDef | null
  templates?: WorkflowTemplate[]
  onImport?: (source: WorkflowImportSource) => void | Promise<void>
  onExport?: (format: WorkflowExportFormat) => boolean | void | Promise<boolean | void>
  onTemplate?: (template: WorkflowTemplate) => void | Promise<void>
}>(), { workflow: null, templates: () => [], onImport: undefined, onExport: undefined, onTemplate: undefined })

const fileInput = ref<HTMLInputElement | null>(null)
const message = ref('')
const messageKind = ref<'ok' | 'error'>('ok')
const exporting = ref(false)

function openImport(): void { fileInput.value?.click() }

async function exportCurrent(format: WorkflowExportFormat): Promise<void> {
  if (!props.workflow) return
  exporting.value = true
  try {
    const ok = props.onExport ? await props.onExport(format) : false
    messageKind.value = ok === false ? 'error' : 'ok'
    message.value = ok === false ? '当前环境不支持文件导出' : '已导出工作流 JSON'
  } catch (error) {
    messageKind.value = 'error'
    message.value = `导出失败：${error instanceof Error ? error.message : String(error)}`
  } finally {
    exporting.value = false
  }
}

async function importFile(event: Event): Promise<void> {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  try {
    const source = parseWorkflowImport(JSON.parse(await file.text()), file.name.replace(/\.json$/i, ''))
    await props.onImport?.(source)
    messageKind.value = 'ok'
    message.value = `已读取：${source.name}`
  } catch (error) {
    messageKind.value = 'error'
    message.value = `导入失败：${error instanceof Error ? error.message : String(error)}`
  }
}

function useTemplate(template: WorkflowTemplate): void {
  void props.onTemplate?.(template)
}
</script>

<style scoped>
.wf-resources { display: grid; gap: var(--space-2); padding: var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); color: var(--theme-backdrop-text); }
.wf-resources-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wf-resources-head h3 { margin: 0; font-size: 12px; font-weight: 700; }
.wf-resources-head span { display: block; margin-top: 2px; color: color-mix(in srgb, var(--theme-backdrop-text) 46%, transparent); font-size: 10px; }
.wf-resource-format { margin: 0 !important; color: var(--blue) !important; font: 10px var(--font-mono); }
.wf-resource-actions { display: flex; flex-wrap: wrap; gap: var(--space-1); }
.wf-resource-actions button { min-height: 28px; border: 0; border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); color: var(--theme-backdrop-text); padding: 0 var(--space-2); cursor: pointer; font-size: 10px; }
.wf-resource-actions button:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-active), transparent); }
.wf-resource-actions button:disabled { opacity: .4; cursor: default; }
.wf-file-input { display: none; }
.wf-resource-message { margin: 0; color: var(--green); font-size: 10px; }
.wf-resource-message.error { color: var(--red); }
.wf-templates { display: grid; gap: var(--space-1); }
.wf-templates h4 { margin: 0 0 var(--space-1); color: color-mix(in srgb, var(--theme-backdrop-text) 60%, transparent); font-size: 10px; font-weight: 650; }
.wf-template { display: grid; gap: 2px; min-height: 34px; border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--theme-backdrop-text); padding: var(--space-1) var(--space-2); text-align: left; cursor: pointer; }
.wf-template:hover, .wf-template:focus-visible { background: color-mix(in srgb, var(--theme-backdrop-text) var(--alpha-hover), transparent); outline: 0; }
.wf-template span { font-size: 10px; font-weight: 600; }
.wf-template small { color: color-mix(in srgb, var(--theme-backdrop-text) 46%, transparent); font-size: 9px; }
@media (max-width: 640px) { .wf-resource-actions button { min-height: 44px; } }
@media (prefers-reduced-motion: reduce) { .wf-resources *, .wf-resources { transition: none; animation: none; } }
</style>

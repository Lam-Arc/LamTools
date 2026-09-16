<template>
  <section v-if="hasMeaningfulEditor" class="wf-schema-editor" aria-label="节点参数">
    <header class="wf-schema-editor-head">
      <div>
        <h4>节点参数</h4>
        <p v-if="schemaDescription">{{ schemaDescription }}</p>
      </div>
      <span v-if="schema" class="wf-schema-type" :title="schema.type_id || schema.name">{{ schemaDisplayName }}</span>
    </header>
    <div v-if="fields.length" class="wf-schema-fields">
      <label v-for="field in fields" :key="field.name" class="wf-schema-field">
        <span class="wf-schema-label">{{ fieldLabel(field) }}<em v-if="field.required">必填</em></span>
        <small v-if="fieldDescription(field)">{{ fieldDescription(field) }}</small>
        <UiSelect
          v-if="field.enum?.length"
          :model-value="stringValue(fieldValue(field.name))"
          :options="enumOptions(field)"
          :aria-label="fieldLabel(field)"
          @update:model-value="setField(field, $event)"
        />
        <label v-else-if="field.type === 'boolean'" class="wf-schema-toggle">
          <input type="checkbox" :checked="Boolean(fieldValue(field.name))" @change="setField(field, ($event.target as HTMLInputElement).checked)" />
          <span>{{ Boolean(fieldValue(field.name)) ? '开启' : '关闭' }}</span>
        </label>
        <input
          v-else-if="field.type === 'number'"
          :value="fieldValue(field.name) as any"
          type="number"
          :placeholder="field.default === undefined ? '' : String(field.default)"
          @input="setField(field, ($event.target as HTMLInputElement).value)"
        />
        <AutoTextarea
          v-else-if="field.type === 'object' || field.type === 'array' || field.multiline"
          :model-value="formattedValue(fieldValue(field.name))"
          :min-rows="2"
          :max-rows="4"
          :placeholder="field.type === 'object' || field.type === 'array' ? 'JSON' : ''"
          @update:model-value="setField(field, $event)"
        />
        <input
          v-else
          :value="stringValue(fieldValue(field.name))"
          type="text"
          :placeholder="field.default === undefined ? '' : String(field.default)"
          @input="setField(field, ($event.target as HTMLInputElement).value)"
        />
      </label>
    </div>
    <button v-if="portsNeedSync" type="button" class="wf-schema-sync" @click="syncPorts">
      补齐缺少的端口（{{ missingPortCount }}）
    </button>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import UiSelect from '../../../../../../ui/src/components/UiSelect.vue'
import AutoTextarea from '../../../../../../ui/src/components/AutoTextarea.vue'
import { schemaFields, schemaPorts, workflowNodeDisplayName, type NormalizedSchemaField } from './catalog'
import type { WorkflowNodeSchema, WorkflowPort } from './types'

const props = withDefaults(defineProps<{
  schema?: WorkflowNodeSchema | null
  modelValue?: Record<string, unknown>
  ports?: WorkflowPort[]
  excludeKeys?: string[]
}>(), {
  schema: null,
  modelValue: () => ({}),
  ports: () => [],
  excludeKeys: () => [],
})
const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>]
  'update:ports': [value: WorkflowPort[]]
}>()

const values = ref<Record<string, unknown>>({ ...props.modelValue })
watch(() => props.modelValue, (next) => { values.value = { ...next } }, { deep: true })

const fields = computed(() => schemaFields(props.schema, 'input').filter((field) => !props.excludeKeys.includes(field.name)))
const expectedPorts = computed(() => schemaPorts(props.schema, props.ports))
const missingPorts = computed(() => expectedPorts.value.filter((expected) => !props.ports.some((current) => (
  current.direction === expected.direction && current.name === expected.name && current.type === expected.type
))))
const portsNeedSync = computed(() => missingPorts.value.length > 0)
const missingPortCount = computed(() => missingPorts.value.length)
const schemaDescription = computed(() => {
  const value = (props.schema as Record<string, unknown> | null | undefined)?.description_zh
    ?? props.schema?.description
  return typeof value === 'string' ? value.trim() : ''
})
const schemaDisplayName = computed(() => workflowNodeDisplayName(props.schema, '节点'))
// Descriptive schema copy belongs in the catalog/inspector summary.  Do not
// render a "节点参数" shell when the node has neither editable parameters nor
// missing ports; that was the empty, single-word configuration UI users hit
// on Output and other structural nodes.
const hasMeaningfulEditor = computed(() => fields.value.length > 0 || portsNeedSync.value)

const FIELD_LABELS: Readonly<Record<string, string>> = {
  prompt: '提示词', instruction: '指令', model_id: '模型', mode: '模式', command: '命令', script: '脚本',
  value: '值', workflow_name: '工作流', iterate: '迭代方式', event_type: '事件类型', title: '标题',
}

function fieldValue(name: string): unknown { return values.value[name] }
function stringValue(value: unknown): string { return value === undefined || value === null ? '' : String(value) }
function fieldLabel(field: NormalizedSchemaField): string {
  const localized = (field as Record<string, unknown>).title_zh
  if (typeof localized === 'string' && localized.trim()) return localized.trim()
  return FIELD_LABELS[field.name] || field.title || field.name
}
function fieldDescription(field: NormalizedSchemaField): string {
  const localized = (field as Record<string, unknown>).description_zh
  if (typeof localized === 'string' && localized.trim()) return localized.trim()
  return field.description || ''
}
function formattedValue(value: unknown): string {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value ?? '', null, 2) || '' } catch { return String(value ?? '') }
}

function enumOptions(field: NormalizedSchemaField): Array<{ value: string; label: string }> {
  return (field.enum || []).map((item) => ({ value: String(item), label: String(item) }))
}

function setField(field: NormalizedSchemaField, raw: unknown): void {
  let value = raw
  if (field.type === 'number') {
    const text = String(raw ?? '').trim()
    value = text === '' ? '' : Number(text)
    if (typeof value === 'number' && !Number.isFinite(value)) value = text
  } else if (field.type === 'object' || field.type === 'array') {
    if (typeof raw === 'string') {
      try { value = raw.trim() ? JSON.parse(raw) : field.type === 'array' ? [] : {} } catch { value = raw }
    }
  }
  values.value = { ...values.value, [field.name]: value }
  emit('update:modelValue', { ...values.value })
}

function syncPorts(): void {
  if (!portsNeedSync.value) return
  emit('update:ports', expectedPorts.value)
}
</script>

<style scoped>
.wf-schema-editor { display: grid; gap: var(--space-2); border-top: 1px solid var(--theme-main-border); padding-top: var(--space-2); }
.wf-schema-editor-head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-2); }
.wf-schema-editor h4 { margin: 0; color: var(--theme-main-text); font-size: 11px; font-weight: 700; }
.wf-schema-editor p { margin: 3px 0 0; color: color-mix(in srgb, var(--theme-main-text) 58%, transparent); font-size: 10px; line-height: 1.35; }
.wf-schema-type { flex: 0 0 auto; max-width: 45%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: color-mix(in srgb, var(--theme-main-text) 52%, transparent); font: 10px var(--font-mono); }
.wf-schema-fields { display: grid; gap: var(--space-2); }
.wf-schema-field { display: grid; gap: var(--space-1); }
.wf-schema-label { display: flex; align-items: center; gap: var(--space-1); color: color-mix(in srgb, var(--theme-main-text) 72%, transparent); font-size: 11px; }
.wf-schema-label em { color: var(--orange); font-size: 9px; font-style: normal; }
.wf-schema-field small { color: color-mix(in srgb, var(--theme-main-text) 48%, transparent); font-size: 10px; line-height: 1.3; }
.wf-schema-field input:not([type='checkbox']) { width: 100%; box-sizing: border-box; min-height: 30px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: var(--theme-composer-text); caret-color: var(--theme-composer-text); padding: 0 var(--space-2); font: inherit; font-size: 11px; outline: 0; }
.wf-schema-toggle { display: inline-flex; align-items: center; gap: var(--space-1); color: var(--theme-control-text); font-size: 11px; }
.wf-schema-toggle input { accent-color: var(--blue); }
.wf-schema-sync { min-height: 28px; border: 1px dashed color-mix(in srgb, var(--theme-main-text) 22%, transparent); border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--theme-main-text) 72%, transparent); cursor: pointer; font-size: 10px; }
.wf-schema-sync:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
@media (max-width: 640px) { .wf-schema-sync { min-height: 44px; } }
@media (prefers-reduced-motion: reduce) { .wf-schema-editor *, .wf-schema-editor { transition: none; animation: none; } }
</style>

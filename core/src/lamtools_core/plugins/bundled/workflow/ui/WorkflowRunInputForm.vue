<template>
  <section v-if="params.length" class="wf-run-inputs" aria-label="工作流运行输入">
    <header class="wf-run-input-head">
      <div>
        <h3>运行输入</h3>
        <span>按工作流 input_params 传入</span>
      </div>
      <span class="wf-run-input-count">{{ params.length }}</span>
    </header>
    <form class="wf-run-input-form" @submit.prevent="submit">
      <label v-for="param in params" :key="param.name" class="wf-run-input-field">
        <span class="wf-run-input-label">{{ param.name }}<em v-if="param.required">必填</em></span>
        <small v-if="param.description">{{ param.description }}</small>
        <label v-if="param.type === 'boolean'" class="wf-run-input-toggle">
          <input type="checkbox" :checked="Boolean(values[param.name])" @change="onBooleanChange(param.name, $event)" />
          <span>{{ values[param.name] ? '开启' : '关闭' }}</span>
        </label>
        <input
          v-else-if="param.type === 'number'"
          :value="stringValue(values[param.name])"
          type="number"
          @input="onValueInput(param.name, $event)"
        />
        <textarea
          v-else-if="param.type === 'object' || param.type === 'array'"
          :value="formattedValue(values[param.name])"
          rows="2"
          placeholder="JSON"
          @input="onValueInput(param.name, $event)"
        />
        <input v-else :value="stringValue(values[param.name])" type="text" @input="onValueInput(param.name, $event)" />
      </label>
      <p v-if="error" class="wf-run-input-error" role="alert">{{ error }}</p>
      <button class="wf-run-input-submit" type="submit" :disabled="disabled">{{ disabled ? '运行中…' : '带输入运行' }}</button>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { WorkflowInputParam } from './types'

const props = withDefaults(defineProps<{
  params?: WorkflowInputParam[]
  disabled?: boolean
}>(), {
  params: () => [],
  disabled: false,
})
const emit = defineEmits<{
  submit: [inputs: Record<string, unknown>]
}>()

const values = ref<Record<string, unknown>>({})
const error = ref('')
const signature = computed(() => props.params.map((param) => `${param.name}:${param.type}:${JSON.stringify(param.default)}`).join('|'))

watch(signature, () => {
  const next: Record<string, unknown> = {}
  for (const param of props.params) {
    if (values.value[param.name] !== undefined) next[param.name] = values.value[param.name]
    else if (param.default !== undefined) next[param.name] = param.default
    else if (param.type === 'boolean') next[param.name] = false
    else if (param.type === 'object') next[param.name] = {}
    else if (param.type === 'array') next[param.name] = []
    else next[param.name] = ''
  }
  values.value = next
  error.value = ''
}, { immediate: true })

function stringValue(value: unknown): string {
  return value === undefined || value === null ? '' : String(value)
}

function formattedValue(value: unknown): string {
  if (typeof value === 'string') return value
  try { return JSON.stringify(value ?? '', null, 2) || '' } catch { return String(value ?? '') }
}

function onValueInput(name: string, event: Event): void {
  const target = event.target
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) values.value = { ...values.value, [name]: target.value }
}

function onBooleanChange(name: string, event: Event): void {
  const target = event.target
  if (target instanceof HTMLInputElement) values.value = { ...values.value, [name]: target.checked }
}

function submit(): void {
  if (props.disabled) return
  const inputs: Record<string, unknown> = {}
  for (const param of props.params) {
    let value = values.value[param.name]
    if (param.required && (value === undefined || value === null || value === '')) {
      error.value = `请填写必填输入：${param.name}`
      return
    }
    if (param.type === 'number' && value !== '') {
      const number = Number(value)
      if (!Number.isFinite(number)) { error.value = `输入必须是数字：${param.name}`; return }
      value = number
    } else if (param.type === 'object' || param.type === 'array') {
      if (typeof value === 'string') {
        try { value = value.trim() ? JSON.parse(value) : param.type === 'array' ? [] : {} } catch { error.value = `请输入有效 JSON：${param.name}`; return }
      }
      if (param.type === 'array' && !Array.isArray(value)) { error.value = `输入必须是数组：${param.name}`; return }
      if (param.type === 'object' && (value === null || typeof value !== 'object' || Array.isArray(value))) { error.value = `输入必须是对象：${param.name}`; return }
    }
    if (value !== '' || param.required || param.default !== undefined) inputs[param.name] = value
  }
  error.value = ''
  emit('submit', inputs)
}
</script>

<style scoped>
.wf-run-inputs { display: grid; gap: var(--space-2); padding: var(--space-3); border-bottom: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); color: var(--theme-backdrop-text); }
.wf-run-input-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wf-run-input-head h3 { margin: 0; font-size: 12px; font-weight: 700; }
.wf-run-input-head span { color: color-mix(in srgb, var(--theme-backdrop-text) 46%, transparent); font-size: 10px; }
.wf-run-input-count { min-width: 20px; color: var(--blue) !important; text-align: right; }
.wf-run-input-form { display: grid; gap: var(--space-2); }
.wf-run-input-field { display: grid; gap: var(--space-1); }
.wf-run-input-label { display: flex; gap: var(--space-1); color: color-mix(in srgb, var(--theme-backdrop-text) 76%, transparent); font-size: 11px; }
.wf-run-input-label em { color: var(--orange); font-size: 9px; font-style: normal; }
.wf-run-input-field small { color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); font-size: 10px; line-height: 1.3; }
.wf-run-input-field input:not([type='checkbox']), .wf-run-input-field textarea { width: 100%; box-sizing: border-box; border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-control-background) 70%, transparent); color: var(--theme-control-text); padding: var(--space-1) var(--space-2); font: inherit; font-size: 11px; outline: 0; }
.wf-run-input-field textarea { min-height: 46px; resize: vertical; font-family: var(--font-mono); }
.wf-run-input-toggle { display: inline-flex; align-items: center; gap: var(--space-1); color: var(--theme-control-text); font-size: 11px; }
.wf-run-input-toggle input { accent-color: var(--blue); }
.wf-run-input-error { margin: 0; color: var(--red); font-size: 10px; }
.wf-run-input-submit { min-height: 30px; border: 0; border-radius: var(--radius-sm); background: var(--theme-control-background); color: var(--theme-control-text); cursor: pointer; font-size: 11px; font-weight: 650; }
.wf-run-input-submit:hover:not(:disabled) { filter: brightness(.94); }
.wf-run-input-submit:disabled { opacity: .45; cursor: default; }
@media (max-width: 640px) { .wf-run-input-submit { min-height: 44px; } }
@media (prefers-reduced-motion: reduce) { .wf-run-inputs *, .wf-run-inputs { transition: none; animation: none; } }
</style>

<template>
  <section class="plugin-config-panel" :data-plugin="pluginName">
    <header class="config-identity">
      <strong>{{ pluginName }}</strong>
      <span class="config-version">{{ version }}</span>
    </header>
    <p v-if="description" class="config-description">{{ description }}</p>

    <p v-if="error" class="config-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="config-notice">{{ notice }}</p>
    <p v-if="!loaded" class="muted">{{ t("加载配置中…") }}</p>

    <!-- user:“作者可以自定义样式”+自定义面板挂在这块空地方，宿主只提供取值存值接口。 -->
    <div
      ref="panelRoot"
      class="config-custom-panel"
      :hidden="!panelActive"
      :data-panel-active="panelActive ? 'true' : 'false'"
    ></div>

    <form v-if="loaded && !panelActive" class="config-form" @submit.prevent="save()">
      <label v-for="field in fields" :key="field.key" class="config-field">
        <span class="config-label">{{ field.label }}</span>
        <select
          v-if="field.enumValues.length"
          :value="String(draft[field.key] ?? '')"
          class="config-input"
          @change="onEnumChange(field, $event)"
        >
          <option
            v-for="value in field.enumValues"
            :key="String(value)"
            :value="value as string | number"
          >
            {{ String(value) }}
          </option>
        </select>
        <input
          v-else-if="field.type === 'boolean'"
          v-model="draft[field.key]"
          class="config-checkbox"
          type="checkbox"
        />
        <input
          v-else-if="field.type === 'number' || field.type === 'integer'"
          v-model.number="draft[field.key]"
          class="config-input"
          type="number"
          :step="field.type === 'integer' ? 1 : 'any'"
        />
        <input
          v-else-if="field.type === 'string' || !field.type"
          v-model="draft[field.key]"
          class="config-input"
          type="text"
        />
        <textarea
          v-else
          v-model="draft[field.key]"
          class="config-input config-textarea"
          rows="3"
        ></textarea>
        <small v-if="field.description" class="config-hint">{{ field.description }}</small>
      </label>

      <p v-if="!fields.length" class="muted">{{ t("这个插件没有可配置项。") }}</p>
      <div v-if="fields.length" class="config-actions">
        <button class="small-btn" type="submit" :disabled="saving">
          {{ saving ? t("保存中…") : t("保存配置") }}
        </button>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import { t } from '../i18n/index'

interface PluginConfigField {
  key: string
  label: string
  description: string
  type: string
  enumValues: unknown[]
}

interface PluginPanelApi {
  plugin: { name: string; version: string; description: string }
  config: Record<string, unknown>
  schema: Record<string, unknown>
  save: (values: Record<string, unknown>) => Promise<void>
}

interface PluginPanelModule {
  mount?: (root: HTMLElement, api: PluginPanelApi) => void
}

type PluginRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = defineProps<{
  pluginName: string
  version: string
  description: string
  requestRpc: PluginRpc
}>()

const loaded = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const schema = ref<Record<string, unknown>>({})
// 表单控件值类型各不相同，草稿用宽类型，提交前再按 schema 还原。
type ConfigDraftValue = string | number | boolean | null
const draft = reactive<Record<string, any>>({})
const panelUrl = ref('')
const hasPanel = ref(false)
const panelActive = ref(false)
const panelRoot = ref<HTMLElement | null>(null)

function schemaProperties(): Record<string, Record<string, unknown>> {
  const properties = schema.value.properties
  if (!properties || typeof properties !== 'object') return {}
  const result: Record<string, Record<string, unknown>> = {}
  for (const [key, value] of Object.entries(properties as Record<string, unknown>)) {
    if (value && typeof value === 'object') {
      result[key] = value as Record<string, unknown>
    }
  }
  return result
}

const fields = computed<PluginConfigField[]>(() =>
  Object.entries(schemaProperties()).map(([key, property]) => ({
    key,
    label: String(property.title || key),
    description: String(property.description || ''),
    type: String(property.type || ''),
    enumValues: Array.isArray(property.enum) ? property.enum : [],
  })),
)

function draftValue(value: unknown): ConfigDraftValue {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value
  }
  return JSON.stringify(value)
}

function applyValues(values: Record<string, unknown>): void {
  for (const key of Object.keys(schemaProperties())) {
    const fallback = schemaProperties()[key]?.default
    draft[key] = draftValue(values[key] !== undefined ? values[key] : fallback)
  }
  for (const [key, value] of Object.entries(values)) {
    if (!(key in draft)) draft[key] = draftValue(value)
  }
}

function onEnumChange(field: PluginConfigField, event: Event): void {
  const select = event.target as HTMLSelectElement
  draft[field.key] = draftValue(field.enumValues[select.selectedIndex])
}

function collectValues(): Record<string, unknown> {
  const values: Record<string, unknown> = { ...draft }
  for (const [key, property] of Object.entries(schemaProperties())) {
    const type = String(property.type || '')
    const value = values[key]
    if ((type === 'array' || type === 'object') && typeof value === 'string') {
      const text = value.trim()
      if (!text) {
        delete values[key]
        continue
      }
      try {
        values[key] = JSON.parse(text)
      } catch {
        throw new Error(t("字段 {0} 需要合法的 JSON。", { 0: key }))
      }
    }
  }
  return values
}

async function save(values?: Record<string, unknown>): Promise<void> {
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const config = values ?? collectValues()
    await props.requestRpc('plugin.system.config.update', {
      name: props.pluginName,
      config,
    })
    applyValues(config)
    notice.value = t("已保存 {0} 的配置。", { 0: props.pluginName })
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

function panelModule(): PluginPanelModule | null {
  const registry = (window as unknown as {
    LamToolsPluginPanels?: Record<string, PluginPanelModule>
  }).LamToolsPluginPanels
  return registry?.[props.pluginName] ?? null
}

function loadPanelScript(url: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-plugin-config-panel="${url}"]`)) {
      resolve()
      return
    }
    const script = document.createElement('script')
    script.src = url
    script.dataset.pluginConfigPanel = url
    script.onload = () => resolve()
    script.onerror = () => reject(new Error(t("自定义配置面板加载失败：{0}", { 0: url })))
    document.head.appendChild(script)
  })
}

async function mountPanel(): Promise<void> {
  if (!hasPanel.value || !panelUrl.value) return
  try {
    await loadPanelScript(panelUrl.value)
    const module = panelModule()
    if (!module?.mount || !panelRoot.value) return
    panelActive.value = true
    await nextTick()
    module.mount(panelRoot.value, {
      plugin: {
        name: props.pluginName,
        version: props.version,
        description: props.description,
      },
      config: { ...draft },
      schema: schema.value,
      save: async (values: Record<string, unknown>) => {
        await save(values)
      },
    })
  } catch (cause) {
    panelActive.value = false
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(async () => {
  try {
    const payload = await props.requestRpc('plugin.system.config.get', {
      name: props.pluginName,
    })
    schema.value = (payload.schema as Record<string, unknown>) || {}
    hasPanel.value = payload.has_panel === true
    panelUrl.value = String(payload.panel_url || '')
    applyValues((payload.config as Record<string, unknown>) || {})
    loaded.value = true
    await mountPanel()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    loaded.value = true
  }
})
</script>

<style scoped>
.plugin-config-panel {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius);
  padding: 10px 12px;
  display: grid;
  gap: 8px;
}

.config-identity {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.config-version {
  font-size: 12px;
  opacity: 0.6;
}

.config-description {
  margin: 0;
  font-size: 12px;
  opacity: 0.8;
}

.config-error {
  color: var(--red);
}

.config-notice {
  color: var(--green);
}

.config-form {
  display: grid;
  gap: 8px;
}

.config-field {
  display: grid;
  gap: 2px;
}

.config-label {
  font-size: 12px;
  opacity: 0.8;
}

.config-input {
  width: 100%;
}

.config-checkbox {
  width: auto;
}

.config-textarea {
  resize: vertical;
}

.config-hint {
  font-size: 11px;
  opacity: 0.6;
}

.config-actions {
  display: flex;
  gap: 8px;
}
</style>

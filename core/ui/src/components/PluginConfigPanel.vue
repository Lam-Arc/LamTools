<template>
  <section class="plugin-config-panel" :data-plugin="pluginName">
    <header v-if="showIdentity" class="config-identity">
      <strong>{{ pluginName }}</strong>
      <span class="config-version">{{ version }}</span>
    </header>
    <p v-if="showIdentity && description" class="config-description">{{ description }}</p>

    <p v-if="error" class="config-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="config-notice" role="status">{{ notice }}</p>
    <p v-if="!loaded" class="config-loading" role="status">
      <span class="config-loading-dot" aria-hidden="true"></span>
      {{ t("加载配置中…") }}
    </p>

    <!-- user:“作者可以自定义样式”+自定义面板挂在这块空地方，宿主只提供取值存值接口。 -->
    <div
      ref="panelRoot"
      class="config-custom-panel"
      :hidden="!panelActive"
      :data-panel-active="panelActive ? 'true' : 'false'"
    ></div>

    <form v-if="loaded && !panelActive" class="config-form" @submit.prevent="save()">
      <label
        v-for="field in fields"
        :key="field.key"
        class="config-field"
        :class="{ 'is-boolean': field.type === 'boolean' }"
      >
        <span class="config-label-row">
          <span class="config-label">{{ field.label }}</span>
          <small v-if="field.description" class="config-hint">{{ field.description }}</small>
        </span>
        <!-- user:“配置界面里面自带的那些样式……比如选中键、下拉框之类的”+
             枚举值走统一的下拉控件，选中行、展开动画和主题色都与设置页一致。 -->
        <UiSelect
          v-if="field.enumValues.length"
          class="config-select"
          :model-value="String(draft[field.key] ?? '')"
          :options="enumOptions(field)"
          :aria-label="field.label"
          :menu-min-width="0"
          @update:model-value="onEnumSelect(field, $event)"
        />
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
      </label>

      <p v-if="!fields.length" class="config-empty">{{ t("这个插件没有可配置项。") }}</p>
      <div v-if="fields.length" class="config-actions">
        <button class="btn btn--primary" type="submit" :disabled="saving">
          {{ saving ? t("保存中…") : t("保存配置") }}
        </button>
      </div>
    </form>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { consentRpc } from '@/plugins/consent'
import { pluginAssetUrl } from '@/plugins/assets'
import UiSelect from '@/components/UiSelect.vue'

import { t } from '@/i18n/index.ts'

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
  rpc: PluginRpc
  signal: AbortSignal
}

interface PluginPanelModule {
  mount?: (root: HTMLElement, api: PluginPanelApi) => void | (() => void) | Promise<void | (() => void)>
}

type PluginRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = withDefaults(defineProps<{
  pluginName: string
  version: string
  description: string
  requestRpc: PluginRpc
  /** 插件页的卡片已经展示身份，抽屉里只留表单本身。 */
  showIdentity?: boolean
}>(), {
  showIdentity: true,
})
const panelController = new AbortController()
let panelCleanup: (() => void) | undefined
onBeforeUnmount(() => { panelController.abort(); panelCleanup?.() })

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

function enumOptions(field: PluginConfigField): Array<{ value: string; label: string }> {
  return field.enumValues.map(value => ({ value: String(value), label: String(value) }))
}

function onEnumSelect(field: PluginConfigField, value: string): void {
  // 枚举值可能是数字/布尔，回到原始类型再写进草稿，提交时不被改成字符串。
  const original = field.enumValues.find(item => String(item) === value)
  draft[field.key] = draftValue(original !== undefined ? original : value)
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
  url = pluginAssetUrl(url)
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-plugin-config-panel="${url}"]`)) {
      const existing = document.querySelector<HTMLScriptElement>(`script[data-plugin-config-panel="${url}"]`)!
      if (existing.dataset.loaded === 'true') resolve()
      else if (existing.dataset.failed === 'true') reject(new Error(t('自定义配置面板加载失败')))
      else {
        existing.addEventListener('load', () => resolve(), { once: true })
        existing.addEventListener('error', () => reject(new Error(t('自定义配置面板加载失败'))), { once: true })
      }
      return
    }
    const script = document.createElement('script')
    script.src = url
    script.dataset.pluginConfigPanel = url
    script.onload = () => { script.dataset.loaded = 'true'; resolve() }
    script.onerror = () => { script.dataset.failed = 'true'; reject(new Error(t("自定义配置面板加载失败：{0}", { 0: url }))) }
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
    if (panelController.signal.aborted) return
    const cleanup = await module.mount(panelRoot.value, {
      plugin: {
        name: props.pluginName,
        version: props.version,
        description: props.description,
      },
      config: { ...draft },
      schema: schema.value,
      rpc: consentRpc(props.requestRpc, panelController.signal),
      signal: panelController.signal,
      save: async (values: Record<string, unknown>) => {
        await save(values)
      },
    })
    if (typeof cleanup === 'function') {
      if (panelController.signal.aborted) cleanup()
      else panelCleanup = cleanup
    }
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
  display: grid;
  gap: var(--space-2);
  min-width: 0;
  color: var(--settings-main-text, var(--text));
}

.config-identity {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.config-identity strong {
  font-size: 13px;
}

.config-version {
  color: color-mix(in srgb, var(--settings-main-text, var(--text)) 48%, transparent);
  font-family: var(--font-mono);
  font-size: 10.5px;
}

.config-description {
  margin: 0;
  color: color-mix(in srgb, var(--settings-main-text, var(--text)) 60%, transparent);
  font-size: 11.5px;
  line-height: 1.5;
}

.config-error,
.config-notice {
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  line-height: 1.5;
}

.config-error {
  border: 1px solid color-mix(in srgb, var(--red) 24%, transparent);
  background: color-mix(in srgb, var(--red) 7%, transparent);
  color: color-mix(in srgb, var(--red) 68%, var(--settings-main-text, var(--text)));
}

.config-notice {
  border: 1px solid color-mix(in srgb, var(--green) 22%, transparent);
  background: color-mix(in srgb, var(--green) 7%, transparent);
  color: color-mix(in srgb, var(--green) 58%, var(--settings-main-text, var(--text)));
}

.config-loading {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  color: color-mix(in srgb, var(--settings-main-text, var(--text)) 52%, transparent);
  font-size: 11.5px;
}

.config-loading-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
  animation: config-loading-pulse 1.3s var(--ease-out) infinite;
}

.config-form {
  display: grid;
  gap: var(--space-3);
  padding-top: var(--space-1);
}

.config-field {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.config-label-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.config-label {
  color: color-mix(in srgb, var(--settings-main-text, var(--text)) 78%, transparent);
  font-size: 11.5px;
  font-weight: 640;
}

/* 下拉复用 UiSelect，只把控件色映射到设置卡片，避免亮底按钮混在暗色表单里。 */
.config-select {
  --settings-control-solid: var(--settings-card-background, #1b1c1c);
  --settings-control-text: var(--settings-main-text, var(--text));
}

.config-select :deep(.ui-select-trigger) {
  min-height: 32px;
  font-size: 12px;
}

.config-input {
  width: 100%;
  min-height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--text)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--text)) 3.5%, transparent);
  color: var(--settings-main-text, var(--text));
  font: inherit;
  font-size: 12px;
}

textarea.config-input {
  min-height: 64px;
  padding: var(--space-2);
  resize: vertical;
  line-height: 1.5;
}

/* 布尔项排成一行：说明在左，选中键在右，不再把复选框单独丢到下一行。 */
.config-field.is-boolean {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--space-3);
}

.config-field.is-boolean .config-label-row {
  grid-column: 1;
}

.config-field.is-boolean .config-checkbox {
  grid-column: 2;
  grid-row: 1;
}

.config-checkbox {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  margin: 0;
  display: grid;
  place-content: center;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--text)) 26%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, var(--text)) 5%, transparent);
  color: var(--settings-main-text, var(--text));
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}

.config-checkbox::before {
  content: '';
  width: 10px;
  height: 5px;
  border-left: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
  transform: rotate(-45deg) scale(0);
  transform-origin: center;
  transition: transform var(--dur-fast) var(--ease-out);
}

.config-checkbox:hover {
  border-color: color-mix(in srgb, var(--settings-main-text, var(--text)) 42%, transparent);
}

.config-checkbox:checked {
  border-color: transparent;
  background: color-mix(in srgb, var(--green) 76%, var(--settings-card-background, #1b1c1c));
}

.config-checkbox:checked::before {
  transform: rotate(-45deg) scale(1);
}

.config-checkbox:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
}

.config-hint {
  color: color-mix(in srgb, var(--settings-main-text, var(--text)) 46%, transparent);
  font-size: 10.5px;
  line-height: 1.45;
}

.config-empty {
  margin: 0;
  padding: var(--space-2) 0;
  color: color-mix(in srgb, var(--settings-main-text, var(--text)) 50%, transparent);
  font-size: 11.5px;
}

.config-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}

.config-actions .btn--secondary:disabled {
  opacity: .45;
  cursor: default;
}

.config-custom-panel[hidden] {
  display: none;
}

@keyframes config-loading-pulse {
  0%, 100% { opacity: .35; }
  50% { opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .config-loading-dot {
    animation: none;
  }

  .config-checkbox,
  .config-checkbox::before {
    transition: none;
  }
}
</style>

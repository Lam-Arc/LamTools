<template>
  <div v-if="regions.length" class="plugin-region-blocks">
    <section
      v-for="region in regions"
      :key="`${region.plugin}:${region.region}:${region.order}`"
      class="plugin-region-card"
      :class="{ 'plugin-region-card--replaced': region.replace }"
      :data-plugin="region.plugin"
      :data-region-contribution="region.region"
    >
      <header v-if="region.plugin && !region.entryUrl" class="plugin-region-head">
        <strong>{{ region.plugin }}</strong>
        <span v-if="region.mode" class="plugin-region-mode">{{ region.mode }}</span>
      </header>

      <!-- user:“自绘内容”+声明了 entry 的区域给插件一个空盒并注入模块脚本，
           插件自己往盒子里画；脚本每地址只执行一次。 -->
      <div
        v-if="region.entryUrl"
        class="plugin-region-entry"
        :data-plugin-entry="region.plugin"
        :data-entry-url="region.entryUrl"
      >
        <!-- 插件脚本自行填充此容器 -->
      </div>

      <div
        v-for="(block, index) in region.blocks"
        :key="index"
        class="plugin-block"
        :class="`plugin-block--${block.type}`"
      >
        <template v-if="block.type === 'status'">
          <span class="plugin-block-label">{{ block.label || t("状态") }}</span>
          <strong :data-state="block.state || undefined">{{ block.value ?? block.state ?? t("未知") }}</strong>
        </template>

        <template v-else-if="block.type === 'metric'">
          <span class="plugin-block-label">{{ block.label }}</span>
          <strong>{{ formatValue(block.value) }}</strong>
          <small v-if="block.detail">{{ block.detail }}</small>
        </template>

        <template v-else-if="block.type === 'progress'">
          <span class="plugin-block-label">{{ block.label }}</span>
          <strong>{{ progressLabel(block) }}</strong>
          <div class="plugin-block-track" role="progressbar" :aria-valuenow="numberValue(block.value)" :aria-valuemax="block.max ?? 100">
            <span :style="{ transform: `scaleX(${progressRatio(block)})` }"></span>
          </div>
          <small v-if="block.detail">{{ block.detail }}</small>
        </template>

        <template v-else-if="block.type === 'list'">
          <span v-if="block.label" class="plugin-block-label">{{ block.label }}</span>
          <ul class="plugin-block-list">
            <li v-for="(item, itemIndex) in block.items" :key="itemIndex">{{ itemLabel(item) }}</li>
          </ul>
        </template>

        <template v-else>
          <span v-if="block.label" class="plugin-block-label">{{ block.label }}</span>
          <span>{{ block.text || formatValue(block.value) }}</span>
        </template>
      </div>

      <div v-if="region.actions.length" class="plugin-region-actions">
        <button
          v-for="action in region.actions"
          :key="action.id"
          type="button"
          class="small-btn"
          :class="{ 'is-danger': action.dangerous }"
          :disabled="busy === action.id"
          :data-action="action.id"
          :title="action.mutates ? t('会修改数据') : undefined"
          @click="invoke(action, region)"
        >
          {{ action.title }}
        </button>
      </div>

      <!-- user:“声明了入参的操作”+执行前收集参数：文本/数字/开关三型小表单。 -->
      <form
        v-if="pendingAction && pendingAction.region === region.region && pendingAction.plugin === region.plugin"
        class="plugin-action-form"
        @submit.prevent="submitPending()"
      >
        <label v-for="(field, name) in pendingFields" :key="name" class="plugin-action-field">
          <span>{{ field.title || name }}</span>
          <input
            v-if="field.type === 'boolean'"
            v-model="pendingValues[name]"
            type="checkbox"
          />
          <input
            v-else-if="field.type === 'number'"
            v-model="pendingValues[name]"
            type="number"
            :required="field.required || undefined"
          />
          <input
            v-else
            v-model="pendingValues[name]"
            type="text"
            :required="field.required || undefined"
          />
        </label>
        <div class="plugin-action-form-actions">
          <button class="small-btn" type="submit" :disabled="busy !== ''">{{ t("执行") }}</button>
          <button class="text-btn" type="button" @click="pendingAction = null">{{ t("取消") }}</button>
        </div>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import { t } from '@/i18n/index.ts'
import { injectScript, type PluginAction, type PluginBlock, type PluginRegionContribution } from '@/plugins/contributions.ts'

interface RegionView extends PluginRegionContribution {
  entryUrl: string
}

const props = defineProps<{
  regions: PluginRegionContribution[]
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const viewRegions = computed<RegionView[]>(() =>
  props.regions.map((region) => ({ ...region, entryUrl: region.entry_url || '' })),
)

const regions = viewRegions

const busy = ref('')

// entry 脚本注入：每地址一次。
watch(
  () => viewRegions.value.map((region) => region.entryUrl).filter(Boolean),
  (urls) => {
    for (const url of urls) injectScript(url)
  },
  { immediate: true },
)

interface ActionField {
  title: string
  type: string
  required: boolean
}

const pendingAction = ref<{ plugin: string; region: string; action: PluginAction } | null>(null)
const pendingValues = ref<Record<string, unknown>>({})

const pendingFields = computed<Record<string, ActionField>>(() => {
  const action = pendingAction.value?.action
  if (!action) return {}
  const schema = action.input_schema
  const properties =
    schema && typeof schema === 'object' && (schema as { properties?: Record<string, Record<string, unknown>> }).properties
      ? (schema as { properties: Record<string, Record<string, unknown>> }).properties
      : {}
  const fields: Record<string, ActionField> = {}
  for (const [name, property] of Object.entries(properties)) {
    fields[name] = {
      title: String(property.title || property.description || name),
      type: String(property.type || 'string'),
      required: Boolean(property.required) || false,
    }
    pendingValues.value[name] = property.type === 'boolean' ? false : ''
  }
  return fields
})

function coerce(name: string, field: ActionField): unknown {
  const value = pendingValues.value[name]
  if (field.type === 'number') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }
  if (field.type === 'boolean') return Boolean(value)
  return String(value ?? '')
}

async function runOperation(action: PluginAction, payload: Record<string, unknown>): Promise<void> {
  busy.value = action.id
  try {
    await props.requestRpc(action.operation, payload)
  } catch (cause) {
    console.warn('[plugin-region] action failed:', action.operation, cause)
  } finally {
    busy.value = ''
  }
}

async function submitPending(): Promise<void> {
  const pending = pendingAction.value
  if (!pending) return
  const payload: Record<string, unknown> = {}
  for (const [name, field] of Object.entries(pendingFields.value)) {
    if (field.required && coerce(name, field) === '') {
      return
    }
    payload[name] = coerce(name, field)
  }
  pendingAction.value = null
  await runOperation(pending.action, payload)
}

async function invoke(action: PluginAction, region: PluginRegionContribution): Promise<void> {
  // user:“危险操作先确认”+dangerous 标记的按钮点击先弹确认再执行。
  if (action.dangerous) {
    const label = action.mutates ? t("确定执行 {0}？该操作会修改数据。", { 0: action.title }) : t("确定执行 {0}？", { 0: action.title })
    if (!window.confirm(label)) return
  }
  const schema = action.input_schema as { properties?: Record<string, unknown> } | undefined
  if (schema && schema.properties && Object.keys(schema.properties).length > 0) {
    pendingValues.value = {}
    pendingAction.value = { plugin: region.plugin, region: region.region, action }
    return
  }
  await runOperation(action, {})
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function itemLabel(item: unknown): string {
  if (typeof item === 'string') return item
  if (item && typeof item === 'object') {
    const record = item as Record<string, unknown>
    const title = String(record.title ?? record.text ?? record.name ?? '').trim()
    const detail = String(record.detail ?? record.description ?? '').trim()
    if (title && detail) return `${title} · ${detail}`
    return title || detail || formatValue(item)
  }
  return formatValue(item)
}

function numberValue(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function progressRatio(block: PluginBlock): number {
  const max = block.max && block.max > 0 ? block.max : 100
  return Math.max(0, Math.min(1, numberValue(block.value) / max))
}

function progressLabel(block: PluginBlock): string {
  const max = block.max && block.max > 0 ? block.max : 100
  return `${numberValue(block.value)} / ${max}`
}
</script>

<style scoped>
.plugin-region-blocks {
  display: grid;
  gap: 8px;
}

.plugin-region-card {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius);
  padding: 10px 12px;
  display: grid;
  gap: 8px;
}

.plugin-region-card--replaced {
  border-style: dashed;
}

.plugin-region-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.plugin-region-mode {
  opacity: 0.6;
}

.plugin-region-entry {
  min-height: 24px;
}

.plugin-block {
  display: grid;
  gap: 2px;
  font-size: 13px;
}

.plugin-block-label {
  font-size: 11px;
  opacity: 0.6;
}

.plugin-block-track {
  background: color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  border-radius: 999px;
  height: 4px;
  overflow: hidden;
}

.plugin-block-track > span {
  background: var(--blue);
  display: block;
  height: 100%;
  transform-origin: left center;
}

.plugin-block-list {
  margin: 0;
  padding-left: 16px;
}

.plugin-region-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.plugin-action-form {
  display: grid;
  gap: 6px;
  font-size: 12px;
  border-top: 1px dashed color-mix(in srgb, var(--theme-main-text) 15%, transparent);
  padding-top: 6px;
}

.plugin-action-field {
  display: grid;
  gap: 2px;
}

.plugin-action-form-actions {
  display: flex;
  gap: 8px;
}

.is-danger {
  color: var(--red);
}
</style>

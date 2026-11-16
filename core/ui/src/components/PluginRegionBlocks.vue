<template>
  <div v-if="regions.length" class="plugin-region-blocks" :class="{ 'plugin-region-blocks--fill': props.fill }">
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
      <PluginRegionEntry v-if="region.entryUrl" :plugin="region.plugin" :entry-url="region.entryUrl" :request-rpc="props.requestRpc" />

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
          <!-- user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(插件进度复用主题进度条并保留数值语义) -->
          <SundayProgress :value="block.value" :max="block.max" :label="block.label || undefined" />
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

      <!-- user:“确保视觉、功能和交互不退化”+(失败直接显示在对应插件区域，便于修改后重试)。 -->
      <p v-if="actionError && actionError.plugin === region.plugin && actionError.region === region.region" class="plugin-action-error" role="alert">{{ actionError.message }}</p>
      <div v-if="region.actions.length" class="plugin-region-actions">
        <button
          v-for="action in region.actions"
          :key="action.id"
          type="button"
          class="btn btn--secondary"
          :class="{ 'is-danger': action.dangerous }"
          :disabled="Boolean(busy)"
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
            class="sunday-checkbox"
            type="checkbox"
            :disabled="Boolean(busy)"
          />
          <input
            v-else-if="field.type === 'number'"
            v-model="pendingValues[name]"
            type="number"
            step="any"
            :disabled="Boolean(busy)"
            :required="field.required || undefined"
          />
          <input
            v-else
            v-model="pendingValues[name]"
            type="text"
            :disabled="Boolean(busy)"
            :required="field.required || undefined"
          />
        </label>
        <div class="plugin-action-form-actions">
          <button class="btn btn--secondary" type="submit" :disabled="busy !== ''">{{ t("执行") }}</button>
          <button class="btn btn--ghost" type="button" :disabled="Boolean(busy)" @click="pendingAction = null">{{ t("取消") }}</button>
        </div>
      </form>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import PluginRegionEntry from './PluginRegionEntry.vue'
import SundayProgress from '@/components/SundayProgress.vue'
import { progressMetrics } from '@/helpers/progressMetrics.ts'
import { consentRpc, confirmPluginOperation } from '@/plugins/consent'

import { t } from '@/i18n/index.ts'
import { type PluginAction, type PluginBlock, type PluginRegionContribution } from '@/plugins/contributions.ts'

interface RegionView extends PluginRegionContribution {
  entryUrl: string
}

const props = defineProps<{
  regions: PluginRegionContribution[]
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** 整栏接管场景：容器撑满并自带滚动，内容再多也不溢出。 */
  fill?: boolean
}>()

const viewRegions = computed<RegionView[]>(() =>
  props.regions.map((region) => ({ ...region, entryUrl: region.entry_url || '' })),
)

const regions = viewRegions

// user:“确保视觉、功能和交互不退化”+(区域卸载时终止待处理授权，避免离开后执行)。
const actionController = new AbortController()
onBeforeUnmount(() => actionController.abort())
const busy = ref('')
const actionError = ref<{ plugin: string; region: string; message: string } | null>(null)

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
  // user:“确保视觉、功能和交互不退化”+(同时识别标准声明与原有字段级必填标记)。
  const requiredNames = Array.isArray(schema?.required) ? new Set(schema.required.map(String)) : new Set<string>()
  const fields: Record<string, ActionField> = {}
  for (const [name, property] of Object.entries(properties)) {
    fields[name] = {
      title: String(property.title || property.description || name),
      type: String(property.type || 'string'),
      required: property.required === true || requiredNames.has(name),
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

// user:“确保视觉、功能和交互不退化”+(动作失败可见且保留参数，运行期间避免并发覆盖状态)。
async function runOperation(action: PluginAction, payload: Record<string, unknown>, target: { plugin: string; region: string }): Promise<boolean> {
  if (busy.value) return false
  busy.value = action.id
  actionError.value = null
  try {
    await consentRpc(props.requestRpc, actionController.signal)(action.operation, payload)
    return true
  } catch (cause) {
    if (!actionController.signal.aborted) actionError.value = { plugin: target.plugin, region: target.region, message: cause instanceof Error ? cause.message : String(cause) }
    return false
  } finally {
    busy.value = ''
  }
}

async function submitPending(): Promise<void> {
  const pending = pendingAction.value
  if (!pending) return
  const payload: Record<string, unknown> = {}
  for (const [name, field] of Object.entries(pendingFields.value)) {
    // user:“确保视觉、功能和交互不退化”+(空数值不能被转换为零后绕过必填，false 和零仍有效)。
    if (field.required && (pendingValues.value[name] === '' || pendingValues.value[name] == null)) {
      return
    }
    payload[name] = coerce(name, field)
  }
  if (await runOperation(pending.action, payload, pending)) pendingAction.value = null
}

async function invoke(action: PluginAction, region: PluginRegionContribution): Promise<void> {
  if (busy.value) return
  actionError.value = null
  // user:“危险操作先确认”+dangerous 标记的按钮点击先弹确认再执行。
  if (action.dangerous) {
    const label = action.mutates ? t("确定执行 {0}？该操作会修改数据。", { 0: action.title }) : t("确定执行 {0}？", { 0: action.title })
    if (!await confirmPluginOperation(action.title, label, actionController.signal)) return
  }
  const schema = action.input_schema as { properties?: Record<string, unknown> } | undefined
  if (schema && schema.properties && Object.keys(schema.properties).length > 0) {
    pendingValues.value = {}
    pendingAction.value = { plugin: region.plugin, region: region.region, action }
    return
  }
  await runOperation(action, {}, region)
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

function progressLabel(block: PluginBlock): string {
  const { raw, maximum } = progressMetrics(block.value, block.max)
  return `${raw} / ${maximum}`
}
</script>

<style scoped>
.plugin-region-blocks {
  display: grid;
  gap: 8px;
}

.plugin-region-blocks--fill {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  align-content: start;
  padding-right: 2px;
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

.plugin-block-list {
  margin: 0;
  padding-left: 16px;
}

.plugin-action-error { margin: 0; color: var(--red); font-size: 12px; }
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

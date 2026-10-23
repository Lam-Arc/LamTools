<template>
  <div v-if="regions.length" class="plugin-region-blocks">
    <section
      v-for="region in regions"
      :key="`${region.plugin}:${region.region}:${region.order}`"
      class="plugin-region-card"
      :data-plugin="region.plugin"
      :data-region-contribution="region.region"
    >
      <header v-if="region.plugin" class="plugin-region-head">
        <strong>{{ region.plugin }}</strong>
        <span v-if="region.mode" class="plugin-region-mode">{{ region.mode }}</span>
      </header>

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
          :title="action.mutates ? t('会修改数据') : undefined"
          @click="invoke(action)"
        >
          {{ action.title }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { t } from '../i18n/index'

interface PluginBlock {
  type: string
  label: string
  value: unknown
  text: string
  state: string
  items: unknown[]
  detail: string
  max?: number
}

interface PluginAction {
  id: string
  title: string
  operation: string
  dangerous?: boolean
  mutates?: boolean
}

interface PluginRegionContribution {
  plugin: string
  region: string
  order: number
  mode: string
  replace: boolean
  blocks: PluginBlock[]
  actions: PluginAction[]
}

type PluginRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = defineProps<{
  regions: PluginRegionContribution[]
  requestRpc: PluginRpc
}>()

const busy = ref('')

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

async function invoke(action: PluginAction): Promise<void> {
  busy.value = action.id
  try {
    await props.requestRpc(action.operation, {})
  } catch (cause) {
    console.warn('[plugin-region] action failed:', action.operation, cause)
  } finally {
    busy.value = ''
  }
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

.plugin-region-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
}

.plugin-region-mode {
  opacity: 0.6;
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

.is-danger {
  color: var(--red);
}
</style>

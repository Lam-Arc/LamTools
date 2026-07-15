<template>
  <div class="right-panel-root">
    <section
      v-for="group in panelGroups"
      :key="group.id"
      class="side-section"
    >
      <h3>{{ group.label }}</h3>
      <div class="activity-item" v-for="item in group.items" :key="item.label">
        <span class="activity-kind">{{ item.label }}</span>
        <span class="activity-text">{{ formatPanelValue(item.value) }}</span>
      </div>
    </section>

    <section v-if="showEvents && events.length > 0" class="side-section">
      <h3>事件</h3>
      <div class="activity-item" v-for="event in recentEvents" :key="event.id">
        <span class="activity-kind">{{ event.type }}</span>
        <span class="activity-text">{{ formatPanelValue(event.data) }}</span>
      </div>
    </section>

    <template v-if="visibleStepGroups.length > 0">
      <section class="side-section">
        <h3>过程</h3>
        <div v-for="group in visibleStepGroups" :key="group.id" class="runtime-panel__group">
          <div class="runtime-panel__group-header">
            <span>{{ group.label }}</span>
            <span class="runtime-panel__group-status">{{ formatStatus(group.status) }}</span>
          </div>
          <div
            v-for="step in visibleSteps(group)"
            :key="step.id"
            class="runtime-panel__step"
          >
            <div class="runtime-panel__step-title">{{ step.title }}</div>
            <div class="runtime-panel__step-status">{{ formatStatus(step.status) }}</div>
          </div>
          <button
            v-if="group.steps.length > stepLimit"
            type="button"
            class="runtime-panel__more"
            @click="toggleGroup(group.id)"
          >
            {{ expandedGroupIds.has(group.id) ? '收起' : `查看其余 ${group.steps.length - stepLimit} 步` }}
          </button>
        </div>
      </section>
    </template>

    <!-- Product slots for fully custom sections -->
    <slot name="custom-sections" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CoreRuntimeEvent, CoreRuntimeStepGroup } from '../types'

export interface PanelInfoItem {
  label: string
  value: unknown
}

export interface PanelGroup {
  id: string
  label: string
  items: PanelInfoItem[]
}

const props = withDefaults(
  defineProps<{
    panelGroups?: PanelGroup[]
    events?: CoreRuntimeEvent[]
    stepGroups?: CoreRuntimeStepGroup[]
    showEvents?: boolean
    stepLimit?: number
  }>(),
  {
    panelGroups: () => [],
    events: () => [],
    stepGroups: () => [],
    showEvents: false,
    stepLimit: 3,
  },
)

const recentEvents = computed(() => props.events.slice(-12).reverse())
const visibleStepGroups = computed(() => props.stepGroups.filter((group) => group.steps.length > 0))
const expandedGroupIds = ref(new Set<string>())

function visibleSteps(group: CoreRuntimeStepGroup) {
  return expandedGroupIds.value.has(group.id) ? group.steps : group.steps.slice(-props.stepLimit)
}

function toggleGroup(groupId: string) {
  const next = new Set(expandedGroupIds.value)
  if (next.has(groupId)) next.delete(groupId)
  else next.add(groupId)
  expandedGroupIds.value = next
}

function formatStatus(status: string): string {
  return ({
    pending: '待处理',
    running: '运行中',
    waiting: '等待中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过',
    cancelled: '已取消',
  } as Record<string, string>)[status] || status
}

function formatPanelValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return '无法显示'
  }
}
</script>

<style scoped>
.right-panel-root { display: grid; gap: 0; }
.runtime-panel__group { display: grid; gap: 8px; }
.runtime-panel__group + .runtime-panel__group { margin-top: 12px; padding-top: 12px; border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); }
.runtime-panel__group-header, .runtime-panel__step { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 10px; }
.runtime-panel__group-header { color: var(--theme-backdrop-text); font-size: 13px; font-weight: 700; }
.runtime-panel__group-status { color: var(--green); font-size: 12px; font-weight: 700; }
.runtime-panel__step { padding: 3px 0; color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent); font-size: 12px; }
.runtime-panel__step-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runtime-panel__step-status { color: color-mix(in srgb, var(--theme-backdrop-text) 48%, transparent); }
.runtime-panel__more { justify-self: start; border: 0; background: transparent; color: color-mix(in srgb, var(--theme-backdrop-text) 58%, transparent); padding: 2px 0; font: inherit; font-size: 12px; cursor: pointer; }
.runtime-panel__more:hover { color: var(--theme-backdrop-text); }
.runtime-panel__more:focus-visible { outline: 2px solid color-mix(in srgb, var(--green) 48%, transparent); outline-offset: 3px; }
</style>

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

    <section v-if="events.length > 0" class="side-section">
      <h3>Events</h3>
      <div class="activity-item" v-for="event in recentEvents" :key="event.id">
        <span class="activity-kind">{{ event.type }}</span>
        <span class="activity-text">{{ formatPanelValue(event.data) }}</span>
      </div>
    </section>

    <!-- Step groups (collapsible runtime steps) -->
    <template v-if="stepGroups && stepGroups.length > 0">
      <section class="side-section">
        <h3>Steps</h3>
        <div v-for="group in stepGroups" :key="group.id" class="runtime-panel__group">
          <div class="runtime-panel__group-header">
            <span>{{ group.label }}</span>
            <span class="runtime-panel__group-status">{{ group.status }}</span>
          </div>
          <div
            v-for="step in group.steps"
            :key="step.id"
            class="runtime-panel__step"
          >
            <div class="runtime-panel__step-title">{{ step.title }}</div>
            <div class="runtime-panel__step-status">{{ step.status }}</div>
          </div>
        </div>
      </section>
    </template>

    <!-- Product slots for fully custom sections -->
    <slot name="custom-sections" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
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
  }>(),
  {
    panelGroups: () => [],
    events: () => [],
    stepGroups: () => [],
  },
)

const recentEvents = computed(() => props.events.slice(-12).reverse())

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

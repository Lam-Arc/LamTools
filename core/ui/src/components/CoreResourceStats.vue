<template>
  <div
    v-if="variant === 'composer'"
    class="core-resource-line"
    :class="{ 'has-data': summary?.hasContext }"
    :style="resourceStyle"
    role="meter"
    aria-label="上下文占用"
    :aria-valuenow="summary?.currentPct ?? 0"
    aria-valuemin="0"
    aria-valuemax="100"
    :title="composerTitle"
  >
    <span></span>
  </div>
  <section v-else class="runtime-widget core-resource-widget">
    <div class="runtime-widget-head">
      <h3>{{ title }}</h3>
      <strong v-if="summary" class="core-resource-state">{{ summary.statusLabel }}</strong>
    </div>
    <template v-if="summary">
      <div class="core-resource-main">
        <div class="core-resource-values">
          <strong>{{ summary.contextLabel }}</strong>
          <strong>{{ summary.percentLabel }}</strong>
        </div>
        <div class="core-resource-bar" :style="resourceStyle" role="meter" :aria-valuenow="summary.currentPct" aria-valuemin="0" aria-valuemax="100">
          <span class="core-resource-used"></span>
          <span class="core-resource-blocked"></span>
        </div>
        <div class="core-resource-legend">
          <span>可用至 {{ summary.thresholdPct }}%</span>
          <span>灰色区压缩</span>
        </div>
      </div>
      <div class="core-resource-stats">
        <div v-for="item in summary.callItems" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </template>
    <div v-else class="core-resource-empty">暂无资源统计。</div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CoreMessage } from '../types'
import { buildCoreResourceSummary, CORE_CONTEXT_COMPACTION_TRIGGER_RATIO } from '../runtime/resources'

const props = withDefaults(defineProps<{
  messages: Array<Pick<CoreMessage, 'metadata'>>
  contextWindow?: number | null
  variant?: 'panel' | 'composer'
  title?: string
}>(), {
  contextWindow: null,
  variant: 'panel',
  title: '资源',
})

const summary = computed(() => buildCoreResourceSummary(props.messages, props.contextWindow))
const resourceStyle = computed(() => ({
  '--core-resource-used': String(summary.value?.currentRatio ?? 0),
  '--core-resource-threshold': `${((summary.value?.thresholdRatio ?? CORE_CONTEXT_COMPACTION_TRIGGER_RATIO) * 100).toFixed(2)}%`,
}))
const composerTitle = computed(() => summary.value?.hasContext
  ? `上下文 ${summary.value.contextLabel}（${summary.value.percentLabel}）`
  : '暂无上下文统计')
</script>

<style scoped>
.core-resource-widget { --core-resource-ease: cubic-bezier(0.22, 1, 0.36, 1); }
.core-resource-state { color: var(--green); font-size: 12px; font-weight: 800; }
.core-resource-main { display: grid; gap: 6px; }
.core-resource-values, .core-resource-legend { display: flex; justify-content: space-between; gap: 8px; }
.core-resource-values strong { color: var(--theme-backdrop-text); font-family: var(--font-mono); font-size: 14px; }
.core-resource-bar { position: relative; height: 6px; overflow: hidden; background: color-mix(in srgb, var(--theme-backdrop-text) 10%, transparent); }
.core-resource-used, .core-resource-blocked { position: absolute; inset: 0; }
.core-resource-used { background: var(--green); transform: scaleX(var(--core-resource-used)); transform-origin: left; transition: transform 180ms var(--core-resource-ease); }
.core-resource-blocked { left: var(--core-resource-threshold); background: color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent); }
.core-resource-legend, .core-resource-empty, .core-resource-stats span { color: color-mix(in srgb, var(--theme-backdrop-text) 56%, transparent); font-size: 12px; }
.core-resource-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 8px; padding-top: 10px; border-top: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 11%, transparent); }
.core-resource-stats > div { display: grid; gap: 3px; min-width: 0; }
.core-resource-stats strong { overflow: hidden; color: var(--theme-backdrop-text); font-family: var(--font-mono); font-size: 13px; text-overflow: ellipsis; }
.core-resource-empty { padding: 8px 0; }
.core-resource-line { --core-resource-ease: cubic-bezier(0.22, 1, 0.36, 1); position: absolute; z-index: 3; top: 0; left: 0; right: 0; height: 1px; overflow: hidden; background: color-mix(in srgb, var(--theme-composer-text) 10%, transparent); pointer-events: none; }
.core-resource-line span { display: block; width: 100%; height: 100%; background: color-mix(in srgb, var(--theme-composer-text) 36%, transparent); opacity: 0; transform: scaleX(var(--core-resource-used)); transform-origin: left; transition: transform 180ms var(--core-resource-ease), opacity 120ms ease; }
.core-resource-line.has-data span { opacity: 1; }
@media (prefers-reduced-motion: reduce) { .core-resource-used, .core-resource-line span { transition-duration: .01ms !important; } }
</style>

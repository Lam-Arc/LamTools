<template>
  <details class="wf-policy-panel wf-inspector-section">
    <summary>
      <span>运行策略</span>
      <span class="wf-policy-summary">{{ summary }}</span>
    </summary>

    <div class="wf-policy-body">
      <label class="wf-policy-field wf-policy-priority">
        <span>队列优先级</span>
        <input
          type="number"
          step="1"
          :value="priority"
          :disabled="disabled || !workflowDefinition"
          @change="setPriority"
        />
      </label>

      <fieldset class="wf-policy-group">
        <label class="wf-policy-toggle">
          <input type="checkbox" :checked="Boolean(policies.concurrency)" :disabled="disabled || !workflowDefinition" @change="toggleConcurrency" />
          <span>并发上限</span>
        </label>
        <div v-if="policies.concurrency" class="wf-policy-grid">
          <label class="wf-policy-field">
            <span>分组键</span>
            <input type="text" :value="policies.concurrency.key" :disabled="disabled" @change="setConcurrencyKey" />
          </label>
          <label class="wf-policy-field">
            <span>最大并发</span>
            <input type="number" min="1" step="1" :value="policies.concurrency.max" :disabled="disabled" @change="setConcurrencyMax" />
          </label>
        </div>
      </fieldset>

      <fieldset class="wf-policy-group">
        <label class="wf-policy-toggle">
          <input type="checkbox" :checked="Boolean(policies.rate_limit)" :disabled="disabled || !workflowDefinition" @change="toggleRateLimit" />
          <span>速率限制</span>
        </label>
        <div v-if="policies.rate_limit" class="wf-policy-grid">
          <label class="wf-policy-field">
            <span>次数</span>
            <input type="number" min="1" step="1" :value="policies.rate_limit.count" :disabled="disabled" @change="setRateCount" />
          </label>
          <label class="wf-policy-field">
            <span>窗口（秒）</span>
            <input type="number" min="0.1" step="0.1" :value="policies.rate_limit.window_seconds" :disabled="disabled" @change="setRateWindow" />
          </label>
        </div>
      </fieldset>

      <fieldset class="wf-policy-group">
        <label class="wf-policy-toggle">
          <input type="checkbox" :checked="Boolean(policies.throttle)" :disabled="disabled || !workflowDefinition" @change="toggleThrottle" />
          <span>节流</span>
        </label>
        <label v-if="policies.throttle" class="wf-policy-field">
          <span>最小间隔（秒）</span>
          <input type="number" min="0.1" step="0.1" :value="policies.throttle.min_interval_seconds" :disabled="disabled" @change="setThrottleInterval" />
        </label>
      </fieldset>

      <fieldset class="wf-policy-group">
        <label class="wf-policy-toggle">
          <input type="checkbox" :checked="Boolean(policies.debounce)" :disabled="disabled || !workflowDefinition" @change="toggleDebounce" />
          <span>防抖</span>
        </label>
        <div v-if="policies.debounce" class="wf-policy-grid">
          <label class="wf-policy-field">
            <span>窗口（秒）</span>
            <input type="number" min="0.1" step="0.1" :value="policies.debounce.window_seconds" :disabled="disabled" @change="setDebounceWindow" />
          </label>
          <label class="wf-policy-field">
            <span>模式</span>
            <UiSelect
              :model-value="policies.debounce.mode"
              :options="debounceModes"
              aria-label="防抖模式"
              :disabled="disabled"
              @update:model-value="setDebounceMode"
            />
          </label>
        </div>
      </fieldset>

      <p class="wf-policy-help">策略作用于工作流运行；被限制的运行会进入可重试暂停态，不占用执行槽。</p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import UiSelect from '../../../../../../ui/src/components/UiSelect.vue'
import type { WorkflowDef, WorkflowPolicies } from './types'

const props = withDefaults(defineProps<{
  workflowDefinition?: WorkflowDef | null
  disabled?: boolean
  onUpdateDefinition?: (definition: WorkflowDef) => void | Promise<void>
}>(), {
  workflowDefinition: null,
  disabled: false,
  onUpdateDefinition: undefined,
})

const debounceModes = [
  { value: 'leading', label: '首个执行' },
  { value: 'trailing', label: '最后一个' },
]

const policies = computed<WorkflowPolicies>(() => props.workflowDefinition?.policies || {})
const priority = computed(() => integer(policies.value.priority, 0))
const summary = computed(() => {
  const enabled = [
    policies.value.concurrency && `并发 ${policies.value.concurrency.max}`,
    policies.value.rate_limit && `限速 ${policies.value.rate_limit.count}/${policies.value.rate_limit.window_seconds}s`,
    policies.value.throttle && `节流 ${policies.value.throttle.min_interval_seconds}s`,
    policies.value.debounce && `防抖 ${policies.value.debounce.window_seconds}s`,
    priority.value !== 0 && `优先级 ${priority.value}`,
  ].filter(Boolean)
  return enabled.join(' · ') || '默认'
})

function number(value: unknown, fallback: number, minimum = 0.1): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= minimum ? parsed : fallback
}

function integer(value: unknown, fallback: number, minimum?: number): number {
  const parsed = Number(value)
  if (!Number.isInteger(parsed)) return fallback
  return minimum === undefined || parsed >= minimum ? parsed : fallback
}

function checked(event: Event): boolean {
  return Boolean((event.target as HTMLInputElement | null)?.checked)
}

function value(event: Event): string {
  return String((event.target as HTMLInputElement | null)?.value || '')
}

function update(next: WorkflowPolicies): void {
  const definition = props.workflowDefinition
  if (!definition || props.disabled) return
  const clean = Object.fromEntries(Object.entries(next).filter(([, item]) => item !== undefined)) as WorkflowPolicies
  void props.onUpdateDefinition?.({
    ...definition,
    policies: clean,
    ...(definition.document ? { document: { ...definition.document, policies: clean } } : {}),
  })
}

function patch(key: keyof WorkflowPolicies, next: unknown): void {
  update({ ...policies.value, [key]: next })
}

function setPriority(event: Event): void { patch('priority', integer(value(event), priority.value)) }
function toggleConcurrency(event: Event): void { patch('concurrency', checked(event) ? { key: 'workflow', max: 1 } : undefined) }
function setConcurrencyKey(event: Event): void { patch('concurrency', { ...policies.value.concurrency!, key: value(event).trim() || 'workflow' }) }
function setConcurrencyMax(event: Event): void { patch('concurrency', { ...policies.value.concurrency!, max: integer(value(event), policies.value.concurrency!.max, 1) }) }
function toggleRateLimit(event: Event): void { patch('rate_limit', checked(event) ? { count: 10, window_seconds: 60 } : undefined) }
function setRateCount(event: Event): void { patch('rate_limit', { ...policies.value.rate_limit!, count: integer(value(event), policies.value.rate_limit!.count, 1) }) }
function setRateWindow(event: Event): void { patch('rate_limit', { ...policies.value.rate_limit!, window_seconds: number(value(event), policies.value.rate_limit!.window_seconds) }) }
function toggleThrottle(event: Event): void { patch('throttle', checked(event) ? { min_interval_seconds: 1 } : undefined) }
function setThrottleInterval(event: Event): void { patch('throttle', { min_interval_seconds: number(value(event), policies.value.throttle!.min_interval_seconds) }) }
function toggleDebounce(event: Event): void { patch('debounce', checked(event) ? { window_seconds: 1, mode: 'trailing' } : undefined) }
function setDebounceWindow(event: Event): void { patch('debounce', { ...policies.value.debounce!, window_seconds: number(value(event), policies.value.debounce!.window_seconds) }) }
function setDebounceMode(mode: string): void { patch('debounce', { ...policies.value.debounce!, mode: mode === 'leading' ? 'leading' : 'trailing' }) }
</script>

<style scoped>
.wf-policy-panel {
  --text: var(--theme-backdrop-text);
  color: var(--text);
}
.wf-policy-panel > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  list-style: none;
}
.wf-policy-panel > summary::-webkit-details-marker { display: none; }
.wf-policy-panel > summary:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); }
.wf-policy-summary {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 55%, transparent);
  font-size: 10px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wf-policy-body { display: grid; gap: var(--space-2); padding: 0 var(--space-3) var(--space-3); }
.wf-policy-group { min-width: 0; margin: 0; padding: var(--space-2); border: 1px solid color-mix(in srgb, var(--text) 10%, transparent); border-radius: var(--radius-sm); }
.wf-policy-toggle { display: flex; align-items: center; gap: var(--space-2); font-weight: 650; cursor: pointer; }
.wf-policy-toggle input { margin: 0; accent-color: var(--theme-control-text); }
.wf-policy-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-2); margin-top: var(--space-2); }
.wf-policy-field { display: grid; min-width: 0; gap: var(--space-1); color: color-mix(in srgb, var(--text) 65%, transparent); font-size: 10px; }
.wf-policy-priority { grid-template-columns: minmax(0, 1fr) 84px; align-items: center; }
.wf-policy-field input {
  box-sizing: border-box;
  width: 100%;
  min-height: 28px;
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--theme-control-text) 12%, transparent);
  border-radius: var(--radius-sm);
  outline: 0;
  background: color-mix(in srgb, var(--theme-control-background) 70%, transparent);
  color: var(--theme-control-text);
  font: inherit;
}
.wf-policy-help { margin: 0; color: color-mix(in srgb, var(--text) 45%, transparent); font-size: 10px; line-height: 1.45; }
.wf-policy-panel :disabled { opacity: .45; cursor: default; }
@media (max-width: 680px) {
  .wf-policy-grid { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
  .wf-policy-panel,
  .wf-policy-panel * { transition: none; animation: none; }
}
</style>

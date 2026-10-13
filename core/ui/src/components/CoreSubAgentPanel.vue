<template>
  <section class="runtime-widget core-sub-agent-panel" :aria-labelledby="titleId">
    <div class="runtime-widget-head core-sub-agent-panel__head">
      <div>
        <h3 :id="titleId">{{ title }}</h3>
        <p>{{ summaryText }}</p>
      </div>
    </div>

    <div :id="listId" class="core-sub-agent-panel__list">
      <div
        v-if="errorText"
        class="core-sub-agent-panel__notice is-error"
        role="alert"
      >
        <span>{{ errorText }}</span>
        <button type="button" @click="$emit('retry')">{{ t("重试") }}</button>
      </div>
      <p v-else-if="loading && runs.length === 0" class="core-sub-agent-panel__notice" role="status">{{ t("正在读取 Sub Agent 记录...") }}</p>

      <TransitionGroup name="sub-agent-list" tag="div" class="core-sub-agent-panel__runs">
        <div
          v-for="group in groupedRuns"
          :key="group.status"
          class="core-sub-agent-panel__group"
          :data-sub-agent-group="group.status"
        >
          <p class="core-sub-agent-panel__group-head">
            <span class="core-sub-agent-panel__group-label">{{ group.label }}</span>
            <span class="core-sub-agent-panel__group-count">{{ group.runs.length }}</span>
          </p>

          <div class="core-sub-agent-panel__group-rows">
            <div
              v-for="run in group.runs"
              :key="runIdentity(run)"
              class="core-sub-agent-panel__item"
              :class="{ 'has-delete': canDelete(run) }"
              :data-sub-agent-item="run.subSessionId"
            >
              <button
                type="button"
                class="core-sub-agent-panel__row"
                :class="{ 'is-active': activeSubAgentId === run.subSessionId }"
                :data-sub-agent-id="run.subSessionId"
                :title="runMetadataTitle(run)"
                aria-haspopup="false"
                :aria-controls="dialogId || undefined"
                :aria-expanded="activeSubAgentId === run.subSessionId"
                :aria-describedby="tooltipRun?.subSessionId === run.subSessionId ? tooltipId : undefined"
                @mouseenter="showTooltip(run, $event)"
                @mouseleave="hideTooltip"
                @focus="showTooltip(run, $event)"
                @blur="hideTooltip"
                @click="openRun(run)"
              >
                <span class="core-sub-agent-panel__dot" :class="'is-' + run.status" aria-hidden="true">
                  <Transition name="sub-agent-status-icon" mode="out-in">
                    <span v-if="run.status === 'running'" :key="run.status" class="core-sub-agent-panel__spinner" />
                    <span v-else-if="run.status === 'error'" :key="run.status" class="core-sub-agent-panel__marker">!</span>
                    <span v-else-if="run.status === 'pending'" :key="run.status" class="core-sub-agent-panel__marker">…</span>
                    <span v-else-if="run.status === 'paused'" :key="run.status" class="core-sub-agent-panel__marker">Ⅱ</span>
                    <span v-else-if="run.status === 'interrupted'" :key="run.status" class="core-sub-agent-panel__marker">↯</span>
                    <span v-else-if="run.status === 'closed'" :key="run.status" class="core-sub-agent-panel__marker">×</span>
                    <span v-else-if="run.status === 'idle'" :key="run.status" class="core-sub-agent-panel__marker">·</span>
                    <span v-else :key="run.status" class="core-sub-agent-panel__marker">✓</span>
                  </Transition>
                </span>
                <!-- 名字是这一行的主标签：右栏很窄，之前名字前面是委派类型、后面是模型与
                     耗时，可伸缩的名字列被挤到零宽，整列看起来一模一样。名字独占第一行
                     并优先占宽；状态与类型/模型/耗时退到第二行的次要小字。 -->
                <span class="core-sub-agent-panel__name">{{ displayName(run) }}</span>
                <span class="core-sub-agent-panel__meta">
                  <Transition name="sub-agent-status-label" mode="out-in">
                    <span :key="run.status" class="core-sub-agent-panel__status" :data-status="run.status">
                      {{ statusLabel(run.status) }}
                    </span>
                  </Transition>
                  <span class="core-sub-agent-panel__type">{{ runType(run) }}</span>
                  <template v-if="hasRunMetadata(run)">
                    <span class="core-sub-agent-panel__model">{{ compactLabel(run.model || run.modelId, '—') }}</span>
                    <span v-if="run.reasoningLevel" class="core-sub-agent-panel__reasoning">{{ run.reasoningLevel }}</span>
                  </template>
                  <span class="core-sub-agent-panel__elapsed" :aria-label="t('耗时 ') + elapsedLabel(run)">{{ elapsedLabel(run) }}</span>
                </span>
              </button>

              <button
                v-if="canDelete(run)"
                type="button"
                class="core-sub-agent-panel__delete"
                :aria-label="t('删除子代理 ') + displayName(run)"
                :title="t('删除 ') + displayName(run)"
                @click="requestDelete(run)"
              >
                <Trash2 :size="13" :stroke-width="1.8" aria-hidden="true" />
              </button>

              <Transition name="sub-agent-timeline">
                <div
                  v-if="activeSubAgentId === run.subSessionId && !run.sourceMessageId && run.timeline.length > 0"
                  class="core-sub-agent-panel__timeline-reveal"
                >
                  <div class="core-sub-agent-panel__timeline" :aria-label="run.name + t(' 子代理时间线')">
                    <p v-for="message in run.timeline.slice(-3)" :key="message.id">
                      <strong>{{ message.role === 'user' ? t("任务") : t("过程") }}</strong>
                      <span>{{ message.content || '…' }}</span>
                    </p>
                  </div>
                </div>
              </Transition>
            </div>
          </div>
        </div>
      </TransitionGroup>

      <button
        v-if="overflowCount > 0"
        type="button"
        class="core-sub-agent-panel__more"
        :aria-expanded="expanded"
        :aria-controls="listId"
        @click="expanded = !expanded"
      >
        <span aria-hidden="true">{{ expanded ? '−' : '…' }}</span>
        <span>{{ expanded ? t("收起") : t("查看其余 ") + overflowCount + t(" 个") }}</span>
      </button>

      <p v-if="runs.length === 0 && !loading && !errorText" class="core-sub-agent-panel__empty">{{ emptyText }}</p>
    </div>

    <Teleport to="body">
      <Transition name="sub-agent-tooltip">
        <div
          v-if="tooltipRun"
          :id="tooltipId"
          class="core-sub-agent-tooltip"
          role="tooltip"
          :style="tooltipStyle"
        >
          <span>{{ hasRunMetadata(tooltipRun) ? runMetadataTitle(tooltipRun) : t("首次任务") }}</span>
          <p>{{ tooltipRun.task || tooltipRun.summary || t("未记录任务内容。") }}</p>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup lang="ts">
import { t } from '../i18n/index'

import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Trash2 } from 'lucide-vue-next'
import type { CoreSubAgentRun } from '../types'
import { normalizeSubAgentType, subAgentStatusLabel as statusLabel } from '../agents/subAgentDisplay'

/** 状态分组顺序：与投影里的运行排序同一口径——在跑的最前，已完成的最后。 */
const STATUS_ORDER = ['running', 'pending', 'paused', 'error', 'interrupted', 'idle', 'closed', 'completed']
/** 结束态才算"完成"，才允许删除：运行中 / 等待中的成员不提供删除入口。 */
const UNDELETABLE_STATUSES = new Set(['running', 'pending'])

const props = withDefaults(defineProps<{
  runs: readonly CoreSubAgentRun[]
  limit?: number
  title?: string
  emptyText?: string
  activeSubAgentId?: string
  dialogId?: string
  loading?: boolean
  errorText?: string
}>(), {
  limit: 4,
  title: 'Sub Agents',
  get emptyText() { return t("尚未启动 Sub Agent") },
  activeSubAgentId: '',
  dialogId: '',
  loading: false,
  errorText: '',
})

const emit = defineEmits<{
  open: [subSessionId: string]
  retry: []
  /** 删除一个已结束的子代理：壳体负责那一次调用，列表本身不直接发 RPC。 */
  delete: [run: CoreSubAgentRun]
}>()

const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const titleId = 'core-sub-agent-title-' + instanceId
const listId = 'core-sub-agent-list-' + instanceId
const tooltipId = 'core-sub-agent-tooltip-' + instanceId
const expanded = ref(false)
const tooltipRun = ref<CoreSubAgentRun | null>(null)
const tooltipTrigger = ref<HTMLElement | null>(null)
const tooltipStyle = ref<Record<string, string>>({})
const elapsedNow = ref(Date.now())
let elapsedTimer: ReturnType<typeof setInterval> | null = null

const safeLimit = computed(() => Math.min(4, Math.max(1, Math.floor(props.limit))))
const overflowCount = computed(() => Math.max(0, props.runs.length - safeLimit.value))

/**
 * 运行按状态分组，运行中的排最前。分组只算"当前要显示的那几条"：折叠时先按状态
 * 排序再取前 limit 条，所以"查看其余 N 个"仍然按状态优先级展开，不会因为折叠漏掉
 * 正在跑的成员。排序是稳定排序：同一状态内保持投影给出的相对顺序（它已经是
 * "最新证据在前"）。这段计算只在卡片挂载时随 props.runs 变化求值一次，不额外扫描
 * 消息，也不新增每帧工作（隐藏时整块 getter 不求值，见 RightSidebarHost）。
 */
const orderedRuns = computed(() => {
  const rank = new Map(STATUS_ORDER.map((status, index) => [status, index]))
  return props.runs
    .map((run, index) => ({ run, index }))
    .sort((left, right) => {
      const leftRank = rank.get(String(left.run.status)) ?? STATUS_ORDER.length
      const rightRank = rank.get(String(right.run.status)) ?? STATUS_ORDER.length
      return leftRank === rightRank ? left.index - right.index : leftRank - rightRank
    })
    .map(entry => entry.run)
})

const visibleRuns = computed(() => (
  expanded.value ? orderedRuns.value : orderedRuns.value.slice(0, safeLimit.value)
))

const groupedRuns = computed(() => {
  const groups: Array<{ status: string; label: string; runs: CoreSubAgentRun[] }> = []
  for (const run of visibleRuns.value) {
    const status = String(run.status || '')
    const last = groups[groups.length - 1]
    if (last && last.status === status) last.runs.push(run)
    else groups.push({ status, label: statusLabel(status), runs: [run] })
  }
  return groups
})

const summaryText = computed(() => {
  if (props.runs.length > 0) return props.runs.length + t(" 个记录")
  if (props.loading) return t("读取中")
  if (props.errorText) return t("读取失败")
  // 空状态由列表里的 emptyText 呈现一次，头部摘要不再重复同一句话。
  return ''
})

watch(
  () => props.runs.map(runIdentity).sort().join('\u0000'),
  () => {
    expanded.value = false
    hideTooltip()
  },
)

function openRun(run: CoreSubAgentRun) {
  hideTooltip()
  emit('open', run.subSessionId)
}

/** 主标签：投影解析出来的真实代理名；记录里没有名字时兜底，绝不显示空白。 */
function displayName(run: CoreSubAgentRun): string {
  return String(run.name || '').trim() || 'Sub Agent'
}

function canDelete(run: CoreSubAgentRun): boolean {
  return !UNDELETABLE_STATUSES.has(String(run.status || ''))
}

function requestDelete(run: CoreSubAgentRun) {
  if (!canDelete(run)) return
  hideTooltip()
  emit('delete', run)
}

function showTooltip(run: CoreSubAgentRun, event: Event) {
  const trigger = event.currentTarget
  if (!(trigger instanceof HTMLElement)) return
  tooltipRun.value = run
  tooltipTrigger.value = trigger
  updateTooltipPosition()
}

function hideTooltip() {
  tooltipRun.value = null
  tooltipTrigger.value = null
}

function updateTooltipPosition() {
  const trigger = tooltipTrigger.value
  if (!trigger || !tooltipRun.value) return
  const rect = trigger.getBoundingClientRect()
  const width = Math.min(320, Math.max(220, window.innerWidth - 24))
  let left = rect.left - width - 10
  if (left < 12) left = Math.min(window.innerWidth - width - 12, rect.right + 10)
  const top = Math.max(12, Math.min(window.innerHeight - 156, rect.top - 8))
  const styles = getComputedStyle(trigger)
  tooltipStyle.value = {
    left: Math.round(left) + 'px',
    top: Math.round(top) + 'px',
    width: Math.round(width) + 'px',
    '--sub-agent-tooltip-bg': styles.getPropertyValue('--theme-backdrop-background') || '#202020',
    '--sub-agent-tooltip-text': styles.getPropertyValue('--theme-backdrop-text') || '#f2efeb',
  }
}

function runType(run: CoreSubAgentRun): string {
  return normalizeSubAgentType(run.type || 'execute')
}

function runIdentity(run: CoreSubAgentRun): string {
  return run.name.trim().toLowerCase() || run.id || run.subSessionId
}

function hasRunMetadata(run: CoreSubAgentRun): boolean {
  return Boolean(run.model || run.modelId || run.reasoningLevel)
}

function runMetadataTitle(run: CoreSubAgentRun): string {
  const model = compactLabel(run.model || run.modelId, '—')
  const reasoning = compactLabel(run.reasoningLevel, '—')
  return `${model} · ${reasoning}`
}

function elapsedLabel(run: CoreSubAgentRun): string {
  let elapsed = typeof run.elapsedMs === 'number' ? run.elapsedMs : undefined
  if (elapsed === undefined) {
    const start = Date.parse(run.startedAt || '')
    const end = run.completedAt ? Date.parse(run.completedAt) : elapsedNow.value
    elapsed = Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, end - start) : 0
  }
  if (elapsed < 1000) return `${Math.round(elapsed)}ms`
  const seconds = elapsed / 1000
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  return `${Math.floor(seconds / 60)}m ${String(Math.floor(seconds % 60)).padStart(2, '0')}s`
}

function compactLabel(value: unknown, fallback: string): string {
  const text = String(value || '').trim()
  return text ? text.slice(0, 40) : fallback
}

let tooltipScrollRaf = 0

function onWindowScroll() {
  // capture 捕获所有容器滚动 + passive + rAF 合并（原实现非 passive 每滚动事件同步跑 getBoundingClientRect）
  if (tooltipScrollRaf) return
  tooltipScrollRaf = requestAnimationFrame(() => {
    tooltipScrollRaf = 0
    updateTooltipPosition()
  })
}

onMounted(() => {
  window.addEventListener('resize', updateTooltipPosition)
  window.addEventListener('scroll', onWindowScroll, { passive: true, capture: true })
  elapsedTimer = setInterval(() => { elapsedNow.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateTooltipPosition)
  window.removeEventListener('scroll', onWindowScroll, { capture: true } as EventListenerOptions)
  if (tooltipScrollRaf) cancelAnimationFrame(tooltipScrollRaf)
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = null
})
</script>

<style scoped>
.core-sub-agent-panel {
  --text: var(--theme-backdrop-text);
  color: var(--text);
}

.core-sub-agent-panel__head p {
  font-variant-numeric: tabular-nums;
}

.core-sub-agent-panel__list {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.core-sub-agent-panel__runs,
.core-sub-agent-panel__item {
  position: relative;
  min-width: 0;
  display: grid;
  gap: 2px;
}

/* 状态分组：组头是安静的小字标签 + 计数；组内行序保持投影给出的顺序。 */
.core-sub-agent-panel__group {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.core-sub-agent-panel__group-head {
  display: flex;
  align-items: baseline;
  gap: .35rem;
  margin: var(--space-1) 0 0;
  padding: 0 .5rem;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: .625rem;
  font-weight: 620;
  letter-spacing: .04em;
  line-height: 1.4;
}

.core-sub-agent-panel__group-count {
  color: color-mix(in srgb, var(--text) 32%, transparent);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.core-sub-agent-panel__group-rows {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.core-sub-agent-panel__notice {
  min-height: 2.25rem;
  margin: 0;
  padding: .5rem;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-size: .75rem;
  line-height: 1.45;
}

.core-sub-agent-panel__notice.is-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: .5rem;
  color: color-mix(in srgb, var(--red, #f5555d) 78%, var(--theme-backdrop-text, currentColor));
}

.core-sub-agent-panel__notice button {
  min-height: 2rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: inherit;
  padding: 0 .625rem;
  font: inherit;
  cursor: pointer;
}

.core-sub-agent-panel__notice button:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-sub-agent-panel__row {
  width: 100%;
  min-width: 0;
  min-height: 2.25rem;
  display: grid;
  /* 两行：第一行只有名字（主标签，优先占宽），第二行是状态与次要元数据。 */
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-areas:
    "dot name"
    ". meta";
  align-content: center;
  align-items: center;
  column-gap: .5rem;
  row-gap: .1rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  padding: .3rem .5rem;
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

/* 带删除入口的行留出按钮位置，名字与状态都不被遮住。 */
.core-sub-agent-panel__item.has-delete .core-sub-agent-panel__row {
  padding-right: 2rem;
}

/* 删除入口：只有已结束的成员才有；平时隐去，悬停/聚焦这一行时出现（触屏常显）。 */
.core-sub-agent-panel__delete {
  position: absolute;
  top: .35rem;
  right: .35rem;
  width: 1.4rem;
  height: 1.4rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 48%, transparent);
  cursor: pointer;
  opacity: 0;
  transition:
    opacity var(--dur-fast) var(--ease-out),
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.core-sub-agent-panel__item:hover .core-sub-agent-panel__delete,
.core-sub-agent-panel__item:focus-within .core-sub-agent-panel__delete {
  opacity: 1;
}

.core-sub-agent-panel__delete:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--red);
}

.core-sub-agent-panel__delete:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-sub-agent-panel__row:hover {
  transform: translateX(2px);
}

.core-sub-agent-panel__row:hover,
.core-sub-agent-panel__row.is-active {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
}

.core-sub-agent-panel__row:active {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-sub-agent-panel__row:focus-visible,
.core-sub-agent-panel__more:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--green, #32d17d) 62%, white 8%);
  outline-offset: 2px;
}

.core-sub-agent-panel__dot {
  grid-area: dot;
  width: 1rem;
  height: 1rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--text) 18%, transparent);
  font-size: .625rem;
  line-height: 1;
  transition:
    background var(--dur-base) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.core-sub-agent-panel__row:hover .core-sub-agent-panel__dot {
  transform: scale(1.06);
}

.core-sub-agent-panel__dot.is-running {
  background: color-mix(in srgb, var(--green) 70%, var(--theme-backdrop-background));
}

.core-sub-agent-panel__dot.is-pending {
  background: color-mix(in srgb, var(--orange) 70%, var(--theme-backdrop-background));
}

.core-sub-agent-panel__dot.is-error {
  background: color-mix(in srgb, var(--red) 70%, var(--theme-backdrop-background));
}

.core-sub-agent-panel__dot.is-failed {
  background: color-mix(in srgb, var(--red) 70%, var(--theme-backdrop-background));
}

.core-sub-agent-panel__dot.is-paused {
  background: color-mix(in srgb, var(--orange) 64%, var(--theme-backdrop-background));
}

.core-sub-agent-panel__dot.is-interrupted,
.core-sub-agent-panel__dot.is-closed {
  background: color-mix(in srgb, var(--text) 28%, transparent);
}

.core-sub-agent-panel__marker { color: var(--theme-backdrop-text); font-weight: 750; }
.core-sub-agent-panel__spinner {
  width: .625rem;
  height: .625rem;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 36%, transparent);
  border-top-color: var(--theme-backdrop-text);
  border-radius: 50%;
  animation: core-sub-agent-spin calc(var(--dur-theme) * 1.5) linear infinite;
}

.core-sub-agent-panel__type,
.core-sub-agent-panel__model,
.core-sub-agent-panel__elapsed {
  min-width: 0;
  max-width: 8rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-sub-agent-panel__name {
  grid-area: name;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: .8125rem;
  font-weight: 680;
  line-height: 1.35;
}

/* 第二行：状态与类型/模型/耗时的次要小字，允许换行但保持安静。 */
.core-sub-agent-panel__meta {
  grid-area: meta;
  min-width: 0;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: .35rem;
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: .625rem;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  line-height: 1.3;
}

.core-sub-agent-panel__status {
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-family: var(--font-sans);
  font-size: .6875rem;
  line-height: 1.3;
  white-space: nowrap;
}

/* 状态不只靠颜色区分（点/旋转/文字都在），这里只是把"还在动"和"出错"挑出来，
   其余状态保持同一层灰，让列表安静。 */
.core-sub-agent-panel__status[data-status="running"] {
  color: color-mix(in srgb, var(--green) 78%, var(--theme-backdrop-text));
}

.core-sub-agent-panel__status[data-status="pending"] {
  color: color-mix(in srgb, var(--orange) 76%, var(--theme-backdrop-text));
}

.core-sub-agent-panel__status[data-status="error"],
.core-sub-agent-panel__status[data-status="failed"] {
  color: color-mix(in srgb, var(--red) 78%, var(--theme-backdrop-text));
}

.core-sub-agent-panel__reasoning {
  color: color-mix(in srgb, var(--text) 38%, transparent);
}

.sub-agent-status-icon-enter-active,
.sub-agent-status-icon-leave-active,
.sub-agent-status-label-enter-active,
.sub-agent-status-label-leave-active {
  transition:
    opacity var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.sub-agent-status-icon-enter-from,
.sub-agent-status-icon-leave-to {
  opacity: 0;
  transform: scale(.72);
}

.sub-agent-status-label-enter-from,
.sub-agent-status-label-leave-to {
  opacity: 0;
  transform: translateY(2px);
}

.sub-agent-list-move,
.sub-agent-list-enter-active,
.sub-agent-list-leave-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}

.sub-agent-list-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}

.sub-agent-list-leave-to {
  opacity: 0;
  transform: translateX(4px);
}

.sub-agent-list-leave-active {
  position: absolute;
  inset-inline: 0;
}

.core-sub-agent-panel__more {
  width: 100%;
  min-height: 2rem;
  display: grid;
  grid-template-columns: 1rem minmax(0, 1fr);
  align-items: center;
  gap: .5rem;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 62%, transparent);
  padding: 0 .5rem;
  font: inherit;
  font-size: .75rem;
  text-align: left;
  cursor: pointer;
}

.core-sub-agent-panel__more:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.core-sub-agent-panel__more span:first-child {
  color: var(--text);
  font-family: var(--font-mono, monospace);
  font-weight: 800;
  text-align: center;
}

.core-sub-agent-panel__empty {
  margin: 0;
  padding: .5rem;
  color: color-mix(in srgb, var(--text) 56%, transparent);
  font-size: .75rem;
  line-height: 1.5;
}

.core-sub-agent-panel__timeline-reveal {
  min-width: 0;
  display: grid;
  grid-template-rows: 1fr;
  overflow: hidden;
}

.core-sub-agent-panel__timeline {
  min-height: 0;
  display: grid;
  gap: var(--space-1);
  margin: 0 var(--space-2) var(--space-1) calc(var(--space-2) + 1.5rem);
  padding: var(--space-2);
  border-left: 1px solid color-mix(in srgb, var(--text) 16%, transparent);
  color: color-mix(in srgb, var(--text) 68%, transparent);
  font-size: .6875rem;
  line-height: 1.4;
}
.core-sub-agent-panel__timeline p { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: var(--space-1); margin: 0; }
.core-sub-agent-panel__timeline span { overflow-wrap: anywhere; }

.sub-agent-timeline-enter-active,
.sub-agent-timeline-leave-active {
  transition:
    grid-template-rows var(--dur-slow) var(--ease-out),
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-slow) var(--ease-out);
}

.sub-agent-timeline-enter-from,
.sub-agent-timeline-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
  transform: translateY(-4px);
}

@keyframes core-sub-agent-spin {
  to { transform: rotate(360deg); }
}

.core-sub-agent-tooltip {
  position: fixed;
  z-index: var(--z-popover, 60);
  max-height: 9rem;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--sub-agent-tooltip-text) 13%, transparent);
  border-radius: var(--radius);
  background: var(--sub-agent-tooltip-bg);
  color: var(--sub-agent-tooltip-text);
  box-shadow: var(--shadow-sm);
  padding: .75rem .875rem;
  pointer-events: none;
}

.core-sub-agent-tooltip span {
  display: block;
  color: color-mix(in srgb, var(--sub-agent-tooltip-text) 58%, transparent);
  font-size: .6875rem;
  font-weight: 650;
  line-height: 1.35;
}

.core-sub-agent-tooltip p {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  overflow: hidden;
  margin: .375rem 0 0;
  font-size: .8125rem;
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.sub-agent-tooltip-enter-active,
.sub-agent-tooltip-leave-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}

.sub-agent-tooltip-enter-from,
.sub-agent-tooltip-leave-to {
  opacity: 0;
  transform: translateX(4px);
}

@media (pointer: coarse) {
  .core-sub-agent-panel__row,
  .core-sub-agent-panel__more {
    min-height: 2.75rem;
  }

  /* 触屏没有悬停：删除入口常显，否则永远够不到。 */
  .core-sub-agent-panel__delete {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .core-sub-agent-panel__spinner { animation: none; }
  .core-sub-agent-panel__row,
  .core-sub-agent-panel__dot,
  .core-sub-agent-panel__delete,
  .sub-agent-list-move,
  .sub-agent-list-enter-active,
  .sub-agent-list-leave-active,
  .sub-agent-status-icon-enter-active,
  .sub-agent-status-icon-leave-active,
  .sub-agent-status-label-enter-active,
  .sub-agent-status-label-leave-active,
  .sub-agent-timeline-enter-active,
  .sub-agent-timeline-leave-active,
  .sub-agent-tooltip-enter-active,
  .sub-agent-tooltip-leave-active {
    transition: none;
  }

  .core-sub-agent-panel__row:hover,
  .core-sub-agent-panel__row:hover .core-sub-agent-panel__dot {
    transform: none;
  }
}
</style>

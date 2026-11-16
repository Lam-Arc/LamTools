<script setup lang="ts">
// user:“胶囊式：键值对横向紧凑展示入参摘要 + 状态徽章（成功/耗时）”+
// (API/状态查询不再把入参铺成 JSON 文本，键值挨着排一行，状态与耗时贴在末尾。)
// user:“超过 N 个键值折叠成「+N」（展开可看全部）”+(默认只露 3 个键值，多的收进 +N，点开看全量。)
import { computed, ref } from 'vue'
import { t } from '@/i18n/index.ts'

interface ProcessKvEntry {
  key: string
  value: string
}

const props = defineProps<{
  entries: ProcessKvEntry[]
  status?: 'success' | 'error' | 'running'
  durationMs?: number
}>()

/** 收起状态下最多露出的键值个数。 */
const MAX_VISIBLE_ENTRIES = 3

const expanded = ref(false)

const visibleEntries = computed(() => (expanded.value ? props.entries : props.entries.slice(0, MAX_VISIBLE_ENTRIES)))
const hiddenCount = computed(() => Math.max(0, props.entries.length - MAX_VISIBLE_ENTRIES))

const statusLabel = computed(() => {
  if (props.status === 'success') return t('成功')
  if (props.status === 'error') return t('失败')
  if (props.status === 'running') return t('进行中')
  return ''
})

/**
 * user:“ProcessKvPill 的 durationMs 支持到分钟级（65s、2m05s），不要出现 125.3s 这种”
 * +(一分钟以内用秒并保留一位小数；跨分钟进位成 `XmSSs`，秒补零，绝不出现 125.3s)。
 */
function formatDuration(durationMs?: number): string {
  const value = Number(durationMs)
  if (!Number.isFinite(value) || value < 0) return ''
  if (value < 1000) return `${Math.round(value)}ms`
  if (value < 60_000) return `${(value / 1000).toFixed(1)}s`
  const totalSeconds = Math.round(value / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m${String(seconds).padStart(2, '0')}s`
}

const durationLabel = computed(() => formatDuration(props.durationMs))
</script>

<template>
  <div v-if="entries.length || status" class="process-kv">
    <span v-for="entry in visibleEntries" :key="entry.key" class="process-kv__entry">
      <span class="process-kv__key">{{ entry.key }}</span>
      <span class="process-kv__value" :title="entry.value">{{ entry.value }}</span>
    </span>
    <button
      v-if="hiddenCount"
      type="button"
      class="process-kv__more"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >{{ expanded ? t('收起') : `+${hiddenCount}` }}</button>
    <!-- 状态徽章取主题语义色：成功走绿、失败走红、进行中走蓝并呼吸。 -->
    <span v-if="status" class="process-kv__status" :class="`process-kv__status--${status}`">
      <span class="process-kv__dot" aria-hidden="true" />
      <span>{{ statusLabel }}</span>
      <span v-if="durationLabel" class="process-kv__duration">{{ durationLabel }}</span>
    </span>
  </div>
</template>

<style scoped>
.process-kv {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  min-width: 0;
  font-size: var(--ms-proc-body-font-size, 12px);
}

.process-kv__entry {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
  box-sizing: border-box;
  max-width: 100%;
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--ms-proc-border-color, var(--line, currentColor));
  border-radius: var(--ms-proc-radius-sm, 8px);
  background: color-mix(
    in srgb,
    var(--ms-proc-fill-color, var(--theme-main-text, currentColor)) calc(var(--ms-proc-fill-alpha, 0) * 100%),
    transparent
  );
  line-height: 20px;
  backdrop-filter: blur(var(--ms-proc-blur, 0px));
  -webkit-backdrop-filter: blur(var(--ms-proc-blur, 0px));
}

.process-kv__key {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 50%, transparent);
}

.process-kv__value {
  min-width: 0;
  max-width: 18ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 84%, transparent);
  font-family: var(--font-mono, inherit);
}

.process-kv__more {
  height: 22px;
  padding: 0 8px;
  border: 1px dashed var(--ms-proc-border-color, var(--line, currentColor));
  border-radius: var(--ms-proc-radius-sm, 8px);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 62%, transparent);
  font: inherit;
  font-size: var(--ms-proc-body-font-size, 12px);
  line-height: 20px;
  cursor: pointer;
}

.process-kv__more:hover {
  border-style: solid;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 88%, transparent);
}

.process-kv__more:focus-visible {
  outline: var(--focus-ring-width, 2px) solid var(--focus-ring-color, currentColor);
  outline-offset: var(--focus-ring-offset, 2px);
}

.process-kv__status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 22px;
  padding: 0 8px;
  border-radius: var(--ms-proc-radius-sm, 8px);
  border: 1px solid color-mix(in srgb, var(--kv-tone, currentColor) 34%, transparent);
  background: color-mix(in srgb, var(--kv-tone, currentColor) 12%, transparent);
  color: color-mix(in srgb, var(--kv-tone, currentColor) 82%, var(--theme-main-text, currentColor));
  font-size: calc(var(--ms-proc-body-font-size, 12px) - 1px);
  line-height: 20px;
  white-space: nowrap;
}

.process-kv__status--success {
  --kv-tone: var(--green, currentColor);
}

.process-kv__status--error {
  --kv-tone: var(--red, currentColor);
}

.process-kv__status--running {
  --kv-tone: var(--blue, currentColor);
}

.process-kv__dot {
  width: 5px;
  height: 5px;
  border-radius: 999px;
  background: var(--kv-tone, currentColor);
}

.process-kv__status--running .process-kv__dot {
  animation: process-kv-pulse 1.4s ease-in-out infinite;
}

.process-kv__duration {
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 52%, transparent);
}

@keyframes process-kv-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

@media (prefers-reduced-motion: reduce) {
  .process-kv__status--running .process-kv__dot {
    animation: none;
  }
}
</style>

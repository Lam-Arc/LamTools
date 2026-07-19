<script setup lang="ts">
import { ref } from 'vue'

export interface CoreArrangeDraft {
  instruction: string
  kind: 'focus' | 'routine'
  trigger: Record<string, unknown>
}

withDefaults(defineProps<{ busy?: boolean; error?: string; timezone?: string }>(), {
  busy: false,
  error: '',
  timezone: 'Asia/Shanghai',
})
const emit = defineEmits<{ submit: [draft: CoreArrangeDraft]; cancel: [] }>()

const instruction = ref('')
const scheduleType = ref<'once' | 'daily' | 'monthly' | 'event'>('once')
const localAt = ref('')
const localTime = ref('09:00')
const day = ref(1)
const eventType = ref('')
const localError = ref('')

function submit(timezone: string) {
  localError.value = ''
  const message = instruction.value.trim()
  if (!message) return
  let trigger: Record<string, unknown>
  if (scheduleType.value === 'once') {
    if (!localAt.value) { localError.value = '请选择执行时间'; return }
    const [date, time = '09:00'] = localAt.value.split('T')
    trigger = { type: 'once', date, time, timezone }
  } else if (scheduleType.value === 'daily') {
    trigger = { type: 'calendar', frequency: 'daily', timezone, time: localTime.value }
  } else if (scheduleType.value === 'monthly') {
    trigger = { type: 'calendar', frequency: 'monthly', timezone, time: localTime.value, day: day.value }
  } else {
    const value = eventType.value.trim()
    if (!value) { localError.value = '请输入事件类型'; return }
    trigger = { type: 'event', event_type: value }
  }
  emit('submit', { instruction: message, kind: scheduleType.value === 'event' ? 'focus' : 'routine', trigger })
}
</script>

<template>
  <form class="core-arrange-form" @submit.prevent="submit(timezone)">
    <header><div><h2>创建安排</h2><p>安排会在专用会话中执行。</p></div><button type="button" class="close" aria-label="关闭" @click="$emit('cancel')">×</button></header>
    <label><span>要做什么</span><textarea v-model="instruction" rows="3" autofocus placeholder="例如：推荐今天吃什么" /></label>
    <label><span>触发方式</span><select v-model="scheduleType"><option value="once">单次时间</option><option value="daily">每天</option><option value="monthly">每月</option><option value="event">事件</option></select></label>
    <label v-if="scheduleType === 'once'"><span>执行时间</span><input v-model="localAt" type="datetime-local" /></label>
    <div v-else-if="scheduleType === 'daily'" class="fields"><label><span>每天</span><input v-model="localTime" type="time" /></label><span class="timezone">{{ timezone }}</span></div>
    <div v-else-if="scheduleType === 'monthly'" class="fields"><label><span>日期</span><input v-model.number="day" type="number" min="1" max="31" /></label><label><span>时间</span><input v-model="localTime" type="time" /></label></div>
    <label v-else><span>事件类型</span><input v-model="eventType" placeholder="例如 artifact.changed" /></label>
    <p v-if="localError || error" class="error" role="alert">{{ localError || error }}</p>
    <footer><button type="button" class="quiet" @click="$emit('cancel')">取消</button><button type="submit" class="primary" :disabled="busy || !instruction.trim()">{{ busy ? '创建中…' : '确认创建' }}</button></footer>
  </form>
</template>

<style scoped>
.core-arrange-form { width: min(460px, calc(100vw - 80px)); }
header, footer, .fields { display: flex; align-items: center; } header { justify-content: space-between; gap: 20px; margin-bottom: 20px; } h2 { margin: 0 0 4px; } header p { margin: 0; color: var(--muted); font-size: 13px; }
label { display: grid; gap: 7px; margin-top: 14px; font-size: 13px; } input, textarea, select { box-sizing: border-box; width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel-2); color: var(--text); font: inherit; }
input:focus-visible, textarea:focus-visible, select:focus-visible, button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; } .fields { align-items: end; gap: 12px; } .fields label { flex: 1; } .timezone { padding-bottom: 9px; color: var(--muted); font-size: 12px; }
footer { justify-content: flex-end; gap: 8px; margin-top: 22px; } button { border: 0; padding: 8px 12px; border-radius: 8px; color: var(--text); background: transparent; cursor: pointer; font: inherit; } .close { padding: 4px 8px; color: var(--muted); font-size: 20px; } .primary { background: var(--blue); color: #101820; font-weight: 650; } button:disabled { cursor: default; opacity: .5; } .error { margin: 12px 0 0; color: var(--red); font-size: 13px; }
@media (max-width: 700px) { input, select, button { min-height: 44px; } .close { min-width: 44px; } }
</style>

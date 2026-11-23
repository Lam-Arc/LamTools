<script setup lang="ts">
/**
 * user:“放进 界面/主题”+(气泡外观属于界面外观，卡片放「设置 → 界面」，
 * 不再占用「通用」；读写仍走 core.assistantDisplay 这一份显示偏好)。
 *
 * user:“界面中是否可以设置？颜色与材质配置？”+(形状、玻璃、用户/助手填充色；
 * 颜色留空表示跟随主题角色色，重启后保留)。
 */
import { computed, onMounted, ref } from 'vue'
import { t } from '@/i18n/index.ts'
import SundaySegmented from '@/components/SundaySegmented.vue'
import SundaySwitch from '@/components/SundaySwitch.vue'
import {
  ASSISTANT_DISPLAY_NAMESPACE,
  assistantDisplayPreferences,
  assistantDisplaySnapshot,
  normalizeAssistantDisplayPreferences,
  setAssistantDisplayPreferences,
  type AssistantDisplayPreferences,
} from '@/composables/useAssistantDisplayPreferences.ts'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const appearance = assistantDisplayPreferences
const saving = ref(false)
const saved = ref(false)
const error = ref('')

const busy = computed(() => saving.value)

const shapeOptions = computed(() => [
  { value: 'card', label: t('卡片') },
  { value: 'capsule', label: t('胶囊') },
])

function readValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object') return {}
  const raw = value as Record<string, unknown>
  const inner = raw.value
  return inner && typeof inner === 'object' ? inner as Record<string, unknown> : raw
}

async function persist(patch: Partial<AssistantDisplayPreferences>): Promise<void> {
  const previous = assistantDisplaySnapshot()
  setAssistantDisplayPreferences(patch)
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const next = assistantDisplaySnapshot()
    await props.requestRpc('settings.update', { namespace: ASSISTANT_DISPLAY_NAMESPACE, value: next })
    saved.value = true
  } catch (e) {
    // 后端没存下时退回上一次成功的取值，界面不显示假状态
    setAssistantDisplayPreferences(previous)
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

function setShape(next: string): void {
  if (next !== 'card' && next !== 'capsule') return
  if (busy.value || next === appearance.bubbleShape) return
  void persist({ bubbleShape: next })
}

function toggleGlass(next: boolean): void {
  if (busy.value || next === appearance.bubbleGlass) return
  void persist({ bubbleGlass: next })
}

function setColor(role: 'user' | 'assistant', event: Event): void {
  if (busy.value) return
  const value = (event.target as HTMLInputElement).value
  void persist(role === 'user' ? { bubbleUserColor: value } : { bubbleAssistantColor: value })
}

function resetColor(role: 'user' | 'assistant'): void {
  if (busy.value) return
  void persist(role === 'user' ? { bubbleUserColor: '' } : { bubbleAssistantColor: '' })
}

onMounted(async () => {
  try {
    const value = readValue(await props.requestRpc('settings.get', { namespace: ASSISTANT_DISPLAY_NAMESPACE }))
    const normalized = normalizeAssistantDisplayPreferences(value)
    if (Object.keys(normalized).length > 0) setAssistantDisplayPreferences(normalized)
  } catch {
    // 读不到就沿用本地偏好，不影响其它界面设置
  }
})
</script>

<template>
  <article class="setting-card bubble-appearance" data-bubble-appearance>
    <div class="subhead">
      <span class="muted subhead-title">{{ t("气泡外观") }}</span>
      <div class="subhead-actions">
        <span v-if="saving" class="bubble-appearance-status">{{ t("保存中…") }}</span>
        <span v-else-if="saved" class="bubble-appearance-status bubble-appearance-status--saved">{{ t("已保存") }}</span>
      </div>
    </div>
    <p class="bubble-appearance-hint">{{ t("用户与助手气泡共用：形状、玻璃与填充色只影响界面显示，不改变消息内容与上下文。") }}</p>
    <div class="bubble-appearance-row">
      <p class="bubble-appearance-hint">{{ t("形状：卡片为 28px 大圆角，胶囊为两端全圆。") }}</p>
      <SundaySegmented
        :model-value="appearance.bubbleShape"
        :options="shapeOptions"
        :label="t('气泡形状')"
        :disabled="busy"
        @update:model-value="setShape"
      />
    </div>
    <div class="bubble-appearance-row">
      <p class="bubble-appearance-hint">{{ t("玻璃：关闭后改用实色填充，不再采样背后的背景。") }}</p>
      <SundaySwitch
        :model-value="appearance.bubbleGlass"
        :label="t('玻璃气泡')"
        :disabled="busy"
        @update:model-value="toggleGlass"
      />
    </div>
    <div class="bubble-appearance-color">
      <span>{{ t("用户气泡颜色") }}</span>
      <input
        type="color"
        :value="appearance.bubbleUserColor || '#f2a3b7'"
        :aria-label="t('用户气泡颜色')"
        :disabled="busy"
        @change="setColor('user', $event)"
      />
      <button class="btn btn--ghost" type="button" :disabled="busy || !appearance.bubbleUserColor" @click="resetColor('user')">{{ t("默认") }}</button>
    </div>
    <div class="bubble-appearance-color">
      <span>{{ t("助手气泡颜色") }}</span>
      <input
        type="color"
        :value="appearance.bubbleAssistantColor || '#a7c6f5'"
        :aria-label="t('助手气泡颜色')"
        :disabled="busy"
        @change="setColor('assistant', $event)"
      />
      <button class="btn btn--ghost" type="button" :disabled="busy || !appearance.bubbleAssistantColor" @click="resetColor('assistant')">{{ t("默认") }}</button>
    </div>
    <p v-if="error" class="bubble-appearance-error" role="alert">{{ error }}</p>
  </article>
</template>

<style scoped>
.bubble-appearance {
  display: grid;
  gap: var(--space-3);
}

.bubble-appearance-hint {
  margin: 0;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 62%, transparent);
  font-size: 12px;
  line-height: 1.6;
}

.bubble-appearance-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-3);
  align-items: center;
}

.bubble-appearance-color {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: var(--space-2);
  align-items: center;
  font-size: 13px;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 72%, transparent);
}

.bubble-appearance-color input[type='color'] {
  width: 44px;
  height: 26px;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 18%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
}

.bubble-appearance-status {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 55%, transparent);
  font-size: 12px;
}

.bubble-appearance-status--saved {
  color: var(--green);
}

.bubble-appearance-error {
  margin: 0;
  color: var(--red);
  font-size: 12px;
}
</style>

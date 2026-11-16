<template>
  <!-- user:“输入框上方是一个三选一的胶囊，发送第一条消息时，定下该会话模式”
       “布局参考一下这个”+(参考图那样：聊天卡片顶部居中一段分段控件，三等分、
       选中的一段更亮；发过第一条消息后模式已定，这块随空会话一起消失)。 -->
  <div
    class="core-run-mode"
    :class="{ 'core-run-mode--locked': !selectable }"
    role="radiogroup"
    :aria-label="t('会话运行模式')"
    data-run-mode-capsule
  >
    <div class="core-run-mode__bar">
      <template v-if="selectable">
        <button
          v-for="option in options"
          :key="option.value"
          type="button"
          role="radio"
          class="core-run-mode__pill"
          :class="{ 'is-active': option.value === modelValue }"
          :aria-checked="option.value === modelValue"
          :title="option.description"
          :data-run-mode-option="option.value"
          @click="$emit('update:modelValue', option.value)"
        >
          {{ option.label }}
        </button>
      </template>
      <span
        v-else
        class="core-run-mode__pill is-active"
        :title="activeDescription"
        data-run-mode-locked
      >
        {{ activeLabel }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import { t } from '@/i18n/index.ts'
import {
  CORE_RUN_MODE_DESCRIPTIONS,
  CORE_RUN_MODE_LABELS,
  CORE_RUN_MODES,
  normalizeCoreRunMode,
  type CoreRunMode,
} from '@/composer/runMode.ts'

const props = withDefaults(defineProps<{
  modelValue?: string
  /** 只有还没发过消息的会话能改模式。 */
  selectable?: boolean
}>(), {
  modelValue: 'work',
  selectable: true,
})

defineEmits<{ 'update:modelValue': [value: CoreRunMode] }>()

const options = computed(() => CORE_RUN_MODES.map((value) => ({
  value,
  label: t(CORE_RUN_MODE_LABELS[value]),
  description: t(CORE_RUN_MODE_DESCRIPTIONS[value]),
})))

const activeMode = computed(() => normalizeCoreRunMode(props.modelValue))
const activeLabel = computed(() => t(CORE_RUN_MODE_LABELS[activeMode.value]))
const activeDescription = computed(() => t(CORE_RUN_MODE_DESCRIPTIONS[activeMode.value]))
</script>

<style scoped>
.core-run-mode {
  display: flex;
  justify-content: center;
  --text: var(--theme-main-text);
}

.core-run-mode__bar {
  display: inline-flex;
  align-items: stretch;
  gap: 2px;
  padding: 4px;
  border-radius: var(--radius-pill, 999px);
  background: color-mix(in srgb, var(--text) 8%, transparent);
}

.core-run-mode--locked .core-run-mode__bar {
  padding: 0;
  background: transparent;
}

.core-run-mode__pill {
  min-width: 132px;
  height: 40px;
  padding: 0 var(--space-4, 16px);
  border: 0;
  border-radius: var(--radius-pill, 999px);
  background: transparent;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font: inherit;
  font-size: 15px;
  font-weight: 550;
  letter-spacing: 0.01em;
  white-space: nowrap;
  text-align: center;
  cursor: pointer;
  transition: background 140ms ease, color 140ms ease;
}

.core-run-mode__pill:hover {
  color: color-mix(in srgb, var(--text) 88%, transparent);
  background: color-mix(in srgb, var(--text) 6%, transparent);
}

.core-run-mode__pill.is-active {
  background: color-mix(in srgb, var(--text) 16%, transparent);
  color: color-mix(in srgb, var(--text) 98%, transparent);
}

.core-run-mode--locked .core-run-mode__pill,
.core-run-mode--locked .core-run-mode__pill.is-active {
  min-width: 0;
  background: color-mix(in srgb, var(--text) 10%, transparent);
  color: color-mix(in srgb, var(--text) 72%, transparent);
  cursor: default;
}

.core-run-mode__pill:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 30%, transparent);
  outline-offset: 2px;
}
</style>

<template>
  <!-- 系统事件行：机器写入转录的一行短提示（成员完成 / 记忆续跑），不是用户气泡，
       也不是助手正文。安静、单行起高、可换行，不主动抢聊天内容的注意力。 -->
  <div class="core-system-event" role="status" data-system-event-row :title="event.text">
    <span class="core-system-event__icon" aria-hidden="true">
      <Bot v-if="event.kind === 'member_wake'" :size="13" :stroke-width="1.8" />
      <History v-else :size="13" :stroke-width="1.8" />
    </span>
    <span class="core-system-event__label">{{ label }}</span>
    <span class="core-system-event__body">
      <template v-if="event.entries.length">
        <span
          v-for="(entry, index) in event.entries"
          :key="index"
          class="core-system-event__entry"
        >
          <span class="core-system-event__name">{{ entry.name }}</span>
          <span class="core-system-event__state">{{ entry.state }}</span>
          <span v-if="entry.message" class="core-system-event__message">{{ entry.message }}</span>
        </span>
      </template>
      <span v-else class="core-system-event__message">{{ event.text }}</span>
    </span>
  </div>
</template>

<script setup lang="ts">
import { t } from '../i18n/index'

import { computed } from 'vue'
import { Bot, History } from 'lucide-vue-next'
import type { CoreSystemEvent } from '../appServer/systemEvents'

const props = defineProps<{ event: CoreSystemEvent }>()

const label = computed(() => {
  if (props.event.kind === 'member_wake') return t("子代理")
  if (props.event.kind === 'memory_resume') return t("记忆续跑")
  return t("系统")
})
</script>

<style scoped>
.core-system-event {
  --text: var(--theme-main-text);
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin: var(--space-1) 0;
  padding: var(--space-1) var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--text) 4%, transparent);
  color: color-mix(in srgb, var(--text) 68%, transparent);
  font-size: 12px;
  line-height: 1.5;
}
.core-system-event__icon {
  flex: 0 0 auto;
  display: inline-flex;
  margin-top: 1px;
  color: color-mix(in srgb, var(--text) 55%, transparent);
}
.core-system-event__label {
  flex: 0 0 auto;
  font-weight: 650;
  color: color-mix(in srgb, var(--text) 78%, transparent);
}
.core-system-event__body {
  min-width: 0;
  /* 一行起高；成员消息稍长时自然换行，但不做成长段正文。 */
  overflow-wrap: anywhere;
}
.core-system-event__entry + .core-system-event__entry {
  display: block;
  margin-top: 2px;
}
.core-system-event__name {
  font-weight: 650;
  color: color-mix(in srgb, var(--text) 82%, transparent);
}
.core-system-event__state {
  margin-left: var(--space-1);
}
.core-system-event__message {
  margin-left: var(--space-1);
  color: color-mix(in srgb, var(--text) 78%, transparent);
}
</style>

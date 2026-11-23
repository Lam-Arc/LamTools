<template>
  <!-- 系统事件行：机器写入转录的一行短提示（成员完成 / 记忆续跑），不是用户气泡，
       也不是助手正文。安静、单行起高、可换行，不主动抢聊天内容的注意力。
       user:“子代理信息结束…那条消息 UI 显示的时候记得折叠成一行胶囊”+
       (成员唤醒默认只占一行：图标 + 子代理 + 成员/状态/结论，超出省略；
        点一下展开成原来的多条明细，再点收起。) -->
  <div
    class="core-system-event"
    :class="{ 'core-system-event--pill': pill, 'core-system-event--open': pillOpen }"
    :role="pill ? 'button' : 'status'"
    :tabindex="pill ? 0 : undefined"
    :aria-expanded="pill ? pillOpen : undefined"
    :aria-label="pill ? pillAria : undefined"
    data-system-event-row
    :title="event.text"
    @click="pill && (pillOpen = !pillOpen)"
    @keydown.enter.prevent="pill && (pillOpen = !pillOpen)"
    @keydown.space.prevent="pill && (pillOpen = !pillOpen)"
  >
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
import { t } from '@/i18n/index.ts'

import { computed, ref } from 'vue'
import { Bot, History } from 'lucide-vue-next'
import type { CoreSystemEvent } from '@/appServer/systemEvents.ts'

const props = defineProps<{ event: CoreSystemEvent }>()

const label = computed(() => {
  if (props.event.kind === 'member_wake') return t("子代理")
  if (props.event.kind === 'memory_resume') return t("记忆续跑")
  return t("系统")
})

/** 只有成员唤醒是胶囊：它一天到晚往会话里落，不折叠会把正文挤下去。 */
const pill = computed(() => props.event.kind === 'member_wake')
const pillOpen = ref(false)
const pillAria = computed(() => (pillOpen.value ? t("收起子代理明细") : t("展开子代理明细")))
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
/* user:“折叠成一行胶囊”+(默认单行、超出省略；点开才换成原来的多条明细)。 */
.core-system-event--pill {
  align-items: center;
  gap: var(--space-1);
  min-height: 26px;
  padding: 0 var(--space-2);
  border-radius: 999px;
  white-space: nowrap;
  overflow: hidden;
  cursor: pointer;
  transition: background-color 100ms ease-out, border-color 100ms ease-out;
}

.core-system-event--pill:hover {
  background: color-mix(in srgb, var(--text) 7%, transparent);
  border-color: color-mix(in srgb, var(--text) 16%, transparent);
}

.core-system-event--pill:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 35%, transparent);
  outline-offset: 1px;
}

.core-system-event--pill .core-system-event__icon {
  margin-top: 0;
}

.core-system-event--pill .core-system-event__body {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
}

.core-system-event--pill .core-system-event__entry {
  display: inline;
}

.core-system-event--pill .core-system-event__entry + .core-system-event__entry {
  display: inline;
  margin-top: 0;
}

/* 分隔点用盒子画，不进文本：复制和读屏拿到的仍是原始内容。 */
.core-system-event--pill .core-system-event__entry + .core-system-event__entry::before {
  content: '·';
  margin: 0 var(--space-1);
  opacity: .55;
}

.core-system-event--open {
  align-items: flex-start;
  border-radius: var(--radius-sm);
  padding: var(--space-1) var(--space-2);
  white-space: normal;
  overflow: visible;
}

.core-system-event--open .core-system-event__entry + .core-system-event__entry {
  display: block;
  margin-top: 2px;
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

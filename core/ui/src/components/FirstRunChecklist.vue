<template>
  <!--
    user:“配置好你的 API key ，新建第一个项目与会话，发送第一条消息，就完事了”+
    (这张清单只有三格：配模型、建项目与会话、发第一句话。它贴在输入框上方，
     不遮内容，也不讲功能；做完最后一格自己消失。)
  -->
  <section
    v-if="visible"
    class="first-run"
    :class="['first-run--' + stage, { 'first-run--done': stage === 'done' }]"
    data-first-run
    :data-first-run-stage="stage"
    role="status"
    aria-live="polite"
  >
    <div class="first-run-row">
      <span class="first-run-count" aria-hidden="true">{{ progress.done }}/{{ progress.total }}</span>

      <div class="first-run-copy">
        <strong class="first-run-title">{{ copy.title }}</strong>
        <span class="first-run-note">{{ copy.note }}</span>
      </div>

      <ol class="first-run-steps" :aria-label="t('开工进度')">
        <li
          v-for="item in stepDefs"
          :key="item.id"
          class="first-run-step"
          :class="{ 'is-done': item.done, 'is-active': item.active }"
          :data-first-run-step="item.id"
          :aria-current="item.active ? 'step' : undefined"
        >
          <span class="first-run-dot" aria-hidden="true">
            <Check v-if="item.done" :size="9" :stroke-width="3" />
          </span>
          <span class="first-run-step-label">{{ item.label }}</span>
        </li>
      </ol>

      <button
        v-if="stage !== 'done'"
        class="first-run-action"
        type="button"
        data-first-run-action
        @click="emit('action')"
      >
        {{ copy.action }}
      </button>
      <button
        v-else
        class="first-run-action first-run-action--quiet"
        type="button"
        @click="finishNow"
      >
        {{ t("收起") }}
      </button>
      <button
        class="first-run-close"
        type="button"
        :aria-label="t('不再显示')"
        :title="t('不再显示')"
        data-first-run-dismiss
        @click="emit('dismiss')"
      >
        <X :size="13" :stroke-width="2" aria-hidden="true" />
      </button>
    </div>

    <div v-if="stage === 'message'" class="first-run-examples">
      <span class="first-run-examples-label">{{ t("不知道说什么？点一句：") }}</span>
      <button
        v-for="example in examples"
        :key="example"
        class="first-run-example"
        type="button"
        @click="emit('pick-example', example)"
      >
        {{ example }}
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Check, X } from 'lucide-vue-next'
import { firstRunProgress, firstRunStage, FIRST_RUN_TOTAL } from '@/firstRun/firstRun.ts'

const props = defineProps<{
  visible: boolean
  hasProvider: boolean
  hasProject: boolean
  hasSession: boolean
  firstMessageSent: boolean
}>()

const emit = defineEmits<{
  action: []
  dismiss: []
  'pick-example': [text: string]
  finished: []
}>()

const stage = computed(() => firstRunStage({
  hasProvider: props.hasProvider,
  hasProject: props.hasProject,
  hasSession: props.hasSession,
  firstMessageSent: props.firstMessageSent,
}))

const progress = computed(() => firstRunProgress({
  hasProvider: props.hasProvider,
  hasProject: props.hasProject,
  hasSession: props.hasSession,
  firstMessageSent: props.firstMessageSent,
}))

const stepDefs = computed(() => [
  { id: 'provider', get label() { return t("配模型") }, done: props.hasProvider, active: stage.value === 'provider' },
  { id: 'workspace', get label() { return t("建项目") }, done: props.hasProject && props.hasSession, active: stage.value === 'workspace' },
  { id: 'message', get label() { return t("第一句话") }, done: props.firstMessageSent, active: stage.value === 'message' },
])

const copy = computed(() => {
  switch (stage.value) {
    case 'provider':
      return {
        get title() { return t("先给 Sunday 一个大脑") },
        get note() { return t("粘贴一串 API key 就行，之后随时能换") },
        get action() { return t("去配置") },
      }
    case 'workspace':
      return {
        get title() { return t("建个项目，开始干活") },
        get note() {
          return props.hasProject
            ? t("项目已经有了，开一个会话说第一句话")
            : t("项目就是它工作的文件夹，会话会一起建好")
        },
        get action() { return props.hasProject ? t("开会话") : t("新建项目") },
      }
    case 'message':
      return {
        get title() { return t("在下面说第一句话") },
        get note() { return t("Enter 发送，Shift+Enter 换行") },
        get action() { return t("帮我起个头") },
      }
    default:
      return {
        get title() { return t("开工了") },
        get note() { return t("接下来说你想做的事就行") },
        get action() { return '' },
      }
  }
})

const examples = [
  t("你好，先介绍一下你能做什么"),
  t("看看这个项目里有什么"),
  t("帮我把今天的待办列一下"),
]

let finishTimer: ReturnType<typeof setTimeout> | undefined

function finishNow(): void {
  if (finishTimer !== undefined) {
    clearTimeout(finishTimer)
    finishTimer = undefined
  }
  emit('finished')
}

// user:“确保视觉、功能和交互不退化”+(只有完成态可见时计时，重新显示时重新开始计时)。
watch([stage, () => props.visible], ([next, shown]) => {
  if (finishTimer !== undefined) {
    clearTimeout(finishTimer)
    finishTimer = undefined
  }
  if (next === 'done' && shown) finishTimer = setTimeout(finishNow, 4200)
}, { immediate: true })

onBeforeUnmount(() => {
  if (finishTimer !== undefined) clearTimeout(finishTimer)
})

defineExpose({ total: FIRST_RUN_TOTAL })
</script>

<style scoped>
.first-run {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--theme-composer-text, #fbf7f0) 12%, transparent);
  border-radius: var(--radius);
  background: var(--theme-composer-soft-background, rgba(255, 255, 255, .045));
  color: var(--theme-composer-text, #fbf7f0);
  animation: first-run-in .22s ease-out;
}

.first-run-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.first-run-count {
  flex: 0 0 auto;
  display: inline-grid;
  place-items: center;
  min-width: 30px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, currentColor 10%, transparent);
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, currentColor 72%, transparent);
}

.first-run-copy {
  display: grid;
  gap: 1px;
  min-width: 0;
  flex: 1 1 auto;
}

.first-run-title {
  font-size: 12.5px;
  font-weight: 700;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.first-run-note {
  font-size: 11px;
  line-height: 1.35;
  color: color-mix(in srgb, currentColor 46%, transparent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.first-run-steps {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
  list-style: none;
}

.first-run-step {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: color-mix(in srgb, currentColor 34%, transparent);
}

.first-run-dot {
  display: inline-grid;
  place-items: center;
  width: 13px;
  height: 13px;
  border: 1px solid color-mix(in srgb, currentColor 22%, transparent);
  border-radius: 50%;
  color: transparent;
}

.first-run-step.is-active {
  color: color-mix(in srgb, currentColor 82%, transparent);
  font-weight: 650;
}

.first-run-step.is-active .first-run-dot {
  border-color: color-mix(in srgb, currentColor 55%, transparent);
  box-shadow: 0 0 0 3px color-mix(in srgb, currentColor 7%, transparent);
}

.first-run-step.is-done {
  color: color-mix(in srgb, currentColor 52%, transparent);
}

.first-run-step.is-done .first-run-dot {
  border-color: transparent;
  background: var(--green);
  color: #10231a;
}

.first-run-action {
  flex: 0 0 auto;
  height: 26px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: var(--theme-control-solid, #fbf7f0);
  color: var(--theme-control-text, #2e3138);
  font: inherit;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
}

.first-run-action:hover {
  filter: brightness(.94);
}

.first-run-action--quiet {
  background: color-mix(in srgb, currentColor 9%, transparent);
  color: color-mix(in srgb, currentColor 66%, transparent);
}

.first-run-close {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, currentColor 38%, transparent);
  cursor: pointer;
}

.first-run-close:hover {
  background: color-mix(in srgb, currentColor 8%, transparent);
  color: color-mix(in srgb, currentColor 78%, transparent);
}

.first-run-examples {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
  padding-left: 38px;
}

.first-run-examples-label {
  font-size: 11px;
  color: color-mix(in srgb, currentColor 40%, transparent);
}

.first-run-example {
  max-width: 100%;
  padding: 2px 8px;
  border: 1px solid color-mix(in srgb, currentColor 12%, transparent);
  border-radius: 999px;
  background: transparent;
  color: color-mix(in srgb, currentColor 70%, transparent);
  font: inherit;
  font-size: 11px;
  line-height: 1.6;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.first-run-example:hover {
  border-color: color-mix(in srgb, currentColor 26%, transparent);
  color: currentColor;
}

.first-run--done {
  border-color: color-mix(in srgb, var(--green) 30%, transparent);
}

.first-run--done .first-run-count {
  background: color-mix(in srgb, var(--green) 18%, transparent);
  color: var(--green);
}

@keyframes first-run-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 820px) {
  .first-run-steps {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .first-run {
    animation: none;
  }
}
</style>

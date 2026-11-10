<template>
  <!--
    user:“诉求是让哪怕没接触过电脑的小白也能用明白sunday”+
    (三个动作各做成一个小练习：必须真的做一次，但永远留「我做不到，帮我过」
     的出口——把人卡在第一步，比不教更伤人。)
  -->
  <div class="guide-practice" :class="'guide-practice--' + exercise">
    <template v-if="exercise === 'click'">
      <div class="guide-practice-stage">
        <button
          ref="clickTarget"
          type="button"
          class="guide-practice-target"
          :class="{ 'is-done': done }"
          data-guide-practice-click
          :aria-label="t('点一下这个圆点')"
          @click="finish"
        >
          <span class="guide-practice-ripple" aria-hidden="true"></span>
          <span class="guide-practice-core" aria-hidden="true"></span>
        </button>
      </div>
      <p class="guide-practice-state" aria-live="polite">
        {{ done ? t("点到了。就是这个动作。") : t("用食指按一下鼠标左键，再松开。") }}
      </p>
    </template>

    <template v-else-if="exercise === 'type'">
      <label class="guide-practice-field">
        <span class="guide-practice-label">{{ t("在这里打字") }}</span>
        <input
          ref="typeInput"
          v-model="typed"
          class="guide-practice-input"
          type="text"
          data-guide-practice-input
          :placeholder="t('输入「你好」')"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          @input="checkTyped"
@keydown.enter.prevent
        />
      </label>
      <p class="guide-practice-state" aria-live="polite">
        <template v-if="done">{{ t("打出来了。键盘就是用来干这个的。") }}</template>
        <template v-else-if="typed">{{ t("已经打了 {0} 个字，还差一点。", { 0: typed.length }) }}</template>
        <template v-else>{{ t("先点一下方框，看到竖线在闪，再敲键盘。") }}</template>
      </p>
    </template>

    <template v-else>
      <div
        ref="scrollBox"
        class="guide-practice-scroll"
        data-guide-practice-scroll
        tabindex="0"
        @scroll.passive="checkScroll"
      >
        <p v-for="line in scrollLines" :key="line" class="guide-practice-line">{{ line }}</p>
        <p class="guide-practice-line guide-practice-line--end">{{ t("到底了。") }}</p>
      </div>
      <p class="guide-practice-state" aria-live="polite">
        {{ done ? t("会滚了。以后看长内容都靠它。") : t("把鼠标放在这里，拨一下中间的轮子。") }}
      </p>
    </template>

    <div class="guide-practice-actions">
      <button class="guide-text-button" type="button" @click="skip">
        {{ exercise === 'click' ? t("我点不到，帮我过") : exercise === 'type' ? t("键盘用不了，帮我过") : t("滚不动，帮我过") }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { nextTick, onMounted, ref } from 'vue'

const props = defineProps<{ exercise: 'click' | 'type' | 'scroll' }>()
const emit = defineEmits<{ done: [] }>()

const done = ref(false)
const typed = ref('')
const clickTarget = ref<HTMLButtonElement | null>(null)
const typeInput = ref<HTMLInputElement | null>(null)
const scrollBox = ref<HTMLElement | null>(null)

const scrollLines = [
  t("第一行：这段字比屏幕长，所以要看下面的，就得滚。"),
  t("第二行：滚动不会改动任何东西，只是换个位置看。"),
  t("第三行：滚过头了也没关系，反方向再滚就回来。"),
  t("第四行：鼠标中间的轮子往前拨是往上，往后拨是往下。"),
  t("第五行：触控板用两根手指上下划，方向相反也可以设置。"),
  t("第六行：长对话、长文件、长网页，全靠这个动作。"),
]

function finish(): void {
  if (done.value) return
  done.value = true
  emit('done')
}

function skip(): void {
  finish()
}

function checkTyped(): void {
  const normalized = typed.value.replace(/\s+/g, '')
  if (normalized.includes('你好')) finish()
}

function checkScroll(): void {
  const element = scrollBox.value
  if (!element) return
  if (element.scrollTop + element.clientHeight >= element.scrollHeight - 8) finish()
}

onMounted(() => {
  // 焦点只在练习区里，不抢整页：让「点一下/打字」的目标自己发亮就够了。
  void nextTick(() => {
    if (props.exercise === 'type') typeInput.value?.focus({ preventScroll: true })
  })
})
</script>

<style scoped>
.guide-practice {
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--text) 10%, transparent);
  border-radius: var(--radius);
  background: var(--theme-main-sunken-background, rgba(0, 0, 0, .25));
}

.guide-practice-stage {
  display: grid;
  place-items: center;
  height: 104px;
}

.guide-practice-target {
  position: relative;
  display: grid;
  place-items: center;
  width: 76px;
  height: 76px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  cursor: pointer;
}

.guide-practice-target:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 40%, transparent);
  outline-offset: 6px;
}

.guide-practice-ripple,
.guide-practice-core {
  position: absolute;
  border-radius: 50%;
}

.guide-practice-ripple {
  width: 76px;
  height: 76px;
  border: 1px solid color-mix(in srgb, var(--text) 24%, transparent);
  animation: guide-practice-pulse 2.4s ease-out infinite;
}

.guide-practice-core {
  width: 34px;
  height: 34px;
  background: var(--theme-control-solid, #fbf7f0);
  box-shadow: 0 0 0 8px color-mix(in srgb, var(--text) 6%, transparent);
  transition: transform var(--dur-fast, .16s) var(--ease-out, ease-out), box-shadow var(--dur-fast, .16s) var(--ease-out, ease-out);
}

.guide-practice-target:hover .guide-practice-core {
  transform: scale(1.08);
  box-shadow: 0 0 0 12px color-mix(in srgb, var(--text) 9%, transparent);
}

.guide-practice-target.is-done .guide-practice-core {
  background: var(--green);
  box-shadow: 0 0 0 12px color-mix(in srgb, var(--green) 18%, transparent);
}

.guide-practice-target.is-done .guide-practice-ripple {
  animation: none;
  opacity: .4;
}

.guide-practice-field {
  display: grid;
  gap: var(--space-1);
}

.guide-practice-label {
  font-size: 12px;
  font-weight: 650;
  color: color-mix(in srgb, var(--text) 55%, transparent);
}

.guide-practice-input {
  width: 100%;
  height: var(--interaction-height-lg, 42px);
  padding: 0 var(--space-3);
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-composer-background, transparent);
  color: var(--text);
  font: inherit;
  font-size: 15px;
  outline: none;
}

.guide-practice-input::placeholder {
  color: color-mix(in srgb, var(--text) 38%, transparent);
}

.guide-practice-scroll {
  max-height: 108px;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--theme-main-background, transparent);
  scrollbar-width: thin;
}

.guide-practice-scroll:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--text) 26%, transparent);
  outline-offset: 2px;
}

.guide-practice-line {
  margin: 0 0 var(--space-2);
  font-size: 13px;
  line-height: 1.7;
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

.guide-practice-line--end {
  margin-bottom: 0;
  color: color-mix(in srgb, var(--text) 42%, transparent);
}

.guide-practice-state {
  min-height: 20px;
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  color: color-mix(in srgb, var(--text) 56%, transparent);
}

.guide-practice-actions {
  display: flex;
  justify-content: flex-end;
}

.guide-text-button {
  border: 0;
  padding: 2px 0;
  background: transparent;
  color: color-mix(in srgb, var(--text) 42%, transparent);
  font: inherit;
  font-size: 12px;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}

.guide-text-button:hover {
  color: color-mix(in srgb, var(--text) 72%, transparent);
}

@keyframes guide-practice-pulse {
  0% { transform: scale(.9); opacity: .8; }
  70% { transform: scale(1.5); opacity: 0; }
  100% { transform: scale(1.5); opacity: 0; }
}

@media (prefers-reduced-motion: reduce) {
  .guide-practice-ripple { animation: none; }
  .guide-practice-core { transition: none; }
}
</style>

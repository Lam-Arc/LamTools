<template>
  <div class="core-session-title-editor" :class="{ 'is-editing': editing }">
    <h1>
      <!-- user:“会话标题需要先点击进入编辑才是正常文本”+
           (显示态是不可选中的标题文本，点一下才切成输入框；Esc 退回显示态)。 -->
      <input
        v-if="editing"
        ref="inputEl"
        v-model="draft"
        class="core-session-title-input"
        :aria-label="t('会话标题')"
        spellcheck="false"
        :disabled="saving"
        @blur="commit"
        @keydown.enter.prevent="commitAndBlur"
        @keydown.esc.prevent="cancel"
      />
      <button
        v-else
        type="button"
        class="core-session-title-display"
        data-session-title-display
        :title="t('点击编辑标题')"
        :aria-label="t('编辑会话标题')"
        @click="startEditing"
      >{{ draft }}</button>
    </h1>
    <span v-if="sessionId">#{{ sessionId.slice(0, 8) }}</span>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  title: string
  sessionId?: string
  rename: (title: string) => Promise<void>
}>()

const emit = defineEmits<{ error: [error: unknown] }>()
const inputEl = ref<HTMLInputElement | null>(null)
const draft = ref(props.title)
const editing = ref(false)
const saving = ref(false)

watch(() => props.title, (title) => {
  if (!editing.value && !saving.value) draft.value = title
})

// user:“会话标题需要先点击进入编辑才是正常文本”+
// (显示态只是文本，点击后才挂上输入框；进入编辑后光标落在末尾，正文仍可正常选择)。
function startEditing(): void {
  editing.value = true
  void nextTick(() => {
    const input = inputEl.value
    if (!input) return
    input.focus()
    const end = input.value.length
    input.setSelectionRange(end, end)
  })
}

async function commit() {
  if (saving.value) return
  const title = draft.value.trim()
  editing.value = false
  if (!title || title === props.title) {
    draft.value = props.title
    return
  }
  saving.value = true
  draft.value = title
  try {
    await props.rename(title)
  } catch (error) {
    draft.value = props.title
    emit('error', error)
  } finally {
    saving.value = false
  }
}

function commitAndBlur() {
  void commit()
  inputEl.value?.blur()
}

function cancel() {
  draft.value = props.title
  editing.value = false
  inputEl.value?.blur()
}
</script>

<style scoped>
.core-session-title-editor {
  width: 100%;
  min-width: 0;
  display: grid;
  gap: 4px;
}

.core-session-title-editor h1 {
  width: 100%;
  min-width: 0;
  margin: 0;
}

.core-session-title-editor span {
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 48%, transparent);
  font-size: 12px;
}

/* 显示态：只是文本，不占输入框的光标与选区行为。 */
.core-session-title-display {
  display: inline-block;
  box-sizing: border-box;
  max-width: 100%;
  height: 28px;
  margin: 0;
  padding: 2px 0;
  border: 0;
  background: transparent;
  color: var(--theme-main-text, currentColor);
  font: inherit;
  font-size: 17px;
  font-weight: 760;
  line-height: 1.2;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: text;
  /* user:“上方的所有标题文字无法被左键拖动选中”+(显示态不参与文本选择)。 */
  user-select: none;
}

.core-session-title-display:hover {
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 82%, transparent);
}

.core-session-title-display:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

.core-session-title-input {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  height: 28px;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--theme-main-text, currentColor);
  caret-color: var(--theme-main-text, currentColor);
  padding: 2px 0;
  font: inherit;
  font-size: 17px;
  font-weight: 760;
  line-height: 1.2;
  text-overflow: ellipsis;
  /* 进入编辑后才是正常文本：可以框选、可以拖选。 */
  user-select: text;
}

.core-session-title-input:focus {
  background: transparent;
}

.core-session-title-input:disabled {
  opacity: .62;
}
</style>

<template>
  <div class="core-session-title-editor">
    <h1>
      <input
        ref="inputEl"
        v-model="draft"
        class="core-session-title-input"
        aria-label="会话标题"
        spellcheck="false"
        :disabled="saving"
        @focus="editing = true"
        @blur="commit"
        @keydown.enter.prevent="commitAndBlur"
        @keydown.esc.prevent="cancel"
      />
    </h1>
    <span v-if="sessionId">#{{ sessionId.slice(0, 8) }}</span>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

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
}

.core-session-title-input:focus {
  background: transparent;
}

.core-session-title-input:disabled {
  opacity: .62;
}
</style>

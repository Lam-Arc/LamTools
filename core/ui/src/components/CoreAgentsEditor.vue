<template>
  <form class="core-agents-editor" :aria-busy="loading" @keydown.esc.prevent="!loading && emit('close')" @submit.prevent="save">
    <div class="core-agents-editor-head">
      <strong>AGENTS.md</strong>
      <button type="button" class="icon-btn" data-agents-close :disabled="loading" title="关闭" aria-label="关闭" @click="emit('close')">
        <X :size="13" :stroke-width="1.8" aria-hidden="true" />
      </button>
    </div>
    <textarea
      v-model="draft"
      data-agents-content
      aria-label="AGENTS.md 内容"
      spellcheck="false"
      :disabled="loading"
    />
    <p v-if="error" class="core-agents-error" role="alert">{{ error }}</p>
    <div class="core-agents-actions">
      <button type="button" class="btn-cancel" :disabled="loading" @click="emit('close')">取消</button>
      <button type="submit" class="btn-primary-sm" data-agents-save :disabled="loading">{{ loading ? '保存中' : '保存' }}</button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  content: string
  loading?: boolean
  error?: string
}>(), {
  loading: false,
  error: '',
})

const emit = defineEmits<{
  save: [content: string]
  close: []
}>()

const draft = ref(props.content)

watch(() => props.content, (content) => {
  draft.value = content
})

function save() {
  if (!props.loading) emit('save', draft.value)
}
</script>

<style scoped>
.core-agents-editor {
  display: grid;
  gap: 8px;
  margin-top: 10px;
  padding: 10px;
  color: var(--theme-main-text, currentColor);
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text, currentColor) 14%, transparent);
}

.core-agents-editor-head,
.core-agents-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, currentColor) 8%, transparent);
  color: var(--theme-main-text, currentColor);
  font-size: 18px;
  line-height: 1;
}

.core-agents-actions {
  justify-content: flex-end;
}

.core-agents-editor textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 180px;
  resize: vertical;
  border: 1px solid color-mix(in srgb, var(--theme-main-text, currentColor) 20%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text, currentColor) 6%, transparent);
  color: var(--theme-main-text, currentColor);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  padding: 8px;
}

.core-agents-error {
  margin: 0;
  color: var(--red);
  font-size: 12px;
}
</style>

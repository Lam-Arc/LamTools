<template>
  <form class="core-project-create" :aria-busy="loading" @keydown.esc.prevent="!loading && emit('cancel')" @submit.prevent="submit">
    <label>
      <span>项目名称</span>
      <input
        v-model="name"
        data-project-name
        class="field-input"
        autocomplete="off"
        :disabled="loading"
      />
    </label>
    <label>
      <span>项目路径</span>
      <input
        v-model="workRoot"
        data-project-root
        class="field-input"
        autocomplete="off"
        required
        :disabled="loading"
      />
    </label>
    <p v-if="error" class="core-project-error" role="alert">{{ error }}</p>
    <div class="core-project-actions">
      <button type="button" class="btn-cancel" data-project-cancel :disabled="loading" @click="emit('cancel')">取消</button>
      <button type="submit" class="btn-primary-sm" data-project-submit :disabled="loading || !workRoot.trim()">
        {{ loading ? '创建中' : '新建项目' }}
      </button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(defineProps<{
  loading?: boolean
  error?: string
}>(), {
  loading: false,
  error: '',
})

const emit = defineEmits<{
  submit: [payload: { name: string; work_root: string }]
  cancel: []
}>()

const name = ref('')
const workRoot = ref('')

function submit() {
  const root = workRoot.value.trim()
  if (!root || props.loading) return
  emit('submit', { name: name.value.trim(), work_root: root })
}
</script>

<style scoped>
.core-project-create {
  display: grid;
  gap: 8px;
  min-width: min(300px, calc(100vw - 48px));
  padding: 10px;
  border: 1px solid color-mix(in srgb, var(--theme-backdrop-text) 14%, transparent);
  border-radius: var(--radius-sm);
  background: var(--theme-backdrop);
  box-shadow: 0 10px 28px color-mix(in srgb, #000 28%, transparent);
}

.core-project-create label {
  display: grid;
  gap: 4px;
  color: color-mix(in srgb, var(--theme-backdrop-text) 72%, transparent);
  font-size: 12px;
}

.core-project-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.core-project-error {
  margin: 0;
  color: var(--red);
  font-size: 12px;
  line-height: 1.35;
}
</style>

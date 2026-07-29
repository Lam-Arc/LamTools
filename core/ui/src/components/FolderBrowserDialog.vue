<template>
  <Teleport defer to=".workspace-shell">
    <div
      v-if="visible"
      class="fb-dialog-backdrop"
      @mousedown.self="cancel"
      @keydown.escape="cancel"
    >
      <section
        class="fb-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="fb-dialog-title"
        :aria-busy="loading"
      >
        <header class="fb-dialog-header">
          <h2 id="fb-dialog-title">选择目录</h2>
          <button
            type="button"
            class="fb-dialog-close"
            aria-label="关闭"
            @click="cancel"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </header>

        <div class="fb-dialog-body">
          <!-- Left: tree -->
          <aside class="fb-tree-panel">
            <div class="fb-tree-header">
              <span class="fb-current-path" :title="treePath">{{ displayPath }}</span>
              <button
                v-if="canGoUp"
                type="button"
                class="fb-tree-up"
                title="上级目录"
                @click="goUp"
              >↑</button>
            </div>
            <div class="fb-tree-list">
              <div v-if="loading && entries.length === 0" class="fb-tree-loading">加载中...</div>
              <div v-else-if="error" class="fb-tree-error">{{ error }}</div>
              <template v-else>
                <FbTreeItem
                  v-for="entry in entries"
                  :key="entry.name"
                  :entry="entry"
                  :base-path="treePath"
                  :selected-path="selectedPath"
                  :api-base="apiBase"
                  :depth="0"
                  @select="onSelect"
                  @navigate="onNavigate"
                />
              </template>
            </div>
          </aside>
        </div>

        <footer class="fb-dialog-footer">
          <button type="button" class="fb-btn-cancel" @click="cancel">取消</button>
          <button
            type="button"
            class="fb-btn-select"
            :disabled="!selectedPath"
            @click="confirm"
          >选择此目录</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, defineAsyncComponent } from 'vue'

const FbTreeItem = defineAsyncComponent(() => import('./FbTreeItem.vue'))

interface Props {
  modelValue?: boolean
  initialPath?: string
  apiBase?: string
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: false,
  initialPath: '',
  apiBase: '/api/core',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  selected: [path: string]
}>()

const visible = ref(props.modelValue)
const treePath = ref(props.initialPath || '')
const selectedPath = ref('')
const entries = ref<FbEntry[]>([])
const loading = ref(false)
const error = ref('')

interface FbEntry {
  name: string
  type: 'directory' | 'file'
  size: number
  ext: string
  path?: string
}

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (val) {
    treePath.value = props.initialPath || ''
    selectedPath.value = ''
    entries.value = []
    error.value = ''
    loadEntries()
  }
})

watch(visible, (val) => {
  if (!val) emit('update:modelValue', false)
})

const displayPath = computed(() => {
  if (!treePath.value) return '此电脑'
  return treePath.value
})

const canGoUp = computed(() => {
  return treePath.value.length > 0
})

function getParentPath(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '')
  const parts = trimmed.split(/[/\\]/)
  if (parts.length <= 1) return ''
  parts.pop()
  // On Windows, C:\ stays as-is; on Unix, / or empty
  if (parts.length === 1 && parts[0].length === 2 && parts[0][1] === ':') return parts[0] + '\\'
  return parts.join(parts[0] === '' ? '/' : '\\')
}

async function loadEntries() {
  loading.value = true
  error.value = ''
  try {
    const query = treePath.value ? `?path=${encodeURIComponent(treePath.value)}` : ''
    const res = await fetch(`${props.apiBase}/browse-directory${query}`)
    if (!res.ok) {
      const text = await res.text()
      throw new Error(text || `${res.status}`)
    }
    const data = await res.json()
    entries.value = data.entries || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    entries.value = []
  } finally {
    loading.value = false
  }
}

function onSelect(path: string) {
  selectedPath.value = path
}

function onNavigate(path: string) {
  treePath.value = path
  loadEntries()
}

function goUp() {
  treePath.value = getParentPath(treePath.value)
  loadEntries()
}

function cancel() {
  visible.value = false
}

function confirm() {
  if (selectedPath.value) {
    emit('selected', selectedPath.value)
  }
  visible.value = false
}
</script>

<style scoped>
/* ================================================================
   CSS Custom Properties (all overridable)
   ================================================================ */
.fb-dialog-backdrop {
  --fb-bg: var(--theme-main-background, #111);
  --fb-text: var(--theme-main-text, #f2efeb);
  --fb-muted: color-mix(in srgb, var(--fb-text) 60%, transparent);
  --fb-border: color-mix(in srgb, var(--fb-text) 12%, transparent);
  --fb-hover-bg: color-mix(in srgb, var(--fb-text) 7%, transparent);
  --fb-selected-bg: color-mix(in srgb, var(--fb-text) 10%, transparent);
  --fb-accent: var(--blue, #79bcff);
  --fb-accent-text: #111;
  --fb-width: 640px;
  --fb-height: 460px;
  --fb-radius: 14px;
  --fb-font-size: 13px;
  --fb-indent: 18px;
}

.fb-dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: calc(var(--z-modal-backdrop, 80) + 3);
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(0 0 0 / 38%);
}

.fb-dialog {
  width: min(var(--fb-width), 100%);
  max-height: calc(100dvh - 48px);
  display: flex;
  flex-direction: column;
  border: 1px solid var(--fb-border);
  border-radius: var(--fb-radius);
  background: var(--fb-bg);
  color: var(--fb-text);
  box-shadow: 0 8px 32px rgb(0 0 0 / 24%);
  overflow: hidden;
}

.fb-dialog-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px 0;
}

.fb-dialog-header h2 {
  margin: 0;
  font-size: 17px;
  font-weight: 700;
}

.fb-dialog-close {
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--fb-muted);
  display: grid;
  place-items: center;
  cursor: pointer;
}

.fb-dialog-close:hover {
  background: var(--fb-hover-bg);
  color: var(--fb-text);
}

.fb-dialog-close svg {
  width: 18px;
  height: 18px;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.fb-dialog-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 0;
  padding: 14px 20px;
  overflow: hidden;
}

/* Left tree panel */
.fb-tree-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--fb-border);
  border-radius: 10px;
  overflow: hidden;
}

.fb-tree-header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--fb-border);
  background: color-mix(in srgb, var(--fb-text) 3%, transparent);
}

.fb-current-path {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-family: var(--font-mono, monospace);
  color: var(--fb-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fb-tree-up {
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: var(--fb-muted);
  font-size: 14px;
  display: grid;
  place-items: center;
  cursor: pointer;
  flex: 0 0 auto;
}

.fb-tree-up:hover {
  background: var(--fb-hover-bg);
  color: var(--fb-text);
}

.fb-tree-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 4px 0;
  scrollbar-width: thin;
  scrollbar-color: color-mix(in srgb, var(--fb-text) 18%, transparent) transparent;
}

.fb-tree-loading,
.fb-tree-error {
  padding: 12px 14px;
  font-size: 12px;
  color: var(--fb-muted);
}

.fb-tree-error {
  color: var(--red, #f55);
}

/* Footer */
.fb-dialog-footer {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 20px;
  border-top: 1px solid var(--fb-border);
}

.fb-btn-cancel,
.fb-btn-select {
  min-width: 80px;
  height: 36px;
  border-radius: 8px;
  padding: 0 16px;
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
}

.fb-btn-cancel {
  border: 0;
  background: transparent;
  color: var(--fb-muted);
}

.fb-btn-cancel:hover {
  background: var(--fb-hover-bg);
  color: var(--fb-text);
}

.fb-btn-select {
  border: 1px solid var(--fb-accent);
  background: var(--fb-accent);
  color: var(--fb-accent-text);
}

.fb-btn-select:hover:not(:disabled) {
  opacity: 0.88;
}

.fb-btn-select:disabled {
  opacity: 0.4;
  cursor: default;
}

/* Responsive */
@media (max-width: 640px) {
  .fb-dialog-backdrop { padding: 12px; }
  .fb-dialog { max-height: calc(100dvh - 24px); }
  .fb-dialog-body { flex-direction: column; padding: 10px 14px; }
  .fb-tree-panel { flex: 1; }
  .fb-dialog-footer { padding: 10px 14px; }
}
</style>
<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>工具模式</h1>
      <p>管理 loadtools.jsonc 的模式工具集：每个模式是一个工具白名单，切换模式后模型只能使用该模式允许的工具（执行期强制拦截）。空列表 = 全部工具可用。</p>
    </header>

    <p v-if="error" class="skill-error" role="alert">{{ error }}</p>

    <article class="setting-card">
      <div class="subhead">
        <span class="muted">{{ loading ? '加载中…' : sourceLabel }}</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading" @click="fetchModes">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || saving || !dirty" @click="saveModes">保存</button>
        </div>
      </div>
      <p class="hook-meta">
        保存到 <code>~/.lam/core/config/loadtools.jsonc</code>。CLI：<code>core loadtools show / edit-mode --mode &lt;name&gt; --tools a,b,c</code>
      </p>
    </article>

    <!-- Mode cards -->
    <article v-for="mode in orderedModes" :key="mode.name" class="setting-card mode-card">
      <div class="subhead">
        <input
          v-model="mode.name"
          class="mode-name-input"
          spellcheck="false"
          placeholder="模式名（如 consider）"
          :disabled="loading || saving"
        />
        <div class="subhead-actions">
          <button class="text-btn danger" type="button" :disabled="saving || orderedModes.length <= 1" @click="removeMode(mode)">删除</button>
        </div>
      </div>

      <input
        v-model="mode.description"
        class="mode-desc-input"
        spellcheck="false"
        placeholder="模式描述（注入系统提示词，如：思索模式：仅使用只读工具进行分析）"
        :disabled="loading || saving"
      />

      <label class="unlimited-row">
        <input v-model="mode.unlimited" type="checkbox" :disabled="loading || saving" />
        <span>不限工具（空列表 = 全部工具可用，如 execute）</span>
      </label>

      <template v-if="!mode.unlimited">
        <div v-for="group in catalogGroups" :key="group.category" class="tool-group">
          <div class="tool-group-head">{{ group.label }}</div>
          <div class="tool-checkbox-row">
            <label v-for="tool in group.tools" :key="tool.name" class="tool-checkbox">
              <input
                v-model="mode.selected"
                type="checkbox"
                :value="tool.name"
                :disabled="loading || saving"
              />
              <span>{{ tool.name }}</span>
            </label>
          </div>
        </div>
      </template>
    </article>

    <!-- Add mode -->
    <div class="add-row">
      <button class="small-btn quiet" type="button" :disabled="loading || saving" @click="addMode">＋ 新增模式</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

interface CatalogTool {
  name: string
  category: string
}

interface ModeDraft {
  name: string
  description: string
  tools: string[]
  selected: string[]
  unlimited: boolean
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const CATEGORY_LABELS: Record<string, string> = {
  file_read: '文件读取',
  file_write: '文件写入',
  command: '命令执行',
  git: 'Git',
  web: '网络',
  image: '生图',
  skill: '技能',
  mcp: 'MCP',
  agent: '子代理',
  control: '控制',
  workflow: '工作流',
  other: '其他',
}

const CATEGORY_ORDER = [
  'file_read', 'file_write', 'command', 'git', 'web', 'image',
  'skill', 'mcp', 'agent', 'control', 'workflow', 'other',
]

const modes = reactive<ModeDraft[]>([])
const catalog = ref<CatalogTool[]>([])
const source = ref<'config' | 'builtin'>('builtin')
const loading = ref(true)
const saving = ref(false)
const dirty = ref(false)
const error = ref('')
// Guards the deep watch below: fetchModes/saveModes rebuild the array and
// must not mark the freshly-loaded server state as dirty (audit 17).
const hydrating = ref(false)

// Any edit to a mode — name, description, tool selection, unlimited toggle —
// must enable the save button; previously only add/remove did (audit 17 S2).
watch(modes, () => {
  if (!loading.value && !saving.value && !hydrating.value) dirty.value = true
}, { deep: true })

const sourceLabel = computed(() =>
  source.value === 'config'
    ? '来源：配置文件（~/.lam/core/config/loadtools.jsonc）'
    : '来源：内置默认（尚未保存，编辑后点击保存生成配置文件）',
)

const catalogGroups = computed(() => {
  const grouped: Record<string, CatalogTool[]> = {}
  for (const tool of catalog.value) {
    ;(grouped[tool.category] ??= []).push(tool)
  }
  return CATEGORY_ORDER
    .filter(category => grouped[category]?.length)
    .map(category => ({
      category,
      label: CATEGORY_LABELS[category] || category,
      tools: grouped[category],
    }))
})

const orderedModes = computed(() => [...modes].sort((a, b) => a.name.localeCompare(b.name, 'zh')))

async function fetchModes() {
  loading.value = true
  hydrating.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.loadtools.get')
    modes.splice(0, modes.length)
    const rawModes = (result.modes ?? {}) as Record<string, { description?: string; tools?: string[] }>
    for (const [name, mode] of Object.entries(rawModes)) {
      const tools = Array.isArray(mode.tools) ? mode.tools.map(String) : []
      modes.push({
        name,
        description: String(mode.description ?? ''),
        tools: [...tools],
        selected: [...tools],
        unlimited: tools.length === 0,
      })
    }
    catalog.value = Array.isArray(result.catalog) ? result.catalog as CatalogTool[] : []
    source.value = result.source === 'config' ? 'config' : 'builtin'
    dirty.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    hydrating.value = false
    loading.value = false
  }
}

function addMode() {
  const base = 'new-mode'
  let name = base
  let index = 2
  while (modes.some(m => m.name === name)) {
    name = `${base}-${index++}`
  }
  modes.push({ name, description: '', tools: [], selected: [], unlimited: false })
  dirty.value = true
}

function removeMode(mode: ModeDraft) {
  const index = modes.indexOf(mode)
  if (index >= 0) {
    modes.splice(index, 1)
    dirty.value = true
  }
}

async function saveModes() {
  saving.value = true
  hydrating.value = true
  error.value = ''
  try {
    // Validate before touching the payload: empty or duplicate mode names
    // must abort with a visible error instead of silently dropping modes
    // (audit 17 S3).
    const seen = new Set<string>()
    for (const mode of modes) {
      const name = mode.name.trim()
      if (!name) {
        error.value = '模式名不能为空，已取消保存'
        return
      }
      if (seen.has(name)) {
        error.value = `模式名重复：${name}，已取消保存`
        return
      }
      seen.add(name)
    }
    const payload: Record<string, { description: string; tools: string[] }> = {}
    for (const mode of modes) {
      payload[mode.name.trim()] = {
        description: mode.description.trim(),
        tools: mode.unlimited ? [] : [...mode.selected],
      }
    }
    const result = await props.requestRpc('config.loadtools.set', { modes: payload })
    source.value = 'config'
    // Re-read so server-side canonicalization is reflected locally.
    const rawModes = (result.modes ?? {}) as Record<string, { description?: string; tools?: string[] }>
    modes.splice(0, modes.length)
    for (const [name, mode] of Object.entries(rawModes)) {
      const tools = Array.isArray(mode.tools) ? mode.tools.map(String) : []
      modes.push({
        name,
        description: String(mode.description ?? ''),
        tools: [...tools],
        selected: [...tools],
        unlimited: tools.length === 0,
      })
    }
    dirty.value = false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    hydrating.value = false
    saving.value = false
  }
}

onMounted(fetchModes)
</script>

<style scoped>
.mode-card {
  margin-top: 10px;
}

.mode-name-input {
  flex: 1;
  min-width: 0;
  padding: 4px 8px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: inherit;
  font-size: 14px;
  font-weight: 600;
}

.mode-desc-input {
  width: 100%;
  margin-top: 8px;
  padding: 6px 8px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: inherit;
  font-size: 13px;
}

.unlimited-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 13px;
  cursor: pointer;
}

.tool-group {
  margin-top: 10px;
}

.tool-group-head {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
  opacity: 0.85;
}

.tool-checkbox-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
}

.tool-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  cursor: pointer;
  font-family: var(--font-mono);
}

/* ── 主题化 checkbox（对齐 layout.css toggle-line 配方：绿勾选中态）── */
.unlimited-row input[type="checkbox"],
.tool-checkbox input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  min-width: 14px;
  min-height: 14px;
  margin: 0;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 24%, transparent);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  position: relative;
  display: grid;
  place-items: center;
  transition: background .12s ease, border-color .12s ease;
}
.unlimited-row input[type="checkbox"]:checked,
.tool-checkbox input[type="checkbox"]:checked {
  border-color: var(--green, #32d17d);
  background: var(--green, #32d17d);
}
.unlimited-row input[type="checkbox"]:checked::after,
.tool-checkbox input[type="checkbox"]:checked::after {
  content: "";
  width: 7px;
  height: 4px;
  border-left: 2px solid color-mix(in srgb, var(--settings-main-text, #fff) 92%, transparent);
  border-bottom: 2px solid color-mix(in srgb, var(--settings-main-text, #fff) 92%, transparent);
  transform: rotate(-45deg) translateY(-1px);
}

.subhead-actions {
  display: flex;
  gap: 6px;
}

.hook-meta {
  margin-top: 8px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}
</style>

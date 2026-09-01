<template>
  <section class="settings-panel settings-panel--editor loadtools-panel">
    <header class="settings-title loadtools-title">
      <div class="loadtools-title-copy">
        <h1>工具模式</h1>
        <p>为不同工作模式配置模型可用的工具。</p>
      </div>

      <div class="loadtools-title-actions">
        <span v-if="dirty" class="loadtools-dirty" role="status">
          <span class="loadtools-dirty-dot" aria-hidden="true" />
          有未保存的修改
        </span>
        <button class="text-btn loadtools-refresh" type="button" :disabled="loading || saving" @click="fetchModes">
          <RefreshCw :size="14" :stroke-width="1.9" aria-hidden="true" />
          <span>刷新</span>
        </button>
        <button class="small-btn primary loadtools-save" type="button" :disabled="loading || saving || !dirty" @click="saveModes">
          <Save :size="15" :stroke-width="1.9" aria-hidden="true" />
          <span>{{ saving ? '保存中…' : '保存' }}</span>
        </button>
      </div>
    </header>

    <p v-if="error" class="skill-error" role="alert">{{ error }}</p>

    <div v-if="loading && !modes.length" class="settings-surface loadtools-loading" role="status">
      <span class="loadtools-loading-dot" aria-hidden="true" />
      正在加载工具模式…
    </div>

    <div v-else class="settings-surface loadtools-workspace">
      <div class="loadtools-overview-bar">
        <dl class="loadtools-overview-metrics" aria-label="工具模式概览">
          <div>
            <dt>工作模式</dt>
            <dd>{{ orderedModes.length }}</dd>
            <span>已配置工作方式</span>
          </div>
          <div>
            <dt>基础工具</dt>
            <dd>{{ catalog.length }}</dd>
            <span>可供模式选择</span>
          </div>
          <div>
            <dt>配置来源</dt>
            <dd>{{ sourceLabel }}</dd>
            <span>{{ loading ? '正在同步…' : '当前已加载' }}</span>
          </div>
        </dl>

        <button class="small-btn quiet loadtools-add-top" type="button" :disabled="loading || saving" @click="addMode">
          <Plus :size="15" :stroke-width="2" aria-hidden="true" />
          <span>新增模式</span>
        </button>
      </div>

      <div class="loadtools-workspace-body">
        <aside class="mode-rail" aria-label="工作模式列表">
          <div class="mode-rail-head">
            <div class="mode-rail-title">
              <strong>模式</strong>
              <span>{{ orderedModes.length }}</span>
            </div>
          </div>

          <label class="loadtools-search mode-search">
            <span class="sr-only">搜索模式</span>
            <Search :size="14" :stroke-width="1.8" aria-hidden="true" />
            <input v-model.trim="modeQuery" type="search" placeholder="搜索模式" />
          </label>

          <div class="mode-picker" role="listbox" aria-label="选择工作模式">
            <button
              v-for="mode in filteredModes"
              :key="mode.name"
              class="mode-picker-item"
              :class="{ 'is-selected': selectedMode === mode }"
              type="button"
              role="option"
              :aria-selected="selectedMode === mode ? 'true' : 'false'"
              @click="selectMode(mode)"
            >
              <span class="mode-picker-copy">
                <strong>{{ mode.name }}</strong>
                <span>{{ modeTranslation(mode.name) }}</span>
              </span>
              <span class="mode-picker-meta">
                <span class="mode-picker-dot" :class="{ 'is-full': mode.unlimited }" aria-hidden="true" />
                {{ modeToolSummary(mode) }}
              </span>
            </button>

            <div v-if="!filteredModes.length" class="mode-rail-empty">
              <strong>没有匹配的模式</strong>
              <small>换个关键词试试</small>
            </div>
          </div>

          <div class="mode-rail-footer">
            <button class="mode-create-btn" type="button" :disabled="loading || saving" @click="addMode">
              <Plus :size="15" :stroke-width="2" aria-hidden="true" />
              <span>新增模式</span>
            </button>
            <span class="mode-source">{{ sourceLabel }}</span>
          </div>
        </aside>

        <section v-if="selectedMode" class="mode-detail" aria-label="工作模式详情">
          <header class="mode-detail-head">
            <div class="mode-detail-identity">
              <span class="mode-detail-context">当前模式</span>
              <div class="mode-name-line">
                <input
                  v-model="selectedMode.name"
                  class="mode-name-input"
                  spellcheck="false"
                  placeholder="模式名"
                  :disabled="loading || saving"
                />
                <span class="mode-name-label">{{ modeTranslation(selectedMode.name) }}</span>
              </div>
              <label class="mode-description-field">
                <span class="sr-only">模式说明</span>
                <input
                  v-model="selectedMode.description"
                  class="mode-description-input"
                  spellcheck="false"
                  placeholder="添加一条简短说明"
                  :disabled="loading || saving"
                />
              </label>
              <div class="mode-meta">
                <span class="mode-access-state" :class="{ 'is-full': selectedMode.unlimited }">
                  <ShieldCheck v-if="!selectedMode.unlimited" :size="13" :stroke-width="2" aria-hidden="true" />
                  <Wrench v-else :size="13" :stroke-width="2" aria-hidden="true" />
                  {{ selectedMode.unlimited ? '全部工具可用' : '按清单使用工具' }}
                </span>
                <span class="mode-meta-separator" aria-hidden="true">·</span>
                <span>{{ sourceLabel }}</span>
              </div>
            </div>

            <div class="mode-head-actions">
              <button
                class="text-btn danger"
                type="button"
                :disabled="saving || orderedModes.length <= 1"
                @click="removeMode(selectedMode)"
              >
                <Trash2 :size="14" :stroke-width="1.8" aria-hidden="true" />
                <span>删除</span>
              </button>
            </div>
          </header>

          <section class="tool-section" aria-label="工具列表">
            <header class="tool-section-head">
              <div class="tool-section-title">
                <h2>工具</h2>
                <span>{{ modeToolSummary(selectedMode) }}</span>
              </div>

              <div class="tool-section-actions">
                <label v-if="!selectedMode.unlimited" class="loadtools-search tool-search">
                  <span class="sr-only">搜索工具</span>
                  <Search :size="14" :stroke-width="1.8" aria-hidden="true" />
                  <input v-model.trim="toolQuery" type="search" placeholder="搜索工具" />
                </label>
                <label class="unlimited-toggle">
                  <input v-model="selectedMode.unlimited" type="checkbox" :disabled="loading || saving" />
                  <span>全部工具</span>
                </label>
              </div>
            </header>

            <div v-if="selectedMode.unlimited" class="all-tools-note">
              <Wrench :size="17" :stroke-width="1.8" aria-hidden="true" />
              <div>
                <strong>这个模式可以使用全部工具</strong>
                <span>清除“全部工具”后，可以单独选择需要开放的工具。</span>
              </div>
            </div>

            <div v-else-if="!filteredCatalogGroups.length" class="tool-empty">
              <Search :size="17" :stroke-width="1.8" aria-hidden="true" />
              <span>没有找到匹配的工具</span>
            </div>

            <div v-else class="tool-list">
              <section v-for="group in filteredCatalogGroups" :key="group.category" class="tool-group">
                <header class="tool-group-head">
                  <span class="tool-group-icon" aria-hidden="true">
                    <component :is="categoryIcon(group.category)" :size="15" :stroke-width="1.8" />
                  </span>
                  <strong>{{ group.label }}</strong>
                  <span>{{ selectedToolCount(group.tools) }} / {{ group.tools.length }}</span>
                </header>

                <label v-for="tool in group.tools" :key="tool.name" class="tool-row">
                  <input
                    v-model="selectedMode.selected"
                    type="checkbox"
                    :value="tool.name"
                    :disabled="loading || saving"
                  />
                  <span class="tool-row-copy">
                    <strong>{{ toolLabel(tool.name) }}</strong>
                    <small>{{ tool.name }}</small>
                  </span>
                  <span class="tool-row-state">{{ selectedMode.selected.includes(tool.name) ? '已启用' : '已停用' }}</span>
                </label>
              </section>
            </div>
          </section>
        </section>

        <section v-else class="mode-empty" aria-live="polite">
          <SlidersHorizontal :size="22" :stroke-width="1.7" aria-hidden="true" />
          <strong>还没有工作模式</strong>
          <span>新增一个模式后，就可以设置它能使用的工具。</span>
          <button class="small-btn primary" type="button" :disabled="loading || saving" @click="addMode">
            <Plus :size="15" :stroke-width="2" aria-hidden="true" />
            <span>新增模式</span>
          </button>
        </section>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  Bot,
  FileCode2,
  FileText,
  GitBranch,
  Globe2,
  Image as ImageIcon,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SquareTerminal,
  Trash2,
  Wrench,
  type LucideIcon,
} from 'lucide-vue-next'

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
  other: '其他',
}

const CATEGORY_ORDER = [
  'file_read', 'file_write', 'command', 'git', 'web', 'image',
  'skill', 'mcp', 'agent', 'control', 'other',
]

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  file_read: FileText,
  file_write: FileCode2,
  command: SquareTerminal,
  git: GitBranch,
  web: Globe2,
  image: ImageIcon,
  skill: Sparkles,
  mcp: Server,
  agent: Bot,
  control: SlidersHorizontal,
  other: Wrench,
}

const TOOL_LABELS: Record<string, string> = {
  read_file: '读取文件',
  list_dir: '查看目录',
  search_files: '查找文件',
  search_content: '搜索内容',
  write_file: '写入文件',
  edit_file: '编辑文件',
  delete_path: '删除文件',
  move_path: '移动文件',
  run_command: '运行命令',
  run_shell: '运行 Shell',
  git_status: '查看 Git 状态',
  git_diff: '查看 Git 差异',
  git_log: '查看提交历史',
  git_commit: '提交更改',
  git_push: '推送到远程仓库',
  web_fetch: '访问网页',
  web_search: '搜索网页',
  generate_image: '生成图片',
  load_skill: '加载技能',
  sub_agent: '调用子代理',
}

const MODE_LABELS: Record<string, string> = {
  consider: '思索',
  execute: '执行',
}

const modes = reactive<ModeDraft[]>([])
const catalog = ref<CatalogTool[]>([])
const source = ref<'config' | 'builtin'>('builtin')
const loading = ref(true)
const saving = ref(false)
const dirty = ref(false)
const error = ref('')
const selectedMode = ref<ModeDraft | null>(null)
const modeQuery = ref('')
const toolQuery = ref('')
// Guards the deep watch below: fetchModes/saveModes rebuild the array and
// must not mark the freshly-loaded server state as dirty (audit 17).
const hydrating = ref(false)

// Any edit to a mode — name, description, tool selection, unlimited toggle —
// must enable the save button; previously only add/remove did (audit 17 S2).
watch(modes, () => {
  if (!loading.value && !saving.value && !hydrating.value) dirty.value = true
}, { deep: true, flush: 'sync' })

const sourceLabel = computed(() => (
  source.value === 'config' ? '配置文件' : '内置默认'
))

function modeTranslation(name: string): string {
  return MODE_LABELS[name.trim()] || '自定义'
}

function modeToolSummary(mode: ModeDraft): string {
  return mode.unlimited ? '全部工具' : `${mode.selected.length} 个工具`
}

function toolLabel(name: string): string {
  return TOOL_LABELS[name] || name
}

function categoryIcon(category: string): LucideIcon {
  return CATEGORY_ICONS[category] || Wrench
}

const orderedModes = computed(() => [...modes].sort((a, b) => a.name.localeCompare(b.name, 'zh')))

const filteredModes = computed(() => {
  const query = modeQuery.value.trim().toLocaleLowerCase()
  if (!query) return orderedModes.value
  return orderedModes.value.filter((mode) => (
    `${mode.name} ${modeTranslation(mode.name)} ${mode.description}`.toLocaleLowerCase().includes(query)
  ))
})

const catalogGroups = computed(() => {
  const grouped: Record<string, CatalogTool[]> = {}
  for (const tool of catalog.value) {
    ;(grouped[tool.category] ??= []).push(tool)
  }
  const orderedCategories = [
    ...CATEGORY_ORDER,
    ...Object.keys(grouped)
      .filter(category => !CATEGORY_ORDER.includes(category))
      .sort((a, b) => a.localeCompare(b, 'zh')),
  ]
  return orderedCategories
    .filter(category => (grouped[category]?.length ?? 0) > 0)
    .map(category => ({
      category,
      label: CATEGORY_LABELS[category] || category,
      tools: grouped[category] || [],
    }))
})

const filteredCatalogGroups = computed(() => {
  const query = toolQuery.value.trim().toLocaleLowerCase()
  if (!query) return catalogGroups.value

  return catalogGroups.value
    .map(group => {
      const groupMatches = group.label.toLocaleLowerCase().includes(query)
      const tools = groupMatches
        ? group.tools
        : group.tools.filter(tool => `${toolLabel(tool.name)} ${tool.name}`.toLocaleLowerCase().includes(query))
      return { ...group, tools }
    })
    .filter(group => group.tools.length > 0)
})

function selectedToolCount(tools: CatalogTool[]): number {
  const selected = selectedMode.value?.selected || []
  return tools.filter(tool => selected.includes(tool.name)).length
}

function selectMode(mode: ModeDraft): void {
  selectedMode.value = mode
  toolQuery.value = ''
}

async function fetchModes() {
  const previousName = selectedMode.value?.name.trim()
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
    selectedMode.value = modes.find(mode => mode.name === previousName) || modes[0] || null
    modeQuery.value = ''
    toolQuery.value = ''
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
  while (modes.some(mode => mode.name === name)) {
    name = `${base}-${index++}`
  }
  const created: ModeDraft = { name, description: '', tools: [], selected: [], unlimited: false }
  modes.push(created)
  selectedMode.value = created
  modeQuery.value = ''
  toolQuery.value = ''
  dirty.value = true
}

function removeMode(mode: ModeDraft) {
  const index = modes.indexOf(mode)
  if (index < 0) return
  const wasSelected = selectedMode.value === mode
  modes.splice(index, 1)
  if (wasSelected) selectedMode.value = orderedModes.value[0] || null
  dirty.value = true
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

    const selectedName = selectedMode.value?.name.trim()
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
    selectedMode.value = modes.find(mode => mode.name === selectedName) || modes[0] || null
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
.loadtools-panel {
  min-width: 0;
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

:global(.settings-main:has(.loadtools-panel)) {
  overflow: hidden;
}

:global(.settings-main:has(.loadtools-panel) .settings-content) {
  height: 100%;
  min-height: 0;
}

:global(.settings-main:has(.loadtools-panel) .settings-content > .settings-panel) {
  height: 100%;
  min-height: 0;
}

.loadtools-title {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.loadtools-title-copy {
  min-width: 0;
}

.loadtools-title-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  flex: 0 0 auto;
}

.loadtools-dirty {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--orange);
  font-size: 11px;
  white-space: nowrap;
}

.loadtools-dirty-dot,
.mode-picker-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 32%, transparent);
}

.loadtools-dirty-dot {
  background: var(--orange);
}

.loadtools-title-actions .text-btn,
.mode-head-actions .text-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
}

.loadtools-title-actions .small-btn,
.loadtools-add-top,
.mode-empty .small-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  min-height: 36px;
  border-radius: var(--radius-sm);
}

.loadtools-title-actions .small-btn.primary {
  background: var(--settings-control-background, var(--theme-control-background));
  color: var(--settings-control-text, var(--theme-control-text));
}

.loadtools-loading {
  min-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
  font-size: 13px;
}

.loadtools-loading-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--green);
  animation: loadtools-pulse 1.1s ease-in-out infinite;
}

@keyframes loadtools-pulse {
  0%, 100% { opacity: .36; }
  50% { opacity: 1; }
}

.loadtools-workspace {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius);
  background: var(--settings-card-background, var(--settings-main-background, var(--theme-main-background, #111111)));
}

.loadtools-overview-bar {
  flex: 0 0 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
}

.loadtools-overview-metrics {
  min-width: 0;
  flex: 1 1 auto;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-5);
  margin: 0;
}

.loadtools-overview-metrics > div {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.loadtools-overview-metrics dt {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 50%, transparent);
  font-size: 10px;
}

.loadtools-overview-metrics dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 15px;
  font-weight: 720;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.loadtools-overview-metrics span {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.loadtools-add-top {
  flex: 0 0 auto;
  min-width: 112px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  background: color-mix(in srgb, var(--settings-control-background, var(--theme-control-background)) 78%, transparent);
  color: var(--settings-control-text, var(--theme-control-text, #fff));
}

.loadtools-workspace-body {
  min-width: 0;
  min-height: 0;
  flex: 1 1 auto;
  display: grid;
  grid-template-columns: minmax(236px, 280px) minmax(0, 1fr);
  overflow: hidden;
}

.mode-rail {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--space-5);
  border-right: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  overflow: hidden;
}

.mode-rail-head {
  min-height: 34px;
  display: flex;
  align-items: center;
  padding-bottom: var(--space-2);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.mode-rail-title {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.mode-rail-title strong {
  font-size: 15px;
}

.mode-rail-title span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-size: 12px;
}

.loadtools-search {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 36px;
  padding: 0 var(--space-3);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-background, var(--theme-control-background)) 70%, transparent);
  color: color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 48%, transparent);
}

.loadtools-search:focus-within {
  color: var(--settings-control-text, var(--theme-control-text, #fff));
}

.loadtools-search input {
  width: 100%;
  min-width: 0;
  min-height: 34px;
  padding: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--settings-control-text, var(--theme-control-text, #fff));
  font-size: 12px;
}

.loadtools-search input::placeholder {
  color: color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 48%, transparent);
}

.mode-search {
  flex: 0 0 auto;
  margin-top: var(--space-3);
}

.mode-picker {
  min-height: 0;
  flex: 1 1 auto;
  display: grid;
  align-content: start;
  gap: var(--space-1);
  margin-top: var(--space-3);
  overflow-y: auto;
}

.mode-picker-item {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--settings-card-text, var(--settings-main-text, var(--theme-main-text, #fff)));
  text-align: left;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.mode-picker-item:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
}

.mode-picker-item.is-selected {
  border-color: color-mix(in srgb, var(--blue) 48%, transparent);
  background: color-mix(in srgb, var(--blue) 12%, transparent);
}

.mode-picker-copy {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.mode-picker-copy strong {
  min-width: 0;
  overflow: hidden;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mode-picker-copy span {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 52%, transparent);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mode-picker-meta {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-size: 10px;
  white-space: nowrap;
}

.mode-picker-dot.is-full {
  background: var(--green);
}

.mode-rail-empty {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-4) var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
  text-align: center;
}

.mode-rail-empty strong {
  font-size: 12px;
}

.mode-rail-empty small {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 11px;
}

.mode-rail-footer {
  flex: 0 0 auto;
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 9%, transparent);
}

.mode-create-btn {
  min-height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  border: 1px dashed color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 18%, transparent);
  border-radius: var(--radius);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 62%, transparent);
  font-size: 13px;
  font-weight: 650;
}

.mode-create-btn:hover {
  border-color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 32%, transparent);
  color: var(--settings-main-text, var(--theme-main-text, #fff));
}

.mode-source {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 10px;
  text-align: center;
}

.mode-detail {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--space-5);
  overflow: auto;
}

.mode-detail-head {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
}

.mode-detail-identity {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.mode-detail-context {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  font-size: 11px;
}

.mode-name-line {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.mode-name-input {
  width: min(100%, 320px);
  min-width: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  outline: 0;
  background: transparent;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 21px;
  font-weight: 760;
  letter-spacing: -.02em;
}

.mode-name-input::placeholder {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
}

.mode-name-label {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
  font-size: 13px;
  font-weight: 650;
}

.mode-description-field {
  min-width: 0;
  display: block;
}

.mode-description-input {
  width: min(100%, 620px);
  min-width: 0;
  min-height: 26px;
  padding: 0;
  border: 0;
  border-radius: 0;
  outline: 0;
  background: transparent;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 64%, transparent);
  font-size: 12px;
}

.mode-description-input::placeholder {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 38%, transparent);
}

.mode-meta {
  min-width: 0;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 10px;
}

.mode-access-state {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--green);
}

.mode-access-state.is-full {
  color: var(--orange);
}

.mode-meta-separator {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 28%, transparent);
}

.mode-head-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.tool-section {
  min-width: 0;
  padding-top: var(--space-5);
}

.tool-section-head {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  padding-bottom: var(--space-3);
}

.tool-section-title {
  min-width: 0;
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
}

.tool-section-title h2 {
  margin: 0;
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 16px;
}

.tool-section-title span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 46%, transparent);
  font-size: 11px;
}

.tool-section-actions {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
}

.tool-search {
  width: min(220px, 32vw);
}

.unlimited-toggle {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding-inline: var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 68%, transparent);
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}

.unlimited-toggle input,
.tool-row input {
  appearance: none;
  -webkit-appearance: none;
  width: 16px;
  height: 16px;
  min-width: 16px;
  margin: 0;
  padding: 0;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 30%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-text, var(--theme-control-text, #fff)) 72%, transparent);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.unlimited-toggle input::after,
.tool-row input::after {
  content: '';
  width: 7px;
  height: 4px;
  border-left: 2px solid var(--settings-control-background, var(--theme-control-background, #111));
  border-bottom: 2px solid var(--settings-control-background, var(--theme-control-background, #111));
  opacity: 0;
  transform: rotate(-45deg) translateY(-1px);
}

.unlimited-toggle input:checked,
.tool-row input:checked {
  border-color: color-mix(in srgb, var(--green) 72%, transparent);
  background: var(--green);
}

.unlimited-toggle input:checked::after,
.tool-row input:checked::after {
  opacity: 1;
}

.unlimited-toggle input:disabled,
.tool-row input:disabled {
  cursor: default;
  opacity: .45;
}

.all-tools-note {
  min-height: 86px;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid color-mix(in srgb, var(--orange) 22%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--orange) 7%, transparent);
  color: var(--orange);
}

.all-tools-note > div {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.all-tools-note strong {
  color: color-mix(in srgb, var(--orange) 76%, var(--settings-main-text, var(--theme-main-text, #fff)));
  font-size: 13px;
}

.all-tools-note span {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 52%, transparent);
  font-size: 11px;
}

.tool-list {
  min-width: 0;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  border-radius: var(--radius-sm);
}

.tool-group + .tool-group {
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
}

.tool-group-head {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3);
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 5%, transparent);
}

.tool-group-icon {
  display: inline-flex;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 58%, transparent);
}

.tool-group-head strong {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 78%, transparent);
  font-size: 12px;
}

.tool-group-head > span:last-child {
  margin-left: auto;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 10px;
}

.tool-row {
  min-width: 0;
  min-height: 48px;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 8%, transparent);
  color: var(--settings-card-text, var(--settings-main-text, var(--theme-main-text, #fff)));
  cursor: pointer;
}

.tool-row:hover {
  background: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) var(--alpha-hover), transparent);
}

.tool-row-copy {
  min-width: 0;
  display: grid;
  gap: var(--space-1);
}

.tool-row-copy strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row-copy small {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-family: var(--font-mono);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row-state {
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 42%, transparent);
  font-size: 10px;
  white-space: nowrap;
}

.tool-row input:checked + .tool-row-copy + .tool-row-state {
  color: var(--green);
}

.tool-empty,
.mode-empty {
  min-height: 160px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 48%, transparent);
  text-align: center;
}

.tool-empty span,
.mode-empty span {
  font-size: 12px;
}

.mode-empty {
  min-height: 420px;
  padding: var(--space-6);
}

.mode-empty strong {
  color: var(--settings-main-text, var(--theme-main-text, #fff));
  font-size: 15px;
}

@media (max-width: 920px) {
  .loadtools-title {
    align-items: stretch;
    flex-direction: column;
  }

  .loadtools-title-actions {
    justify-content: flex-start;
  }
}

@media (max-width: 799px) {
  .loadtools-workspace {
    overflow: visible;
  }

  .loadtools-overview-bar {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-3);
  }

  .loadtools-workspace-body {
    grid-template-columns: 1fr;
    overflow: visible;
  }

  .mode-rail {
    min-height: 0;
    padding: var(--space-4);
    border-right: 0;
    border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, var(--theme-main-text, #fff)) 10%, transparent);
  }

  .mode-picker {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .mode-picker-item {
    flex: 0 0 min(240px, 72vw);
  }

  .mode-rail-footer {
    margin-top: var(--space-3);
  }

  .mode-detail {
    padding: var(--space-5) var(--space-4) var(--space-4);
    overflow: visible;
  }
}

@media (max-width: 600px) {
  .loadtools-overview-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-3) var(--space-4);
  }

  .loadtools-add-top,
  .tool-search {
    width: 100%;
  }

  .tool-section-actions {
    align-items: stretch;
    flex-direction: column;
    justify-content: flex-start;
  }

  .tool-section-head {
    align-items: stretch;
    flex-direction: column;
    gap: var(--space-3);
  }

  .unlimited-toggle {
    padding-inline: 0;
  }

  .mode-detail-head {
    flex-direction: column;
  }

  .mode-head-actions {
    align-self: flex-end;
  }
}

@media (max-width: 420px) {
  .loadtools-title-actions {
    align-items: stretch;
    flex-wrap: wrap;
  }

  .loadtools-dirty {
    width: 100%;
  }

  .loadtools-overview-metrics {
    grid-template-columns: 1fr 1fr;
  }

  .mode-name-line {
    align-items: flex-start;
    flex-direction: column;
    gap: 0;
  }

  .mode-name-input,
  .mode-description-input {
    width: 100%;
  }

  .tool-row {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .tool-row-state {
    grid-column: 2;
  }
}

@media (prefers-reduced-motion: reduce) {
  .loadtools-loading-dot,
  .mode-picker-item {
    animation: none;
    transition: none;
  }
}
</style>

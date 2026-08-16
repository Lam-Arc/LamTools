<template>
  <section class="settings-panel plugins-root">
    <header class="settings-title">
      <h1>插件</h1>
      <p>插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件（git / websearch / imagegen）可禁用、不可卸载。</p>
    </header>

    <p v-if="error" class="skill-error" role="alert">{{ error }}</p>

    <!-- 安装区：拖拽 zip 直装 / 粘贴 Release URL -->
    <article class="setting-card install-card">
      <h3>安装插件</h3>
      <div
        class="install-dropzone"
        :class="{ 'is-drag': dragActive }"
        @dragover.prevent="onDragOver"
        @dragenter.prevent="dragActive = true"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
      >
        <p class="dropzone-hint">{{ dragActive ? '松开以安装' : '拖拽 .zip 文件到此处安装' }}</p>
        <p class="dropzone-sub">或粘贴 GitHub Release URL：</p>
        <div class="install-form">
          <select v-model="installSource" class="field-input">
            <option value="url">GitHub Release URL</option>
            <option value="local">本地目录</option>
            <option value="zip">本地 zip 路径</option>
          </select>
          <input
            v-model="installPath"
            class="field-input install-path"
            type="text"
            :placeholder="installSource === 'url' ? 'https://github.com/{owner}/{repo}/releases/…/{asset}.zip' : '插件目录或 .zip 路径'"
          />
          <button class="small-btn" type="button" :disabled="installing || !installPath.trim()" @click="doInstall">
            {{ installing ? '安装中…' : '安装' }}
          </button>
        </div>
      </div>
      <p v-if="installNotice" class="install-notice">{{ installNotice }}</p>
    </article>

    <div class="subhead">
      <span class="muted">{{ loading ? '加载中…' : `共 ${plugins.length} 个 · 已启用 ${enabledCount}` }}</span>
      <button class="text-btn" type="button" @click="fetchPlugins">刷新</button>
    </div>

    <!-- 插件列表 -->
    <div class="provider-list">
      <section class="provider-group">
        <header class="provider-head">
          <div class="provider-identity">
            <strong>已安装插件</strong>
            <span>{{ plugins.length }} 个</span>
          </div>
        </header>
        <div class="model-list">
          <div v-for="plugin in plugins" :key="plugin.name" class="model-row plugin-row" :class="{ 'is-disabled': !plugin.enabled }">
            <div class="model-identity">
              <button class="plugin-name-btn" type="button" @click="openConfig(plugin)">
                <strong>{{ plugin.name }}</strong>
                <span class="plugin-version">{{ plugin.version }}</span>
              </button>
              <span>{{ plugin.description }}</span>
              <span class="plugin-meta">
                <span class="hook-status" :class="depsClass(plugin)">{{ depsLabel(plugin) }}</span>
                <span class="hook-status is-plugins-tools">{{ toolCount(plugin) }} 工具</span>
                <span v-if="isBundled(plugin)" class="hook-status is-bundled">内置</span>
              </span>
            </div>
            <div class="row-actions">
              <button
                class="text-btn toggle-btn"
                :class="{ 'is-on': plugin.enabled }"
                type="button"
                :aria-label="plugin.enabled ? `禁用插件 ${plugin.name}` : `启用插件 ${plugin.name}`"
                :title="plugin.enabled ? '已启用' : '已禁用'"
                @click="toggleEnabled(plugin)"
              >
                <ToggleRight v-if="plugin.enabled" :size="16" :stroke-width="1.8" aria-hidden="true" />
                <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <button
                v-if="plugin.config_schema || plugin.dependencies.length || hasAssets(plugin)"
                class="text-btn icon-btn"
                type="button"
                aria-label="配置"
                title="配置"
                @click="openConfig(plugin)"
              >
                <Settings :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <button
                v-if="!isBundled(plugin)"
                class="text-btn danger icon-btn"
                type="button"
                aria-label="卸载"
                title="卸载"
                @click="doUninstall(plugin)"
              >
                <Trash2 :size="15" :stroke-width="1.8" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>

    <p v-if="errors.length" class="skill-error plugin-errors" role="alert">
      <span v-for="err in errors" :key="err.name">{{ err.name }}: {{ err.error }}</span>
    </p>

    <!-- 插件配置卡片（浮层，非行内展开） -->
    <div v-if="configPlugin" class="editor-overlay" @click.self="closeConfig">
      <div class="editor-popover plugin-config-popover">
        <p v-if="error" class="skill-error editor-error" role="alert">{{ error }}</p>
        <div class="editor-popover-head">
          <h3>{{ configPlugin.name }} <span class="plugin-version">{{ configPlugin.version }}</span></h3>
          <button type="button" class="editor-popover-close" aria-label="关闭" @click="closeConfig">
            <X :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
        </div>

        <p class="plugin-path">{{ configPlugin.root }}</p>

        <!-- 工具列表 -->
        <div class="detail-block">
          <h4>工具 <span class="asset-count">{{ allTools(configPlugin).length }}</span></h4>
          <div v-if="allTools(configPlugin).length" class="asset-list">
            <div v-for="tool in allTools(configPlugin)" :key="tool.name" class="asset-row">
              <span class="asset-name">{{ tool.name }}</span>
              <span class="asset-tag" :class="permClass(tool.permission)">{{ tool.permission }}</span>
              <span v-if="tool.visibility === 'on_load'" class="asset-tag">on_load</span>
            </div>
          </div>
          <p v-else class="muted">无工具</p>
        </div>

        <!-- 技能列表 -->
        <div class="detail-block">
          <h4>技能 <span class="asset-count">{{ configPlugin.skill_names.length }}</span></h4>
          <div v-if="configPlugin.skill_names.length" class="asset-list">
            <div v-for="name in configPlugin.skill_names" :key="name" class="asset-row">
              <span class="asset-name">{{ name }}</span>
            </div>
          </div>
          <p v-else class="muted">无技能</p>
        </div>

        <!-- 钩子列表 -->
        <div class="detail-block">
          <h4>钩子 <span class="asset-count">{{ configPlugin.hook_summary.length }}</span></h4>
          <div v-if="configPlugin.hook_summary.length" class="asset-list">
            <div v-for="(hook, i) in configPlugin.hook_summary" :key="i" class="asset-row">
              <span class="asset-name">{{ hook.event }}</span>
              <span class="asset-tag">{{ hook.matcher }}</span>
              <span class="asset-tag">{{ hook.type }}</span>
            </div>
          </div>
          <p v-else class="muted">无钩子</p>
        </div>

        <!-- 参数（configSchema 驱动，如生图 api_url/api_key） -->
        <div v-if="configPlugin.config_schema" class="detail-block">
          <h4>参数</h4>
          <div v-if="schemaLoading" class="muted">加载中…</div>
          <div v-else class="config-form">
            <div v-for="prop in schemaProps" :key="prop.key" class="field" :class="{ 'field-boolean': prop.type === 'boolean' }">
              <span class="field-label">{{ prop.label }}<code v-if="prop.type" class="field-type">{{ prop.type }}</code></span>

              <!-- x-control: path-list —— 路径列表：每项可编辑 + 浏览（目录选择），
                   表单级扫描按钮（plugin.config.detect-dirs） -->
              <template v-if="prop.xControl?.kind === 'path-list'">
                <div v-if="prop.xControl.scan" class="scan-row">
                  <button class="small-btn" type="button" :disabled="scanning" @click="scanDirs(prop)">
                    {{ scanning ? '扫描中…' : (prop.xControl.scan.label || '扫描目录') }}
                  </button>
                  <span v-if="scanNotice[prop.key]" class="scan-notice">{{ scanNotice[prop.key] }}</span>
                </div>
                <div class="path-list">
                  <div v-for="(item, index) in arrayDraft[prop.key] || []" :key="index" class="path-row">
                    <input v-model="arrayDraft[prop.key][index]" class="field-input path-input" type="text" />
                    <button class="small-btn" type="button" @click="browsePath(prop, index)">浏览</button>
                    <button class="text-btn danger" type="button" @click="removePath(prop, index)">删除</button>
                  </div>
                  <div class="path-row">
                    <input
                      v-model="newPathDraft[prop.key]"
                      class="field-input path-input"
                      type="text"
                      placeholder="目录路径（工作区相对或绝对）"
                      @keyup.enter="addPath(prop)"
                    />
                    <button class="small-btn" type="button" @click="addPath(prop)">添加</button>
                    <button class="small-btn" type="button" @click="browsePath(prop)">浏览…</button>
                  </div>
                </div>
              </template>

              <!-- x-control: model-select —— 模型下拉：选项来自 config.models.list，
                   按 capability 过滤；无多模态模型 / 加载失败时退化为可自由输入 -->
              <template v-else-if="prop.xControl?.kind === 'model-select'">
                <input
                  v-if="modelOptionsFor(prop).length"
                  v-model="configDraft[prop.key]"
                  class="field-input"
                  type="text"
                  :list="modelListId(prop)"
                  placeholder="选择或输入模型 ID"
                />
                <datalist v-if="modelOptionsFor(prop).length" :id="modelListId(prop)">
                  <option v-for="m in modelOptionsFor(prop)" :key="m.id" :value="m.id">{{ m.display_name || m.model_id }}</option>
                </datalist>
                <input
                  v-else
                  v-model="configDraft[prop.key]"
                  class="field-input"
                  type="text"
                  :placeholder="modelLoadFailed ? '模型列表加载失败，可手动输入' : '暂无可用模型，可手动输入模型 ID'"
                />
              </template>

              <select v-else-if="prop.enum" v-model="configDraft[prop.key]" class="field-input">
                <option v-for="opt in prop.enum" :key="opt" :value="opt">{{ opt }}</option>
              </select>
              <button
                v-else-if="prop.type === 'boolean'"
                type="button"
                class="toggle-btn"
                :class="{ 'is-on': !!configDraft[prop.key] }"
                :aria-label="`${prop.label} 开关`"
                @click="configDraft[prop.key] = !configDraft[prop.key]"
              >
                <ToggleRight v-if="configDraft[prop.key]" :size="16" :stroke-width="1.8" aria-hidden="true" />
                <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
              </button>
              <input
                v-else-if="prop.type === 'number' || prop.type === 'integer'"
                v-model.number="configDraft[prop.key]"
                class="field-input"
                type="number"
              />
              <textarea
                v-else-if="prop.type === 'array'"
                v-model="arrayDraft[prop.key]"
                class="field-input array-input"
                rows="2"
                placeholder="每行一个"
              ></textarea>
              <input v-else v-model="configDraft[prop.key]" class="field-input" type="text" />
            </div>
            <div class="editor-actions">
              <button class="small-btn" type="button" :disabled="configSaving" @click="saveConfig">
                {{ configSaving ? '保存中…' : '保存配置' }}
              </button>
            </div>
          </div>
        </div>

        <!-- 依赖 -->
        <div v-if="configPlugin.dependencies.length" class="detail-block">
          <h4>依赖</h4>
          <p class="muted deps-line">{{ configPlugin.dependencies.join(' · ') }}</p>
          <button
            v-if="configPlugin.deps_status !== 'ok' && configPlugin.deps_status !== 'none'"
            class="small-btn"
            type="button"
            :disabled="installingDeps"
            @click="installDeps(configPlugin)"
          >{{ installingDeps ? '安装中…' : '安装依赖' }}</button>
        </div>
      </div>

      <!-- 目录树对话框：teleport 进 overlay 内（overlay 自身 z-95 高于对话框
           z-modal，只有作为其子节点才能保证对话框可交互） -->
      <FolderBrowserDialog
        v-model="browseDialogOpen"
        :api-base="browseApiBase"
        teleport-target=".plugin-folder-host"
        @selected="onBrowseSelected"
        @update:model-value="onBrowseDismissed"
      />
      <div class="plugin-folder-host"></div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Settings, ToggleLeft, ToggleRight, Trash2, X } from 'lucide-vue-next'
import FolderBrowserDialog from './FolderBrowserDialog.vue'

interface PluginToolDecl {
  name: string
  permission?: string
  visibility?: string
  skill?: string
  handler?: string
  timeout?: number | null
}

interface PluginItem {
  name: string
  version: string
  description: string
  root: string
  enabled: boolean
  skills: string[]
  hooks: string[]
  mcp: string[]
  tools: { path: string; tools: PluginToolDecl[]; error?: string }[]
  skill_names: string[]
  hook_summary: { event: string; matcher: string; type: string }[]
  dependencies: string[]
  deps_status: string
  config_schema: string
}

// x-control 控件协议（插件 configSchema 扩展，见 plugins/lamtools-rag/config/schema.jsonc）：
// path-list = 路径列表（浏览 + 扫描），model-select = 模型下拉（按 capability 过滤）
interface XBrowseSpec {
  type?: string
  mode?: string
}
interface XScanSpec {
  label?: string
  dirs?: string[]
  case_insensitive?: boolean
}
interface XControlSpec {
  kind?: string
  browse?: XBrowseSpec
  scan?: XScanSpec
  capability?: string
}
interface SchemaProp {
  key: string
  label: string
  type: string
  enum?: string[]
  xControl?: XControlSpec
}
interface ModelOption {
  id: string
  model_id: string
  display_name: string
  capability: string
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const plugins = ref<PluginItem[]>([])
const loading = ref(true)
const error = ref('')
const errors = ref<{ name: string; error: string }[]>([])
const installing = ref(false)
const installingDeps = ref(false)
const installNotice = ref('')
const installSource = ref('url')
const installPath = ref('')
const dragActive = ref(false)

// 拖拽安装：Tauri（dragDropEnabled）下拖入文件的 File.path 为真实路径，
// 直接走 plugin.install(source=zip)；非桌面端无 path 时提示改用 URL。
function onDragOver() {
  dragActive.value = true
}
function onDragLeave(e: DragEvent) {
  // 离开子元素不熄灭（relatedTarget 在拖拽区内则忽略）
  const related = e.relatedTarget as Node | null
  if (related && (e.currentTarget as Node).contains(related)) return
  dragActive.value = false
}
async function onDrop(e: DragEvent) {
  dragActive.value = false
  const file = e.dataTransfer?.files?.[0]
  if (!file) return
  const p = (file as File & { path?: string }).path
  if (!p) {
    installNotice.value = '当前环境不支持拖拽安装（请使用 Release URL 粘贴安装）'
    return
  }
  if (!/\.zip$/i.test(p)) {
    installNotice.value = `仅支持 .zip 安装包：${file.name}`
    return
  }
  installNotice.value = ''
  installing.value = true
  error.value = ''
  try {
    await props.requestRpc('plugin.install', { source: 'zip', path: p })
    installNotice.value = `安装成功：${file.name}`
    await fetchPlugins()
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    installing.value = false
  }
}

// 配置卡片（浮层）：当前打开的插件
const configPlugin = ref<PluginItem | null>(null)
const configDraft = ref<Record<string, unknown>>({})
const arrayDraft = ref<Record<string, string[]>>({})
const schemaProps = ref<SchemaProp[]>([])
const schemaLoading = ref(false)
const configSaving = ref(false)

// x-control 状态：工作区根（相对路径转换）、扫描、模型下拉
const workRoot = ref('')
const scanning = ref(false)
const scanNotice = ref<Record<string, string>>({})
const newPathDraft = ref<Record<string, string>>({})
const allModels = ref<ModelOption[]>([])
const modelLoadFailed = ref(false)
const browseDialogOpen = ref(false)
const browseApiBase = ((window as { __LAMTOOLS_API_BASE__?: string }).__LAMTOOLS_API_BASE__) || '/api/core'
// 目录树对话框的挂起回调（非 Tauri 环境回落用）
let pendingBrowseResolve: ((path: string | null) => void) | null = null

const enabledCount = computed(() => plugins.value.filter((p) => p.enabled).length)

const BUNDLED = ['git', 'websearch', 'imagegen']

function isBundled(plugin: PluginItem): boolean {
  return BUNDLED.includes(plugin.name)
}

function toolCount(plugin: PluginItem): number {
  return plugin.tools.reduce((n, tf) => n + (tf.tools?.length || 0), 0)
}

function allTools(plugin: PluginItem): PluginToolDecl[] {
  return plugin.tools.flatMap((tf) => tf.tools || [])
}

function hasAssets(plugin: PluginItem): boolean {
  return plugin.skills.length > 0 || plugin.hooks.length > 0 || plugin.mcp.length > 0 || plugin.tools.length > 0
}

function permClass(permission?: string): string {
  if (permission === 'auto_allow') return 'is-auto'
  if (permission === 'hard_block') return 'is-block'
  return 'is-ask'
}

function depsLabel(plugin: PluginItem): string {
  if (!plugin.dependencies.length) return '无依赖'
  if (plugin.deps_status === 'ok') return '依赖就绪'
  if (plugin.deps_status === 'version_mismatch') return '版本不符'
  if (plugin.deps_status === 'missing') return '依赖缺失'
  return '依赖未知'
}

function depsClass(plugin: PluginItem): string {
  if (plugin.deps_status === 'ok' || !plugin.dependencies.length) return 'is-trusted'
  return 'is-pending-text'
}

async function fetchPlugins() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('plugin.list')
    plugins.value = (result.plugins as PluginItem[]) || []
    errors.value = (result.errors as { name: string; error: string }[]) || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function toggleEnabled(plugin: PluginItem) {
  const next = !plugin.enabled
  try {
    await props.requestRpc(next ? 'plugin.enable' : 'plugin.disable', { name: plugin.name })
    const idx = plugins.value.findIndex((p) => p.name === plugin.name)
    if (idx >= 0) plugins.value[idx] = { ...plugins.value[idx], enabled: next }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function doInstall() {
  if (!installPath.value.trim()) return
  installing.value = true
  installNotice.value = ''
  error.value = ''
  try {
    const payload: Record<string, unknown> = { source: installSource.value }
    if (installSource.value === 'url') payload.url = installPath.value.trim()
    else payload.path = installPath.value.trim()
    await props.requestRpc('plugin.install', payload)
    installNotice.value = '安装成功'
    installPath.value = ''
    await fetchPlugins()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    installing.value = false
  }
}

async function doUninstall(plugin: PluginItem) {
  if (!window.confirm(`卸载插件「${plugin.name}」？将删除其目录${plugin.dependencies.length ? '（依赖默认保留）' : ''}。`)) return
  try {
    await props.requestRpc('plugin.uninstall', { name: plugin.name })
    if (configPlugin.value?.name === plugin.name) closeConfig()
    await fetchPlugins()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function installDeps(plugin: PluginItem) {
  installingDeps.value = true
  error.value = ''
  try {
    await props.requestRpc('plugin.install', { name: plugin.name, install_deps: true })
    await fetchPlugins()
    if (configPlugin.value?.name === plugin.name) {
      configPlugin.value = { ...configPlugin.value, deps_status: 'ok' }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    installingDeps.value = false
  }
}

function openConfig(plugin: PluginItem) {
  configPlugin.value = plugin
  error.value = ''
  if (plugin.config_schema) void loadConfig(plugin)
}

function closeConfig() {
  configPlugin.value = null
  schemaProps.value = []
  workRoot.value = ''
  scanNotice.value = {}
  newPathDraft.value = {}
  allModels.value = []
  modelLoadFailed.value = false
  browseDialogOpen.value = false
  pendingBrowseResolve = null
}

async function loadConfig(plugin: PluginItem) {
  schemaLoading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('plugin.config.get', { name: plugin.name })
    const schema = (result.schema as Record<string, unknown>) || {}
    const propsMap = (schema.properties as Record<string, Record<string, unknown>>) || {}
    schemaProps.value = Object.entries(propsMap).map(([key, spec]) => ({
      key,
      label: key,
      type: String(spec.type || 'string'),
      enum: Array.isArray(spec.enum) ? (spec.enum as string[]) : undefined,
      xControl: parseXControl(spec),
    }))
    workRoot.value = String(result.work_root || '')
    configDraft.value = { ...((result.config as Record<string, unknown>) || {}) }
    arrayDraft.value = {}
    for (const [key, spec] of Object.entries(propsMap)) {
      if (String(spec.type || '') === 'array') {
        const raw = configDraft.value[key]
        arrayDraft.value[key] = Array.isArray(raw) ? raw.map(String) : []
      }
    }
    if (schemaProps.value.some((p) => p.xControl?.kind === 'model-select')) {
      await loadModelOptions()
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    schemaLoading.value = false
  }
}

async function saveConfig() {
  if (!configPlugin.value) return
  configSaving.value = true
  error.value = ''
  const payload = { ...configDraft.value }
  for (const [key, list] of Object.entries(arrayDraft.value)) {
    payload[key] = (list || []).filter((item) => item.trim())
  }
  try {
    await props.requestRpc('plugin.config.update', { name: configPlugin.value.name, config: payload })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    configSaving.value = false
  }
}

// ── x-control: path-list ──────────────────────────────────────────────

function parseXControl(spec: Record<string, unknown>): XControlSpec | undefined {
  const raw = spec['x-control']
  if (!raw || typeof raw !== 'object') return undefined
  const xc = raw as Record<string, unknown>
  const browseRaw = xc.browse
  const scanRaw = xc.scan
  return {
    kind: String(xc.kind || ''),
    browse: browseRaw && typeof browseRaw === 'object'
      ? {
          type: String((browseRaw as Record<string, unknown>).type || ''),
          mode: String((browseRaw as Record<string, unknown>).mode || ''),
        }
      : undefined,
    scan: scanRaw && typeof scanRaw === 'object'
      ? {
          label: String((scanRaw as Record<string, unknown>).label || ''),
          dirs: Array.isArray((scanRaw as Record<string, unknown>).dirs)
            ? ((scanRaw as Record<string, unknown>).dirs as string[])
            : [],
          case_insensitive: Boolean((scanRaw as Record<string, unknown>).case_insensitive),
        }
      : undefined,
    capability: String(xc.capability || ''),
  }
}

function appendPathValue(prop: SchemaProp, value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return false
  if (!arrayDraft.value[prop.key]) arrayDraft.value[prop.key] = []
  const list = arrayDraft.value[prop.key]
  // 重复去重：case_insensitive 时忽略大小写比较
  const fold = (s: string) => (prop.xControl?.scan?.case_insensitive ? s.toLowerCase() : s)
  if (list.some((item) => fold(item.trim()) === fold(trimmed))) return false
  list.push(trimmed)
  return true
}

function addPath(prop: SchemaProp) {
  if (appendPathValue(prop, newPathDraft.value[prop.key] || '')) {
    newPathDraft.value[prop.key] = ''
    scanNotice.value[prop.key] = ''
  }
}

function removePath(prop: SchemaProp, index: number) {
  arrayDraft.value[prop.key]?.splice(index, 1)
}

// 绝对路径 → 工作区相对路径（相对则保留相对，越界则保留绝对并提示）
function toWorkspaceRelative(absolute: string): { value: string; outside: boolean } | null {
  const root = workRoot.value
  if (!root) return null
  const norm = (s: string) => s.replace(/\\/g, '/').replace(/\/+$/, '')
  const target = norm(absolute)
  const base = norm(root)
  const lowerTarget = target.toLowerCase()
  const lowerBase = base.toLowerCase()
  if (lowerTarget === lowerBase) return { value: '.', outside: false }
  if (lowerTarget.startsWith(lowerBase + '/')) return { value: target.slice(lowerBase.length + 1), outside: false }
  return { value: absolute, outside: true }
}

// 目录选择：优先原生选择器（Tauri desktop 已注册 __LAMTOOLS_PICK_DIRECTORY__），
// 非 Tauri（浏览器 dev / demo）回落内置目录树对话框（/api/core/browse-directory）。
// 不新增任何依赖——两条路径都是仓库既有能力。
async function pickDirectory(): Promise<string | null> {
  const nativePick = (window as { __LAMTOOLS_PICK_DIRECTORY__?: () => Promise<string | null> }).__LAMTOOLS_PICK_DIRECTORY__
  if (nativePick) {
    try {
      return await nativePick()
    } catch {
      // 原生选择器异常 → 回落目录树对话框
    }
  }
  return new Promise<string | null>((resolve) => {
    pendingBrowseResolve = resolve
    browseDialogOpen.value = true
  })
}

function onBrowseSelected(path: string) {
  browseDialogOpen.value = false
  pendingBrowseResolve?.(path)
  pendingBrowseResolve = null
}

function onBrowseDismissed() {
  browseDialogOpen.value = false
  pendingBrowseResolve?.(null)
  pendingBrowseResolve = null
}

async function browsePath(prop: SchemaProp, index?: number) {
  const picked = await pickDirectory()
  if (!picked) return
  const converted = toWorkspaceRelative(picked)
  const value = converted?.value ?? picked
  if (index !== undefined) {
    if (!arrayDraft.value[prop.key]) arrayDraft.value[prop.key] = []
    arrayDraft.value[prop.key][index] = value
  } else if (!appendPathValue(prop, value)) {
    scanNotice.value[prop.key] = '该目录已在列表中'
  }
  if (converted?.outside) {
    scanNotice.value[prop.key] = '所选目录在工作区之外，已保留绝对路径'
  }
}

// 表单级扫描：调 plugin.config.detect-dirs，结果追加进列表（重复去重、
// 工作区相对路径），未命中目录在提示里列出
async function scanDirs(prop: SchemaProp) {
  const scan = prop.xControl?.scan
  if (!scan || scanning.value) return
  scanning.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('plugin.config.detect-dirs', {
      dirs: scan.dirs || [],
      case_insensitive: !!scan.case_insensitive,
    })
    const found = ((result.found || []) as { dir: string; path: string; relative?: string }[])
    const missing = ((result.missing || []) as string[]).filter(Boolean)
    if (!arrayDraft.value[prop.key]) arrayDraft.value[prop.key] = []
    const list = arrayDraft.value[prop.key]
    const fold = (s: string) => (scan.case_insensitive ? s.toLowerCase() : s)
    let added = 0
    for (const item of found) {
      const value = (item.relative || item.path).trim()
      if (!value || list.some((existing) => fold(existing.trim()) === fold(value))) continue
      list.push(value)
      added += 1
    }
    const parts: string[] = []
    if (added) parts.push(`已添加 ${added} 个目录`)
    if (missing.length) parts.push(`未找到：${missing.join('、')}`)
    if (!parts.length) parts.push('未发现新目录')
    scanNotice.value[prop.key] = parts.join('；')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    scanning.value = false
  }
}

// ── x-control: model-select ───────────────────────────────────────────

async function loadModelOptions() {
  modelLoadFailed.value = false
  allModels.value = []
  try {
    const result = await props.requestRpc('config.models.list')
    allModels.value = ((result.models || []) as ModelOption[]).filter(
      (m) => m && typeof m === 'object' && typeof m.capability === 'string',
    )
  } catch (e) {
    // 枚举数据加载失败 → 退化为普通输入框（兜底可手动输入）
    modelLoadFailed.value = true
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function modelOptionsFor(prop: SchemaProp): ModelOption[] {
  const capability = prop.xControl?.capability || 'multimodal'
  return allModels.value.filter((m) => m.capability === capability)
}

function modelListId(prop: SchemaProp): string {
  return `plugin-model-${prop.key}`
}

onMounted(fetchPlugins)
</script>

<style scoped>
.plugins-root {
  position: relative;
}

/* 配置卡片浮层：fixed 相对视口定位（面板高度=全部内容高度，absolute 会
   让弹层居中于整个面板而非视口——改为视口定位）；透明遮罩（无压暗/无
   blur），弹层自身带背景/阴影/边框独立呈现，点击外部仍可关闭 */
.plugins-root .editor-overlay {
  position: fixed;
  inset: var(--titlebar-offset, 36px) 0 0 0;
  z-index: 95;
  background: transparent;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  padding: 24px;
}

.install-card {
  padding: 12px 14px;
  margin-bottom: 14px;
}

.install-card h3 {
  margin: 0 0 8px;
  font-size: 14px;
}

.install-dropzone {
  border: 1.5px dashed var(--border, rgba(128, 128, 128, 0.45));
  border-radius: 8px;
  padding: 14px 12px;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.install-dropzone.is-drag {
  border-color: var(--accent, #4f8cff);
  background: color-mix(in srgb, var(--accent, #4f8cff) 8%, transparent);
}

.dropzone-hint {
  margin: 0 0 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text, inherit);
}

.dropzone-sub {
  margin: 0 0 8px;
  font-size: 12px;
  opacity: 0.7;
}

/* 行操作图标按钮（配置/卸载）：图标垂直居中，与文字按钮同高 */
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 2px 4px;
}

.install-form {
  display: grid;
  grid-template-columns: 130px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
}

.install-path {
  font-family: var(--font-mono);
  font-size: 12px;
}

.install-notice {
  margin: 8px 0 0;
  color: var(--green);
  font-size: 12px;
}

.plugin-row {
  align-items: flex-start;
  padding: 10px 12px;
}

.plugin-name-btn {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.plugin-name-btn strong {
  font-size: 14px;
}

.plugin-version {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
}

.plugin-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px !important;
}

.hook-status.is-bundled {
  color: var(--blue);
}

.hook-status.is-plugins-tools {
  color: var(--purple);
}

.plugin-path {
  font-family: var(--font-mono);
  font-size: 11px;
  opacity: .7;
  margin: 0 0 10px;
}

/* ── 配置卡片（浮层）内部 ── */
.plugin-config-popover {
  width: min(620px, 100%);
  display: grid;
  gap: 14px;
}

.plugin-config-popover .editor-popover-head h3 {
  font-size: 16px;
}

.detail-block h4 {
  margin: 0 0 6px;
  font-size: 13px;
}

.asset-count {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--muted);
  margin-left: 4px;
}

.asset-list {
  display: grid;
  gap: 4px;
}

.asset-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}

.asset-name {
  font-family: var(--font-mono);
  font-size: 12px;
  min-width: 0;
}

.asset-tag {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
  color: var(--muted);
}

.asset-tag.is-auto {
  color: var(--green);
}

.asset-tag.is-ask {
  color: var(--orange);
}

.asset-tag.is-block {
  color: var(--red);
}

.config-form {
  display: grid;
  gap: 10px;
  max-width: 560px;
}

.field-label {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  margin-bottom: 4px;
}

/* 布尔参数：开关与标题同行（label 左、开关右），不单起一行 */
.field-boolean {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 32px;
}

.field-boolean .field-label {
  margin-bottom: 0;
}

.field-type {
  font-size: 10px;
  opacity: .6;
}

.array-input {
  font-family: var(--font-mono);
  font-size: 12px;
}

/* ── x-control: path-list ── */
.scan-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.scan-notice {
  font-size: 12px;
  color: var(--muted);
  min-width: 0;
}

.path-list {
  display: grid;
  gap: 6px;
}

.path-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  gap: 6px;
  align-items: center;
}

.path-input {
  font-family: var(--font-mono);
  font-size: 12px;
}

/* 目录树对话框 teleport 宿主（空节点，仅作为挂载点） */
.plugin-folder-host {
  display: contents;
}

.deps-line {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.editor-error {
  margin: 0 0 10px;
}

.text-btn.danger {
  color: var(--red);
}

.plugin-errors {
  display: block;
  margin-top: 12px;
  white-space: pre-line;
}

@media (max-width: 720px) {
  .install-form {
    grid-template-columns: 1fr;
  }
}
</style>

<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>插件</h1>
      <p>插件 = 工具 / 技能 / Hooks / MCP 的统一安装单元。内置插件（git / websearch / imagegen）可禁用、不可卸载。</p>
    </header>

    <p v-if="error" class="skill-error" role="alert">{{ error }}</p>

    <!-- 安装表单 -->
    <article class="setting-card install-card">
      <h3>安装插件</h3>
      <div class="install-form">
        <select v-model="installSource" class="field-input">
          <option value="local">本地目录</option>
          <option value="zip">本地 zip</option>
          <option value="url">GitHub Release URL</option>
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
              <button class="plugin-name-btn" type="button" @click="toggleDetail(plugin.name)">
                <strong>{{ plugin.name }}</strong>
                <span class="plugin-version">{{ plugin.version }}</span>
              </button>
              <span>{{ plugin.description }}</span>
              <span class="plugin-meta">
                <span class="hook-status" :class="depsClass(plugin)">{{ depsLabel(plugin) }}</span>
                <span class="hook-status is-plugins-tools">{{ toolCount(plugin) }} 工具</span>
                <span v-if="isBundled(plugin)" class="hook-status is-bundled">内置</span>
              </span>
              <span v-if="pluginDetail === plugin.name" class="plugin-path">{{ plugin.root }}</span>
            </div>
            <div class="row-actions">
              <button
                class="text-btn"
                :class="{ 'is-on': plugin.enabled }"
                type="button"
                @click="toggleEnabled(plugin)"
              >{{ plugin.enabled ? '已启用' : '已禁用' }}</button>
              <button
                v-if="plugin.config_schema || plugin.dependencies.length"
                class="text-btn"
                type="button"
                @click="toggleDetail(plugin.name)"
              >配置</button>
              <button v-if="!isBundled(plugin)" class="text-btn danger" type="button" @click="doUninstall(plugin)">卸载</button>
            </div>

            <!-- 展开详情：资产 + 配置 -->
            <div v-if="pluginDetail === plugin.name" class="plugin-detail">
              <div class="detail-block">
                <h4>资产</h4>
                <div v-if="plugin.skills.length || plugin.hooks.length || plugin.tools.length" class="detail-assets">
                  <span v-for="tool in allTools(plugin)" :key="tool.name" class="asset-chip">{{ tool.name }}</span>
                  <span v-for="path in plugin.skills" :key="path" class="asset-chip">skill</span>
                  <span v-for="path in plugin.hooks" :key="path" class="asset-chip">hooks</span>
                </div>
                <p v-else class="muted">无资产（仅管理单元）。</p>
              </div>

              <div v-if="plugin.config_schema" class="detail-block">
                <h4>配置</h4>
                <div v-if="schemaLoading" class="muted">加载中…</div>
                <div v-else class="config-form">
                  <label v-for="prop in schemaProps" :key="prop.key" class="field">
                    <span class="field-label">{{ prop.label }}<code v-if="prop.type" class="field-type">{{ prop.type }}</code></span>
                    <select v-if="prop.enum" v-model="configDraft[prop.key]" class="field-input">
                      <option v-for="opt in prop.enum" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <input
                      v-else-if="prop.type === 'boolean'"
                      v-model="configDraft[prop.key]"
                      class="checkbox"
                      type="checkbox"
                    />
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
                  </label>
                  <div class="editor-actions">
                    <button class="small-btn" type="button" :disabled="configSaving" @click="saveConfig(plugin)">
                      {{ configSaving ? '保存中…' : '保存配置' }}
                    </button>
                  </div>
                </div>
              </div>

              <div v-if="plugin.dependencies.length" class="detail-block">
                <h4>依赖</h4>
                <p class="muted deps-line">{{ plugin.dependencies.join(' · ') }}</p>
                <button
                  v-if="plugin.deps_status !== 'ok' && plugin.deps_status !== 'none'"
                  class="small-btn"
                  type="button"
                  :disabled="installingDeps"
                  @click="installDeps(plugin)"
                >{{ installingDeps ? '安装中…' : '安装依赖' }}</button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <p v-if="errors.length" class="skill-error plugin-errors" role="alert">
      <span v-for="err in errors" :key="err.name">{{ err.name }}: {{ err.error }}</span>
    </p>

    <!-- 系统级 Skills / Hooks 区块（B6：原 tab 迁入，复用原组件） -->
    <div class="system-block">
      <CoreSkillsEditor :request-rpc="props.requestRpc" />
      <CoreHooksEditor :request-rpc="props.requestRpc" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import CoreSkillsEditor from './CoreSkillsEditor.vue'
import CoreHooksEditor from './CoreHooksEditor.vue'

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
  dependencies: string[]
  deps_status: string
  config_schema: string
}

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const plugins = ref<PluginItem[]>([])
const loading = ref(true)
const error = ref('')
const errors = ref<{ name: string; error: string }[]>([])
const pluginDetail = ref('')
const installing = ref(false)
const installingDeps = ref(false)
const installNotice = ref('')
const installSource = ref('local')
const installPath = ref('')

const configDraft = ref<Record<string, unknown>>({})
const arrayDraft = ref<Record<string, string[]>>({})
const schemaProps = ref<{ key: string; label: string; type: string; enum?: string[] }[]>([])
const schemaLoading = ref(false)
const configSaving = ref(false)

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
    if (pluginDetail.value === plugin.name) pluginDetail.value = ''
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
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    installingDeps.value = false
  }
}

async function toggleDetail(name: string) {
  if (pluginDetail.value === name) {
    pluginDetail.value = ''
    return
  }
  pluginDetail.value = name
  const plugin = plugins.value.find((p) => p.name === name)
  if (plugin && plugin.config_schema) await loadConfig(plugin)
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
    }))
    configDraft.value = { ...((result.config as Record<string, unknown>) || {}) }
    arrayDraft.value = {}
    for (const [key, spec] of Object.entries(propsMap)) {
      if (String(spec.type || '') === 'array') {
        const raw = configDraft.value[key]
        arrayDraft.value[key] = Array.isArray(raw) ? raw.map(String) : []
      }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    schemaLoading.value = false
  }
}

async function saveConfig(plugin: PluginItem) {
  configSaving.value = true
  error.value = ''
  const payload = { ...configDraft.value }
  for (const [key, list] of Object.entries(arrayDraft.value)) {
    payload[key] = (list || []).filter((item) => item.trim())
  }
  try {
    await props.requestRpc('plugin.config.update', { name: plugin.name, config: payload })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    configSaving.value = false
  }
}

onMounted(fetchPlugins)
</script>

<style scoped>
.install-card {
  padding: 12px 14px;
  margin-bottom: 14px;
}

.install-card h3 {
  margin: 0 0 8px;
  font-size: 14px;
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
  margin-top: 2px !important;
}

.plugin-detail {
  grid-column: 1 / -1;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 4%, transparent);
  display: grid;
  gap: 12px;
}

.detail-block h4 {
  margin: 0 0 6px;
  font-size: 13px;
}

.detail-assets {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.asset-chip {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
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

.field-type {
  font-size: 10px;
  opacity: .6;
}

.array-input {
  font-family: var(--font-mono);
  font-size: 12px;
}

.deps-line {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.system-block {
  margin-top: 22px;
  border-top: 1px solid var(--line);
  padding-top: 4px;
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

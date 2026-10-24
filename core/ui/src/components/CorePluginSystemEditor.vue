<template>
  <article class="setting-card plugin-system-preview">
    <header class="preview-head">
      <div>
        <h3>{{ t("插件") }}</h3>
        <p class="muted">{{ t("清单、启停、安装、更新与卸载都在这里。") }}</p>
      </div>
      <button class="text-btn" type="button" :disabled="loading" @click="fetchPlugins()">
        {{ t("刷新") }}
      </button>
    </header>

    <!-- user:“装、卸、启停、更新全部在本地完成”+三种来源同一条安装流程；
         更新走同一表单，只换按钮（同名替换，data 保留）。 -->
    <form class="preview-install" @submit.prevent="submitInstall(false)">
      <div class="install-row">
        <label><input v-model="installSource" type="radio" value="local" />{{ t("本地目录") }}</label>
        <label><input v-model="installSource" type="radio" value="zip" />{{ t("压缩包") }}</label>
        <label><input v-model="installSource" type="radio" value="url" />{{ t("链接") }}</label>
      </div>
      <div class="install-row">
        <input
          v-model="installTarget"
          class="install-input"
          type="text"
          :placeholder="installSource === 'url' ? 'https://example.com/plugin.zip' : 'C:\path\to\plugin'"
        />
        <input
          v-if="installSource === 'url'"
          v-model="installSha256"
          class="install-sha"
          type="text"
          :placeholder="t('sha256（可选）')"
        />
      </div>
      <div class="install-row">
        <button class="small-btn" type="submit" :disabled="installBusy || !installTarget">
          {{ t("安装") }}
        </button>
        <button
          class="small-btn"
          type="button"
          :disabled="installBusy || !installTarget"
          @click="submitInstall(true)"
        >
          {{ t("更新（同名替换，data 保留）") }}
        </button>
        <span v-if="installBusy" class="muted">{{ t("处理中…") }}</span>
      </div>
    </form>

    <p v-if="error" class="preview-error" role="alert">{{ error }}</p>
    <p v-if="notice" class="preview-notice">{{ notice }}</p>

    <p v-if="loading" class="muted">{{ t("加载中…") }}</p>
    <p v-else-if="!plugins.length" class="muted">
      {{ t("还没有插件。在插件根目录放一个只有 name 和 version 的 plugin.json 就会出现。") }}
    </p>

    <div v-else class="preview-list">
      <div
        v-for="plugin in plugins"
        :key="plugin.name"
        class="preview-row"
        :class="{ 'is-disabled': !plugin.enabled }"
      >
        <div class="preview-identity">
          <strong>{{ plugin.name }}</strong>
          <span class="preview-version">{{ plugin.version }}</span>
          <span class="preview-scope">{{ plugin.scope }}</span>
        </div>
        <p v-if="plugin.description" class="preview-desc">{{ plugin.description }}</p>
        <code class="preview-root">{{ plugin.root }}</code>
        <span class="preview-capabilities" :class="{ 'is-error': plugin.capability_error }">
          {{ capabilitySummary(plugin) }}
        </span>
        <div class="preview-actions">
          <button
            class="small-btn"
            type="button"
            :disabled="busy === plugin.name"
            @click="toggle(plugin)"
          >
            {{ plugin.enabled ? t("禁用") : t("启用") }}
          </button>
          <button
            v-for="window in windowsFor(plugin.name)"
            :key="window.id"
            class="small-btn"
            type="button"
            @click="openWindow(window)"
          >
            {{ t("打开窗口 {0}", { 0: window.title }) }}
          </button>
          <button
            class="small-btn"
            type="button"
            :data-config-for="plugin.name"
            @click="toggleConfig(plugin)"
          >
            {{ configuring === plugin.name ? t("收起配置") : t("配置") }}
          </button>
          <button
            class="small-btn"
            type="button"
            :data-deps-for="plugin.name"
            @click="checkDeps(plugin)"
          >
            {{ t("依赖") }}
          </button>
          <button
            class="text-btn danger"
            type="button"
            :disabled="busy === plugin.name"
            @click="uninstall(plugin)"
          >
            {{ t("卸载") }}
          </button>
        </div>
        <p v-if="depsFor(plugin.name)" class="preview-deps" :class="{ 'is-missing': depsMissing(plugin.name) }">
          {{ depsFor(plugin.name) }}
        </p>
        <PluginConfigPanel
          v-if="configuring === plugin.name"
          :plugin-name="plugin.name"
          :version="plugin.version"
          :description="plugin.description"
          :request-rpc="props.requestRpc"
        />
      </div>
    </div>

    <!-- user:“行为表插件页可查”+按名字查任意行为落在哪个模块/内核。 -->
    <form class="preview-install" @submit.prevent="searchBehavior">
      <div class="install-row">
        <input
          v-model="behaviorQuery"
          class="install-input"
          type="text"
          :placeholder="t('查行为表：模块名或片段（如 prompt、plugin_system.host）')"
        />
        <button class="small-btn" type="submit" :disabled="!behaviorQuery.trim()">
          {{ t("查询") }}
        </button>
        <span v-if="behaviorTotal >= 0" class="muted">
          {{ t("{0} 条匹配", { 0: behaviorTotal }) }}
        </span>
      </div>
      <p v-for="entry in behaviorEntries" :key="entry.module" class="preview-deps">
        {{ entry.module }} — {{ entry.ownership === 'kernel' ? t('内核（不可替换）') : t('可替换模块') }}（{{ entry.layer }}）
      </p>
    </form>

    <details v-if="loadErrors.length" class="preview-errors">
      <summary>{{ t("加载错误 {0}", { 0: loadErrors.length }) }}</summary>
      <p v-for="item in loadErrors" :key="item.path">{{ item.name }}：{{ item.error }}</p>
    </details>

    <PluginSystemContributions :request-rpc="props.requestRpc" region="settings" />
  </article>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { openPluginWindow, type PluginWindowTarget } from '../helpers/pluginWindow'
import { t } from '../i18n/index'
import PluginConfigPanel from './PluginConfigPanel.vue'
import PluginSystemContributions from './PluginSystemContributions.vue'

interface PluginSystemCapabilities {
  tools: string[]
  skills: string[]
  hooks: string[]
  mcp: string[]
  commands: string[]
  context: string[]
}

interface PluginSystemEntry {
  name: string
  version: string
  description: string
  enabled: boolean
  scope: string
  root: string
  capabilities?: PluginSystemCapabilities
  capability_error?: string
}

interface PluginSystemError {
  name: string
  path: string
  error: string
}

interface PluginSystemWindow {
  plugin: string
  id: string
  title: string
  url: string
  width: number
  height: number
}

type PluginSystemRpc = (
  method: string,
  params?: Record<string, unknown>,
) => Promise<Record<string, unknown>>

const props = defineProps<{ requestRpc: PluginSystemRpc }>()

const behaviorQuery = ref('')
const behaviorEntries = ref<Array<{ module: string; ownership: string; layer: string }>>([])
const behaviorTotal = ref(-1)
const installSource = ref<'local' | 'zip' | 'url'>('local')
const installTarget = ref('')
const installSha256 = ref('')
const installBusy = ref(false)
const depsReport = ref<Record<string, string>>({})
const plugins = ref<PluginSystemEntry[]>([])
const windows = ref<PluginSystemWindow[]>([])
const configuring = ref('')
const loadErrors = ref<PluginSystemError[]>([])
const loading = ref(true)
const busy = ref('')
const error = ref('')
const notice = ref('')

const CAPABILITY_LABELS: Array<[keyof PluginSystemCapabilities, string]> = [
  ['tools', '工具'],
  ['skills', '技能'],
  ['hooks', '钩子'],
  ['mcp', 'MCP'],
  ['commands', '命令'],
  ['context', '上下文'],
]

function capabilitySummary(plugin: PluginSystemEntry): string {
  if (plugin.capability_error) {
    return t("声明错误：{0}", { 0: plugin.capability_error })
  }
  const capabilities = plugin.capabilities
  if (!capabilities) return t("没有声明能力")
  const parts = CAPABILITY_LABELS
    .filter(([key]) => (capabilities[key] || []).length > 0)
    .map(([key, label]) => `${label} ${capabilities[key].length}`)
  return parts.length ? parts.join(" · ") : t("没有声明能力")
}

function windowsFor(pluginName: string): PluginSystemWindow[] {
  return windows.value.filter((window) => window.plugin === pluginName)
}

function toggleConfig(plugin: PluginSystemEntry): void {
  configuring.value = configuring.value === plugin.name ? '' : plugin.name
}

async function openWindow(target: PluginSystemWindow): Promise<void> {
  notice.value = ''
  try {
    const opened = await openPluginWindow(target as PluginWindowTarget)
    if (!opened) notice.value = t("当前环境没有桌面窗口，插件窗口只能在桌面端打开。")
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function fetchWindows(): Promise<void> {
  try {
    const payload = await props.requestRpc('plugin.system.ui', {})
    windows.value = Array.isArray(payload.windows)
      ? (payload.windows as PluginSystemWindow[])
      : []
  } catch {
    windows.value = []
  }
}

async function fetchPlugins(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('plugin.system.list', {})
    plugins.value = Array.isArray(result.plugins)
      ? (result.plugins as PluginSystemEntry[])
      : []
    loadErrors.value = Array.isArray(result.errors)
      ? (result.errors as PluginSystemError[])
      : []
    await fetchWindows()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function toggle(plugin: PluginSystemEntry): Promise<void> {
  busy.value = plugin.name
  error.value = ''
  try {
    await props.requestRpc(
      plugin.enabled ? 'plugin.system.disable' : 'plugin.system.enable',
      { name: plugin.name },
    )
    await fetchPlugins()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = ''
  }
}

async function uninstall(plugin: PluginSystemEntry): Promise<void> {
  if (!window.confirm(t("卸载 {0}？data 目录会保留。", { 0: plugin.name }))) return
  busy.value = plugin.name
  error.value = ''
  try {
    await props.requestRpc('plugin.system.uninstall', {
      name: plugin.name,
      keep_data: true,
    })
    notice.value = t("已卸载 {0}，data 目录保留。", { 0: plugin.name })
    await fetchPlugins()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = ''
  }
}

interface InstallResult {
  installed?: boolean
  updated?: boolean
  name?: string
  dependencies?: Array<{ name: string; status: string }>
  missing_dependencies?: number
}

function describeDependencies(result: InstallResult): string {
  const items = result.dependencies || []
  if (!items.length) return ''
  const missing = items.filter((item) => item.status === 'missing').map((item) => item.name)
  const summary = items.map((item) => `${item.name}:${item.status === 'ok' ? '✓' : '缺失'}`).join(' · ')
  return missing.length ? `${summary}（缺 ${missing.join('、')}，可用 pip 安装；不阻止安装）` : summary
}

async function submitInstall(isUpdate: boolean): Promise<void> {
  const source = installSource.value
  const payload: Record<string, unknown> = { source }
  if (source === 'url') {
    payload.url = installTarget.value.trim()
    if (installSha256.value.trim()) payload.sha256 = installSha256.value.trim()
  } else {
    payload.path = installTarget.value.trim()
  }
  installBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = (await props.requestRpc(
      isUpdate ? 'plugin.system.update' : 'plugin.system.install',
      payload,
    )) as unknown as InstallResult
    const verb = isUpdate ? '已更新' : '已安装'
    const deps = describeDependencies(result)
    notice.value = `${verb} ${result.name || ''}${deps ? `；依赖：${deps}` : ''}`
    installTarget.value = ''
    installSha256.value = ''
    await fetchPlugins()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    installBusy.value = false
  }
}

function depsFor(name: string): string {
  return depsReport.value[name] || ''
}

function depsMissing(name: string): boolean {
  return (depsReport.value[name] || '').includes('缺失')
}

async function checkDeps(plugin: PluginSystemEntry): Promise<void> {
  busy.value = plugin.name
  try {
    const result = await props.requestRpc('plugin.deps-status', { name: plugin.name })
    const items = Array.isArray(result.dependencies)
      ? (result.dependencies as Array<{ name: string; status: string }>)
      : []
    depsReport.value[plugin.name] = items.length
      ? items.map((item) => `${item.name}:${item.status === 'ok' ? '✓' : '缺失'}`).join(' · ')
      : t('没有声明依赖')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    busy.value = ''
  }
}

async function searchBehavior(): Promise<void> {
  const query = behaviorQuery.value.trim()
  if (!query) return
  try {
    const result = await props.requestRpc('plugin.system.behavior', { query })
    behaviorEntries.value = Array.isArray(result.entries)
      ? (result.entries as Array<{ module: string; ownership: string; layer: string }>)
      : []
    behaviorTotal.value = Number(result.total_matches || 0)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(fetchPlugins)
</script>

<style scoped>
.plugin-system-preview {
  display: grid;
  gap: 12px;
}

.preview-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.preview-head h3 {
  margin: 0 0 4px;
}

.preview-error {
  color: var(--red);
}

.preview-notice {
  color: var(--green);
}

.preview-list {
  display: grid;
  gap: 8px;
}

.preview-row {
  border: 1px solid color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  border-radius: var(--radius);
  padding: 10px 12px;
  display: grid;
  gap: 6px;
}

.preview-row.is-disabled {
  opacity: 0.6;
}

.preview-identity {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.preview-version {
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 60%, transparent);
}

.preview-scope {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid currentColor;
  opacity: 0.7;
}

.preview-desc {
  margin: 0;
  font-size: 12px;
}

.preview-root {
  font-size: 11px;
  opacity: 0.6;
  word-break: break-all;
}

.preview-capabilities {
  font-size: 12px;
  opacity: 0.8;
}

.preview-capabilities.is-error {
  color: var(--red);
  opacity: 1;
}

.preview-actions {
  display: flex;
  gap: 8px;
}

.preview-errors {
  font-size: 12px;
}

.danger {
  color: var(--red);
}

.preview-install {
  display: grid;
  gap: 6px;
  border: 1px dashed color-mix(in srgb, var(--theme-main-text) 20%, transparent);
  border-radius: var(--radius);
  padding: 8px 10px;
}

.install-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
}

.install-input {
  flex: 1;
  min-width: 220px;
}

.install-sha {
  width: 180px;
}

.preview-deps {
  margin: 0;
  font-size: 12px;
  opacity: 0.8;
}

.preview-deps.is-missing {
  color: var(--red);
  opacity: 1;
}
</style>

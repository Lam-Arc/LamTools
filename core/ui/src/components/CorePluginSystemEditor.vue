<template>
  <article class="setting-card plugin-system-preview">
    <header class="preview-head">
      <div>
        <h3>{{ t("新插件系统（预览）") }}</h3>
        <p class="muted">{{ t("与当前插件页互不影响。这里只验证清单、启停和卸载。") }}</p>
      </div>
      <button class="text-btn" type="button" :disabled="loading" @click="fetchPlugins()">
        {{ t("刷新") }}
      </button>
    </header>

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
            class="text-btn danger"
            type="button"
            :disabled="busy === plugin.name"
            @click="uninstall(plugin)"
          >
            {{ t("卸载") }}
          </button>
        </div>
        <PluginConfigPanel
          v-if="configuring === plugin.name"
          :plugin-name="plugin.name"
          :version="plugin.version"
          :description="plugin.description"
          :request-rpc="props.requestRpc"
        />
      </div>
    </div>

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
</style>

<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>搜索</h1>
      <p>管理 web_search 工具使用的搜索引擎内核。默认内核与参数写入 <code>.lam/core/config/websearch.jsonc</code>，保存后即时生效。</p>
    </header>

    <p v-if="error" class="hook-error">{{ error }}</p>

    <!-- 概览：当前默认内核 -->
    <article class="setting-card agent-toggle">
      <div class="agent-toggle-row">
        <div>
          <h3>默认搜索内核</h3>
          <p>
            内置：<strong>baidu</strong>（国内可达，推荐）· bing（英文/分词正常词可用）· ddg（海外备胎）。
            外部工具（GPL/AGPL 等独立进程）经 subprocess/http 接入，需手动配置 JSONC。
          </p>
        </div>
        <div v-if="!loading" class="kernel-badge">{{ activeProvider }}</div>
      </div>
    </article>

    <!-- 表单编辑器（可视化） -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">内核配置</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading" @click="fetchConfig">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || saving" @click="saveForm">保存</button>
        </div>
      </div>

      <label class="field">
        <span>默认内核 provider</span>
        <UiSelect
          :model-value="form.provider"
          :options="providerOptions"
          :disabled="loading || saving"
          aria-label="默认内核 provider"
          @update:model-value="form.provider = $event"
        />
      </label>

      <label class="field">
        <span>结果上限 limit（默认 5，1-20）</span>
        <input
          v-model.number="form.limit"
          type="number"
          min="1"
          max="20"
          :disabled="loading || saving"
        />
      </label>

      <label class="field">
        <span>超时秒数 timeout</span>
        <input
          v-model.number="form.timeout"
          type="number"
          min="5"
          max="120"
          :disabled="loading || saving"
        />
      </label>

      <p v-if="saved" class="hook-meta" role="status"><Check :size="12" :stroke-width="2.2" aria-hidden="true" /> 已保存</p>
    </article>

    <!-- 原始 JSONC 编辑器 -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">原始配置</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="configSaving" @click="revertConfig">还原</button>
          <button class="small-btn" type="button" :disabled="configSaving" @click="saveRawConfig">
            {{ configSaving ? '保存中…' : '保存' }}
          </button>
        </div>
      </div>
      <textarea
        v-model="configDraft"
        class="hook-config-textarea"
        rows="12"
        spellcheck="false"
        aria-label="websearch.jsonc 内容"
        :disabled="configSaving"
        placeholder="{ &quot;provider&quot;: &quot;baidu&quot;, &quot;limit&quot;: 5, &quot;timeout&quot;: 15 }"
      />
      <p class="hook-meta" :class="{ 'hook-config-error': configError }">
        <Check v-if="configSaved" :size="12" :stroke-width="2.2" aria-hidden="true" />
        {{ configMessage || '支持注释（JSONC），保存后即时生效。' }}
      </p>
    </article>

    <!-- 说明卡片 -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted subhead-title">外部搜索内核（subprocess / http）</span>
      </div>
      <p class="skill-path-explain">
        如需接入独立搜索工具（如 baidu-serp-api、SearXNG、openserp 等），在原始配置中扩展
        <code>transport</code> / <code>command</code> / <code>url</code> 字段，例如：
      </p>
      <pre class="config-sample">{
  "provider": "custom-serp",
  "transport": "http",
  "url": "http://127.0.0.1:8888/search"
}</pre>
      <p class="hook-meta">GPL/AGPL 组件以独立进程运行、仓库不携带代码；LamTools 仅按固定 JSON 契约调用（详见 docs/web-search-module.md）。</p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Check } from 'lucide-vue-next'
import UiSelect from './UiSelect.vue'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const loading = ref(true)
const saving = ref(false)
const saved = ref(false)
const error = ref('')

const form = reactive({
  provider: 'baidu',
  limit: 5,
  timeout: 15,
})

const providerOptions = [
  { value: 'baidu', label: 'baidu（百度，国内可达）' },
  { value: 'bing', label: 'bing（必应中文）' },
  { value: 'ddg', label: 'ddg（DuckDuckGo，海外）' },
]

// raw config editor
const configDraft = ref('')
const configOriginal = ref('')
const configSaving = ref(false)
const configMessage = ref('')
const configSaved = ref(false)
const configError = ref(false)

const activeProvider = ref('baidu')

interface ParsedConfig {
  provider?: string
  limit?: number
  timeout?: number
  [key: string]: unknown
}

function stripJsoncComments(text: string): string {
  // String-literal-aware JSONC comment strip. A regex-based strip corrupts
  // the `//` inside quoted URLs ("https://…") (audit 17 S3).
  let out = ''
  let inString = false
  for (let i = 0; i < text.length; i++) {
    const ch = text[i]
    const next = text[i + 1]
    if (inString) {
      out += ch
      if (ch === '\\' && i + 1 < text.length) {
        out += next
        i += 1
        continue
      }
      if (ch === '"') inString = false
      continue
    }
    if (ch === '"') {
      inString = true
      out += ch
      continue
    }
    if (ch === '/' && next === '/') {
      while (i < text.length && text[i] !== '\n') i += 1
      continue
    }
    if (ch === '/' && next === '*') {
      i += 2
      while (i + 1 < text.length && !(text[i] === '*' && text[i + 1] === '/')) i += 1
      i += 1
      continue
    }
    out += ch
  }
  return out
}

function parseConfig(content: string): ParsedConfig {
  if (!content.trim()) return {}
  try {
    const data = JSON.parse(stripJsoncComments(content))
    return (data && typeof data === 'object' && !Array.isArray(data) ? data : {}) as ParsedConfig
  } catch {
    return {}
  }
}

function syncFormFromContent(content: string) {
  const parsed = parseConfig(content)
  form.provider = typeof parsed.provider === 'string' && parsed.provider ? parsed.provider : 'baidu'
  form.limit = typeof parsed.limit === 'number' ? parsed.limit : 5
  form.timeout = typeof parsed.timeout === 'number' ? parsed.timeout : 15
  activeProvider.value = form.provider
  configOriginal.value = content || JSON.stringify({ provider: 'baidu' }, null, 2)
  configDraft.value = configOriginal.value
}

async function fetchConfig() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('websearch.config.get', {})
    const content = String((result as Record<string, unknown>).content || '')
    syncFormFromContent(content)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function toJsoncContent(): string {
  // Merge onto the original config so custom extension fields (transport,
  // url, command, …) survive a form save instead of being silently wiped
  // (audit 17 S3).
  const data: Record<string, unknown> = { ...parseConfig(configOriginal.value || '') }
  data.provider = form.provider.trim() || 'baidu'
  if (form.limit > 0) data.limit = form.limit
  else delete data.limit
  if (form.timeout > 0) data.timeout = form.timeout
  else delete data.timeout
  return JSON.stringify(data, null, 2)
}

async function saveForm() {
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    await props.requestRpc('websearch.config.update', { content: toJsoncContent() })
    configOriginal.value = toJsoncContent()
    configDraft.value = configOriginal.value
    activeProvider.value = form.provider
    saved.value = true
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

function revertConfig() {
  configDraft.value = configOriginal.value
  configMessage.value = ''
  configSaved.value = false
  configError.value = false
}

async function saveRawConfig() {
  configSaving.value = true
  configMessage.value = ''
  configSaved.value = false
  configError.value = false
  try {
    await props.requestRpc('websearch.config.update', { content: configDraft.value })
    configOriginal.value = configDraft.value
    syncFormFromContent(configDraft.value)
    configSaved.value = true
    configMessage.value = '已保存'
  } catch (e) {
    configError.value = true
    configMessage.value = e instanceof Error ? e.message : String(e)
  } finally {
    configSaving.value = false
  }
}

onMounted(fetchConfig)
</script>

<style scoped>
.hook-error {
  margin: 0;
  padding: 9px 12px;
  border-radius: var(--radius);
  border: 1px solid color-mix(in srgb, var(--red) 22%, transparent);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 64%, var(--settings-main-text, #fff));
  font-size: 13px;
}

.agent-toggle {
  padding: 12px 14px;
}

.agent-toggle-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}

.agent-toggle h3 {
  margin: 0 0 4px;
  font-size: 14px;
}

.agent-toggle p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.kernel-badge {
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: var(--green);
  border: 1px solid color-mix(in srgb, var(--green) 40%, transparent);
  background: color-mix(in srgb, var(--green) 12%, transparent);
}

.field {
  display: grid;
  gap: 5px;
  margin-bottom: 13px;
}

.field > span {
  font-size: 12px;
  font-weight: 600;
}

.field input {
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  font-size: 13px;
}

.field :deep(.ui-select-trigger) {
  width: 100%;
  min-height: 34px;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  font-size: 13px;
}

.hook-meta {
  margin: 0;
  font-size: 12px;
  color: var(--green);
}

.hook-config-error {
  color: var(--red, #e5484d) !important;
}

.hook-config-textarea {
  width: 100%;
  min-height: 140px;
  padding: 10px;
  border-radius: var(--radius-sm);
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  font-family: var(--mono, ui-monospace, 'Cascadia Code', Consolas, monospace);
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
}

.config-sample {
  margin: 6px 0;
  padding: 9px 12px;
  border-radius: var(--radius-sm, 8px);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  font-family: var(--mono, ui-monospace, 'Cascadia Code', Consolas, monospace);
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre;
}

.skill-path-explain {
  margin: 0 0 6px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}
</style>
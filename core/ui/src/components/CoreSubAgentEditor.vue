<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>Sub agent</h1>
      <p>配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。</p>
    </header>

    <p v-if="error" class="skill-error">{{ error }}</p>

    <!-- Default multimodal model picker -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted">默认多模态解析模型</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="settingsLoading || settingsSaving" @click="saveSettings">保存</button>
        </div>
      </div>
      <UiSelect
        :model-value="defaultMmModel"
        class="mm-select"
        :options="mmModelOptions"
        :disabled="settingsLoading"
        aria-label="默认多模态解析模型"
        @update:model-value="defaultMmModel = $event"
      />
      <p class="hook-meta">
        当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明 <strong>多模态</strong> 能力的模型。保存到 <code>{{ settingsTargetPath }}</code>。
      </p>
    </article>

    <!-- Guide editor -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted">{{ loading ? '加载中…' : statusLabel }}</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading" @click="fetchGuide">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || saving" @click="saveGuide">保存</button>
        </div>
      </div>

      <textarea
        v-model="draft"
        class="guide-editor"
        rows="18"
        spellcheck="false"
        :disabled="loading || saving"
        placeholder="# Sub-agent 委派指南&#10;在此编写自然语言指令，将注入到主 Agent 系统提示词中…"
      />
      <p class="hook-meta">
        {{ guideDescription }}
      </p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiSelect from './UiSelect.vue'
import type { CoreSettingsModel } from './CoreSettings.vue'

const props = withDefaults(defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  models?: CoreSettingsModel[]
  /** Config scope this editor reads/writes. 'global' (default) edits ~/.lam/core/config;
   *  'project' edits {workRoot}/.lam/config and falls back to global/builtin on read. */
  scope?: 'global' | 'project'
  /** Required when scope === 'project'. */
  workRoot?: string
}>(), {
  scope: 'global',
  workRoot: '',
})

// ── Guide state ──
const draft = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const isBuiltin = ref(true)

/** Merge scope + work_root into an RPC params object so the backend reads/writes
 *  the correct tier (global → ~/.lam/core/config, project → {workRoot}/.lam/config). */
function withScope<T extends Record<string, unknown>>(extra: T): T {
  return { scope: props.scope, ...(props.workRoot ? { work_root: props.workRoot } : {}), ...extra } as T
}

const statusLabel = computed(() => {
  if (saving.value) return '保存中…'
  if (props.scope === 'project') {
    return isBuiltin.value
      ? '当前来源：继承全局 / 内置默认（未配置项目级 guide）'
      : '当前来源：项目配置'
  }
  return isBuiltin.value ? '当前来源：内置默认（未配置全局 guide）' : '当前来源：全局配置'
})

const settingsTargetPath = computed(() =>
  props.scope === 'project'
    ? `${props.workRoot || '(项目根)'}/.lam/config/subagent/settings.json`
    : '~/.lam/core/config/subagent/settings.json',
)

const guideDescription = computed(() => {
  if (props.scope === 'project') {
    return `保存到项目配置 ${props.workRoot || '(项目根)'}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>`
  }
  return '保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global'
})

async function fetchGuide() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.subagent.guide.get', withScope({}))
    draft.value = String(result.content ?? '')
    isBuiltin.value = result.is_builtin !== false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function saveGuide() {
  saving.value = true
  error.value = ''
  try {
    await props.requestRpc('config.subagent.guide.set', withScope({
      content: draft.value,
    }))
    await fetchGuide()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

// ── Default multimodal model state ──
const defaultMmModel = ref('')
const settingsLoading = ref(true)
const settingsSaving = ref(false)

const multimodalModels = computed(() =>
  (props.models ?? []).filter(m => m.capability === 'multimodal')
)

const mmModelOptions = computed(() => [
  { value: '', label: `未配置（使用内置兜底：${fallbackLabel.value}）` },
  ...multimodalModels.value.map(m => ({
    value: m.display_name || m.model_id || m.id,
    label: m.display_name || m.model_id || m.id,
  })),
])

/** Built-in fallback when no default_multimodal_model is configured: the first
 *  multimodal model by model_id — same ordering as the backend ModelStore. */
const fallbackMultimodalModel = computed(() =>
  [...(props.models ?? [])]
    .filter(m => m.capability === 'multimodal')
    .sort((a, b) => String(a.model_id || a.id || '').localeCompare(String(b.model_id || b.id || '')))[0] ?? null,
)

const fallbackLabel = computed(() => {
  const m = fallbackMultimodalModel.value
  if (!m) return '无多模态模型'
  return m.display_name || m.model_id || m.id
})

async function fetchSettings() {
  settingsLoading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.subagent.settings.get', withScope({}))
    const settings = result.settings as Record<string, unknown> | undefined
    defaultMmModel.value = String(settings?.default_multimodal_model ?? '')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    settingsLoading.value = false
  }
}

async function saveSettings() {
  settingsSaving.value = true
  error.value = ''
  try {
    await props.requestRpc('config.subagent.settings.set', withScope({
      settings: { default_multimodal_model: defaultMmModel.value },
    }))
    await fetchSettings()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    settingsSaving.value = false
  }
}

onMounted(() => {
  fetchGuide()
  fetchSettings()
})
</script>

<style scoped>
.guide-editor {
  width: 100%;
  min-height: 320px;
  margin-top: 10px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  padding: 9px;
  font-family: var(--font-mono);
  font-size: 13px;
  resize: vertical;
}

.mm-select {
  width: 100%;
  max-width: 400px;
  margin-top: 8px;
}

.mm-select :deep(.ui-select-trigger) {
  min-height: 34px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  font-size: 13px;
}

.subhead-actions {
  display: flex;
  gap: 6px;
}

.hook-meta {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}
</style>

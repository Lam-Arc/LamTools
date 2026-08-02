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
      <select
        v-model="defaultMmModel"
        class="mm-select"
        :disabled="settingsLoading"
      >
        <option value="">未配置（使用内置兜底：Kimi-K2.6 等）</option>
        <option
          v-for="m in multimodalModels"
          :key="m.id"
          :value="m.display_name || m.model_id || m.id"
        >{{ m.display_name || m.model_id || m.id }}</option>
      </select>
      <p class="hook-meta">
        当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明 <strong>多模态</strong> 能力的模型。保存到 <code>~/.lam/config/subagent/settings.json</code>。
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
        保存到全局配置 <code>~/.lam/config/subagent/guide.md</code>。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：<code>core subagent guide show/set/edit --scope global</code>
      </p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CoreSettingsModel } from './CoreSettings.vue'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  models?: CoreSettingsModel[]
}>()

// ── Guide state ──
const draft = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const isBuiltin = ref(true)

const statusLabel = computed(() => {
  if (saving.value) return '保存中…'
  return isBuiltin.value ? '当前来源：内置默认（未配置全局 guide）' : '当前来源：全局配置'
})

async function fetchGuide() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.subagent.guide.get', { scope: 'global' })
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
    await props.requestRpc('config.subagent.guide.set', {
      scope: 'global',
      content: draft.value,
    })
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

async function fetchSettings() {
  settingsLoading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.subagent.settings.get', { scope: 'global' })
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
    await props.requestRpc('config.subagent.settings.set', {
      scope: 'global',
      settings: { default_multimodal_model: defaultMmModel.value },
    })
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
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: inherit;
  padding: 9px;
  font-family: var(--font-mono);
  font-size: 13px;
  resize: vertical;
}

.mm-select {
  width: 100%;
  max-width: 400px;
  margin-top: 8px;
  padding: 6px 8px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: inherit;
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

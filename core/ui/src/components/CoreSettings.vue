<template>
  <Teleport to="body">
    <div
      class="settings-overlay"
      @click.self="$emit('close')"
    >
      <div class="settings-card">
        <SettingsShell
          :sections="sections"
          title="Core 设置"
          :settings-theme-style="settingsThemeStyle"
          @close="$emit('close')"
        >
          <template #default="{ activeSection }">
      <section v-if="activeSection === 'models'" class="settings-panel">
        <header class="settings-title">
          <h1>模型与供应商</h1>
          <p>共享 Core 配置。更改会在所有接入 Core 的界面中生效。</p>
        </header>

        <div v-if="noticeText" class="settings-notice">{{ noticeText }}</div>

        <section v-if="providerEditor" class="settings-editor" aria-label="供应商配置">
          <div class="subhead">
            <h3>{{ providerEditor.mode === 'create' ? '新增供应商' : '编辑供应商' }}</h3>
          </div>
          <form :data-provider-form="providerEditor.mode" class="config-form" @submit.prevent="submitProvider">
            <label v-if="providerEditor.mode === 'create'" class="field">官方模板
              <select v-model="providerEditor.preset_id" @change="applyProviderPreset">
                <option value="">自定义</option>
                <option v-for="preset in providerPresets" :key="preset.id" :value="preset.id">{{ preset.label }}</option>
              </select>
            </label>
            <div v-if="providerEditor.preset_id" class="preset-summary field-wide">
              <strong>{{ providerEditor.name }}</strong>
              <span>{{ providerEditor.base_url }} · 将自动添加模板内模型</span>
            </div>
            <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id" class="field">名称
              <input v-model.trim="providerEditor.name" data-provider-name required />
            </label>
            <label v-if="providerEditor.mode === 'update' || !providerEditor.preset_id" class="field">服务地址
              <input v-model.trim="providerEditor.base_url" data-provider-base-url type="url" required />
            </label>
            <label class="field">API Key
              <input
                v-model="providerEditor.api_key"
                data-provider-api-key
                type="password"
                autocomplete="new-password"
                :required="providerEditor.mode === 'create'"
                :placeholder="providerEditor.mode === 'update' ? '留空以保留现有密钥' : ''"
              />
            </label>
            <details class="settings-advanced field-wide">
              <summary>高级设置</summary>
              <div class="advanced-fields">
                <label class="field">接口类型
                  <select v-model="providerEditor.api_type" data-provider-api-type>
                    <option value="openai">OpenAI compatible</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </label>
                <label class="field field-wide">高级适配 JSON
                  <textarea v-model="providerEditor.extra_json" rows="5" spellcheck="false" placeholder="{}"></textarea>
                </label>
              </div>
            </details>
            <div class="editor-actions field-wide">
              <button type="button" class="small-btn quiet" @click="providerEditor = null">取消</button>
              <button class="small-btn primary" type="submit">{{ providerEditor.mode === 'create' ? '添加供应商' : '保存供应商' }}</button>
            </div>
          </form>
        </section>

        <section v-if="modelEditor" class="settings-editor" aria-label="模型配置">
          <div class="subhead">
            <h3>{{ modelEditor.mode === 'create' ? '新增模型' : '编辑模型' }}</h3>
          </div>
          <form :data-model-form="modelEditor.mode" class="config-form" @submit.prevent="submitModel">
            <label class="field">供应商
              <select v-model="modelEditor.provider_id" data-model-provider-id required>
                <option v-for="provider in providers" :key="provider.id" :value="provider.id">{{ provider.name || provider.id }}</option>
              </select>
            </label>
            <label class="field">模型标识
              <input v-model.trim="modelEditor.model_id" data-model-id required />
            </label>
            <label class="field">显示名称
              <input v-model.trim="modelEditor.display_name" data-model-display-name placeholder="选填" />
            </label>
            <details class="settings-advanced field-wide">
              <summary>高级参数</summary>
              <div class="advanced-fields model-advanced-fields">
                <label class="field">上下文窗口
                  <input v-model.number="modelEditor.context_window" type="number" min="1" />
                </label>
                <label class="field">最大输出
                  <input v-model.number="modelEditor.max_output_tokens" type="number" min="1" />
                </label>
                <label class="field">推理预算
                  <input v-model.number="modelEditor.thinking_budget" type="number" min="0" />
                </label>
                <label class="field">Temperature
                  <input v-model.number="modelEditor.temperature" type="number" min="0" max="2" step="0.1" />
                </label>
                <label class="field checkbox-field">
                  <input v-model="modelEditor.thinking_supported" type="checkbox" /> 支持推理
                </label>
                <label class="field field-wide">高级适配 JSON
                  <textarea v-model="modelEditor.extra_json" rows="5" spellcheck="false" placeholder="{}"></textarea>
                </label>
              </div>
            </details>
            <div class="editor-actions field-wide">
              <button type="button" class="small-btn quiet" @click="modelEditor = null">取消</button>
              <button class="small-btn primary" type="submit">{{ modelEditor.mode === 'create' ? '添加模型' : '保存模型' }}</button>
            </div>
          </form>
        </section>

        <div class="provider-actions">
          <button class="small-btn primary" type="button" data-provider-create @click="startProviderCreate">新增供应商</button>
          <button class="small-btn quiet" type="button" data-model-create @click="startModelCreate">新增模型</button>
          <button v-if="allowEnvironmentImport" class="small-btn quiet" type="button" @click="$emit('import-environment')">从当前环境导入</button>
        </div>

        <div v-if="providers.length" class="provider-list">
          <section v-for="provider in providers" :key="provider.id" class="provider-group">
            <header class="provider-head">
              <div class="provider-identity">
                <strong>{{ provider.name || provider.id }}</strong>
                <span>{{ provider.has_api_key ? '已配置密钥' : '未配置密钥' }} · {{ provider.base_url || provider.id }}</span>
              </div>
              <div class="row-actions">
                <button class="text-btn" type="button" :data-provider-edit="provider.id" @click="startProviderUpdate(provider)">编辑</button>
                <button class="text-btn danger" type="button" :data-provider-delete="provider.id" @click="$emit('delete-provider', provider.id)">删除</button>
              </div>
            </header>
            <div class="model-list">
                <div v-for="model in modelsForProvider(provider.id)" :key="model.id" class="model-row">
                  <div class="model-identity">
                    <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                    <span>{{ model.model_id || model.id }}{{ model.thinking_supported ? ' · 支持推理' : '' }}</span>
                  </div>
                  <div class="row-actions">
                    <button class="text-btn" :class="{ active: model.is_default }" type="button" :data-model-default="model.id" @click="$emit('set-default-model', model.id)">{{ model.is_default ? '★ 默认' : '☆ 默认' }}</button>
                    <button class="text-btn" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">编辑</button>
                    <button class="text-btn danger" type="button" :data-model-delete="model.id" @click="$emit('delete-model', model.id)">删除</button>
                  </div>
                </div>
                <p v-if="!modelsForProvider(provider.id).length" class="model-empty">暂无模型</p>
            </div>
          </section>
        </div>
        <div v-else class="setting-card">
          <h3>暂无配置</h3>
          <p>Core 配置接口尚未返回可用的供应商或模型。</p>
        </div>
      </section>

      <section v-else-if="activeSection === 'appearance'" class="settings-panel">
        <header class="settings-title">
          <h1>界面</h1>
          <p>主题和密度只影响当前 Core 界面。</p>
        </header>

        <div class="setting-card">
          <h3>界面密度</h3>
          <div class="density-options" role="group" aria-label="界面密度">
            <button
              v-for="option in densityOptions"
              :key="option.value"
              type="button"
              :data-density="option.value"
              :class="{ active: density === option.value }"
              @click="$emit('update:density', option.value)"
            >{{ option.label }}</button>
          </div>
          <label v-if="contentWidth" class="field">内容宽度
            <input
              :value="contentWidth"
              type="range"
              min="560"
              max="1120"
              step="20"
              @input="$emit('update:content-width', Number(($event.target as HTMLInputElement).value))"
            />
          </label>
        </div>

        <ThemeEditor
          product-name="LamTools Core"
          content-description="Core 工作区"
          :get-stops="getStops"
          :get-angle="getAngle"
          :get-opacity="getOpacity"
          :get-text-color="getTextColor"
          :presets="presets"
          :presets-by-group="presetsByGroup"
          :theme-preview-style="themePreviewStyle"
          :theme-preview-main-style="themePreviewMainStyle"
          :theme-preview-composer-style="themePreviewComposerStyle"
          :theme-preview-control-style="themePreviewControlStyle"
          @reset-theme="$emit('reset-theme')"
          @apply-preset="(preset) => $emit('apply-preset', preset)"
          @update-stops="(area, stops) => $emit('update-stops', area, stops)"
          @update-angle="(area, angle) => $emit('update-angle', area, angle)"
          @update-opacity="(area, opacity) => $emit('update-opacity', area, opacity)"
          @update-text-color="(area, color) => $emit('update-text-color', area, color)"
          @add-stop="(area) => $emit('add-stop', area)"
          @remove-stop="(area, index) => $emit('remove-stop', area, index)"
          @sort-stops="(area) => $emit('sort-stops', area)"
        />
      </section>

      <section v-else-if="activeSection === 'skills'" class="settings-panel">
        <CoreSkillsEditor :request-rpc="requestRpc || defaultRequestRpc" />
      </section>

      <section v-else-if="activeSection === 'hooks'" class="settings-panel">
        <CoreHooksEditor :request-rpc="requestRpc || defaultRequestRpc" />
      </section>

      <section v-else class="settings-panel">
        <header class="settings-title">
          <h1>权限策略</h1>
        </header>
        <article class="setting-card">
          <h3>放行模式</h3>
          <div class="permission-list">
            <div v-for="tier in permissionTiers" :key="tier.id" class="permission-row">
              <div class="permission-row-top" :class="{ active: permissionMode === tier.id }" @click="$emit('update-permission-mode', tier.id)" role="button" tabindex="0" :aria-pressed="permissionMode === tier.id ? 'true' : 'false'" :aria-label="'选择' + tier.label" @keydown.enter.prevent="$emit('update-permission-mode', tier.id)" @keydown.space.prevent="$emit('update-permission-mode', tier.id)">
                <button type="button" class="permission-row-header" @click.stop="expandedTier = expandedTier === tier.id ? null : tier.id">
                  {{ tier.label }}
                </button>
                <span class="permission-radio" :class="{ active: permissionMode === tier.id }" aria-hidden="true">
                  <span class="permission-radio-dot" />
                </span>
              </div>
              <div v-if="expandedTier === tier.id" class="permission-tools">
                <template v-if="tier.id === 'full_edit'">
                  <p class="permission-tools-full">完全放行</p>
                </template>
                <template v-else>
                  <div v-for="tool in tier.tools" :key="tool" class="permission-tool-row">{{ tool }}</div>
                </template>
              </div>
            </div>
          </div>
        </article>
      </section>
    </template>
  </SettingsShell>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { PROVIDER_PRESETS } from '../data/provider-presets'
import { THEME_PRESETS } from '../data/theme-presets'
import {
  gradientFromStops,
  relativeLuminance,
  type ThemeArea,
  type ThemeData,
  type ThemePreset,
  type ThemeStop,
} from '../helpers/theme'
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import ThemeEditor from './ThemeEditor.vue'
import CoreSkillsEditor from './CoreSkillsEditor.vue'
import CoreHooksEditor from './CoreHooksEditor.vue'

export type CoreSettingsDensity = 'compact' | 'standard' | 'loose'

export interface CoreSettingsModel {
  id: string
  provider_id?: string
  model_id?: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  temperature?: number
  is_default?: boolean
  extra?: Record<string, unknown> | null
}

export interface CoreSettingsProvider {
  id: string
  name?: string
  api_type?: string
  base_url?: string
  has_api_key?: boolean
  extra?: Record<string, unknown> | null
}

export interface CoreSettingsProviderPayload {
  provider_id?: string
  preset_id?: string
  name: string
  api_type: string
  base_url: string
  api_key?: string
  extra?: Record<string, unknown>
  models?: CoreSettingsModelPayload[]
}

export interface CoreSettingsModelPayload {
  model_record_id?: string
  provider_id: string
  model_id: string
  display_name: string
  context_window: number
  max_output_tokens: number
  thinking_supported: boolean
  thinking_budget: number
  temperature: number
  extra?: Record<string, unknown>
}

const props = defineProps<{
  models: CoreSettingsModel[]
  providers: CoreSettingsProvider[]
  density: CoreSettingsDensity
  theme: ThemeData
  contentWidth?: number
  allowEnvironmentImport?: boolean
  permissionMode?: 'read_only' | 'limited_edit' | 'full_edit'
  requestRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const emit = defineEmits<{
  close: []
  'update:density': [density: CoreSettingsDensity]
  'update:content-width': [width: number]
  'import-environment': []
  'update-permission-mode': [mode: 'read_only' | 'limited_edit' | 'full_edit']
  'reset-theme': []
  'apply-preset': [preset: ThemePreset]
  'update-stops': [area: ThemeArea, stops: ThemeStop[]]
  'update-angle': [area: ThemeArea, angle: number]
  'update-opacity': [area: ThemeArea, opacity: number]
  'update-text-color': [area: ThemeArea, color: string]
  'add-stop': [area: ThemeArea]
  'remove-stop': [area: ThemeArea, index: number]
  'sort-stops': [area: ThemeArea]
  'create-provider': [payload: CoreSettingsProviderPayload]
  'update-provider': [payload: CoreSettingsProviderPayload]
  'delete-provider': [providerId: string]
  'create-model': [payload: CoreSettingsModelPayload]
  'update-model': [payload: CoreSettingsModelPayload]
  'delete-model': [modelRecordId: string]
  'set-default-model': [modelId: string]
}>()

const sections: SettingsSection[] = [
  { id: 'models', label: '模型与供应商', icon: '◈' },
  { id: 'appearance', label: '界面', icon: '◐' },
  { id: 'skills', label: 'Skills', icon: '✦' },
  { id: 'hooks', label: 'Hooks', icon: '⌘' },
  { id: 'permissions', label: '权限', icon: '◇' },
]

const densityOptions: Array<{ value: CoreSettingsDensity; label: string }> = [
  { value: 'compact', label: '紧凑' },
  { value: 'standard', label: '标准' },
  { value: 'loose', label: '宽松' },
]

type ProviderEditor = Required<Omit<CoreSettingsProviderPayload, 'provider_id'>> & {
  mode: 'create' | 'update'
  provider_id?: string
  api_key: string
  extra_json: string
}

type ModelEditor = CoreSettingsModelPayload & { mode: 'create' | 'update'; extra_json: string }

const providerEditor = ref<ProviderEditor | null>(null)
const modelEditor = ref<ModelEditor | null>(null)
const noticeText = ref('')
const expandedTier = ref<string | null>(null)
const defaultRequestRpc = async (_method: string, _params?: Record<string, unknown>) => {
  throw new Error('requestRpc not provided — connect CoreSettings to a CoreAppServerClient')
}

const permissionMode = computed(() => props.permissionMode || 'full_edit')
const permissionTiers = [
  {
    id: 'read_only' as const, label: '只读调查',
    tools: ['read_file', 'list_dir', 'search_files', 'search_content', 'web_search', 'web_fetch', 'git_status', 'git_diff', 'load_skill', 'browser_check', 'sub_agent'],
  },
  {
    id: 'limited_edit' as const, label: '有限编辑',
    tools: ['read_file', 'list_dir', 'search_files', 'search_content', 'web_search', 'web_fetch', 'git_status', 'git_diff', 'load_skill', 'browser_check', 'sub_agent', 'write_file', 'edit_file', 'write_spreadsheet', 'document_normalize', 'run_tests'],
  },
  {
    id: 'full_edit' as const, label: '完全编辑',
    tools: [] as string[],
  },
]
const providerPresets = PROVIDER_PRESETS

const settingsThemeStyle = computed(() => {
  const lightMain = relativeLuminance(props.theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': gradientFromStops(
      props.theme.backdropAngle,
      props.theme.backdropStops,
      1,
    ),
    '--settings-backdrop-text': props.theme.backdropText,
    '--settings-main-background': gradientFromStops(
      props.theme.mainAngle,
      props.theme.mainStops,
      props.theme.mainOpacity,
    ),
    '--settings-main-text': props.theme.mainText,
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-text) 4%, transparent)',
    '--settings-card-text': props.theme.mainText,
    '--settings-control-background': gradientFromStops(
      props.theme.controlAngle,
      props.theme.controlStops,
      props.theme.controlOpacity,
    ),
    '--settings-control-text': props.theme.controlText,
    '--settings-panel-2': lightMain ? '#f0efeb' : '#1d1e1e',
    '--settings-line': lightMain ? '#d4d0cc' : '#3b3a38',
    '--settings-muted': lightMain ? '#8a8580' : '#a7a29b',
  }
})

const themePreviewStyle = computed(() => ({
  background: gradientFromStops(props.theme.backdropAngle, props.theme.backdropStops, 1),
  color: props.theme.backdropText,
}))
const themePreviewMainStyle = computed(() => ({
  background: gradientFromStops(props.theme.mainAngle, props.theme.mainStops, props.theme.mainOpacity),
  color: props.theme.mainText,
}))
const themePreviewComposerStyle = computed(() => ({
  background: gradientFromStops(props.theme.composerAngle, props.theme.composerStops, props.theme.composerOpacity),
  color: props.theme.composerText,
}))
const themePreviewControlStyle = computed(() => ({
  background: gradientFromStops(props.theme.controlAngle, props.theme.controlStops, props.theme.controlOpacity),
  color: props.theme.controlText,
}))

function modelsForProvider(providerId: string): CoreSettingsModel[] {
  return props.models.filter((model) => model.provider_id === providerId)
}

function startProviderCreate() {
  providerEditor.value = {
    mode: 'create',
    preset_id: '',
    name: '',
    api_type: 'openai',
    base_url: '',
    api_key: '',
    extra: {},
    extra_json: '{}',
    models: [],
  }
}

function startProviderUpdate(provider: CoreSettingsProvider) {
  providerEditor.value = {
    mode: 'update',
    preset_id: '',
    provider_id: provider.id,
    name: provider.name || '',
    api_type: provider.api_type || 'openai',
    base_url: provider.base_url || '',
    api_key: '',
    extra: provider.extra || {},
    extra_json: JSON.stringify(provider.extra || {}, null, 2),
    models: [],
  }
}

function submitProvider() {
  const editor = providerEditor.value
  if (!editor) return
  const extra = parseExtraJson(editor.extra_json)
  if (!extra) return
  const payload: CoreSettingsProviderPayload = {
    ...(editor.provider_id ? { provider_id: editor.provider_id } : {}),
    ...(editor.preset_id ? { preset_id: editor.preset_id } : {}),
    name: editor.name,
    api_type: editor.api_type,
    base_url: editor.base_url,
    ...(editor.api_key.trim() ? { api_key: editor.api_key.trim() } : {}),
    extra,
  }
  if (editor.mode === 'create' && editor.preset_id) {
    const preset = providerPresets.find(candidate => candidate.id === editor.preset_id)
    if (preset) {
      payload.models = preset.models.map(model => ({
        provider_id: '',
        model_id: model.modelId,
        display_name: model.displayName,
        context_window: model.contextWindow,
        max_output_tokens: model.maxOutputTokens,
        thinking_supported: model.thinkingSupported,
        thinking_budget: model.thinkingBudget,
        temperature: model.temperature,
        extra: model.extra,
      }))
    }
  }
  if (editor.mode === 'create') emit('create-provider', payload)
  else emit('update-provider', payload)
  providerEditor.value = null
}

function applyProviderPreset() {
  const editor = providerEditor.value
  if (!editor) return
  const preset = providerPresets.find(candidate => candidate.id === editor.preset_id)
  if (!preset) return
  editor.name = preset.name
  editor.api_type = preset.apiType
  editor.base_url = preset.baseUrl
  editor.extra = { ...(preset.extra || {}), adapter_profile_id: preset.adapterProfile }
  editor.extra_json = JSON.stringify(editor.extra, null, 2)
}

function startModelCreate() {
  modelEditor.value = {
    mode: 'create',
    provider_id: props.providers[0]?.id || '',
    model_id: '',
    display_name: '',
    context_window: 128000,
    max_output_tokens: 16384,
    thinking_supported: false,
    thinking_budget: 10000,
    temperature: 0.7,
    extra: {},
    extra_json: '{}',
  }
}

function startModelUpdate(model: CoreSettingsModel) {
  modelEditor.value = {
    mode: 'update',
    model_record_id: model.id,
    provider_id: model.provider_id || '',
    model_id: model.model_id || '',
    display_name: model.display_name || '',
    context_window: model.context_window || 128000,
    max_output_tokens: model.max_output_tokens || 16384,
    thinking_supported: model.thinking_supported === true,
    thinking_budget: model.thinking_budget || 10000,
    temperature: model.temperature ?? 0.7,
    extra: model.extra || {},
    extra_json: JSON.stringify(model.extra || {}, null, 2),
  }
}

function submitModel() {
  const editor = modelEditor.value
  if (!editor) return
  const extra = parseExtraJson(editor.extra_json)
  if (!extra) return
  const { mode: _mode, extra_json: _extraJson, ...rest } = editor
  const payload = { ...rest, extra }
  if (editor.mode === 'create') emit('create-model', payload)
  else emit('update-model', payload)
  modelEditor.value = null
}

function parseExtraJson(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value || '{}')
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error()
    noticeText.value = ''
    return parsed as Record<string, unknown>
  } catch {
    noticeText.value = '高级适配 JSON 必须是对象'
    return null
  }
}

function getStops(area: ThemeArea): ThemeStop[] {
  return props.theme[`${area}Stops` as keyof ThemeData] as ThemeStop[]
}

function getAngle(area: ThemeArea): number {
  return props.theme[`${area}Angle` as keyof ThemeData] as number
}

function getOpacity(area: ThemeArea): number {
  return area === 'backdrop' ? 1 : props.theme[`${area}Opacity` as keyof ThemeData] as number
}

function getTextColor(area: ThemeArea): string {
  return props.theme[`${area}Text` as keyof ThemeData] as string
}

function presetsByGroup(group: ThemePreset['group']): ThemePreset[] {
  return THEME_PRESETS.filter((preset) => preset.group === group)
}

const presets = THEME_PRESETS

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    emit('close')
  }
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
/* ── Overlay — full-viewport backdrop with centered card ── */
.settings-overlay {
  position: fixed;
  inset: var(--titlebar-offset, 36px) 0 0 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.settings-card {
  position: relative;
  width: min(960px, calc(100vw - 48px));
  max-height: calc(100dvh - var(--titlebar-offset, 36px) - 48px);
  border: 1px solid color-mix(in srgb, var(--theme-main-text, #f2efeb) 12%, transparent);
  border-radius: 16px;
  background: var(--bg, #111111);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.35);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Responsive: full-screen on narrow viewports ── */
@media (max-width: 640px) {
  .settings-card {
    width: 100vw;
    max-height: calc(100dvh - var(--titlebar-offset, 36px));
    border-radius: 0;
  }
}

/* ── Existing settings editor styles ── */
.settings-editor {
  padding: 18px 0;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
}

.settings-editor h3 {
  margin: 0;
  font-size: 15px;
}

.preset-summary {
  min-width: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
}

.preset-summary strong,
.preset-summary span {
  display: block;
}

.preset-summary strong { font-size: 13px; }
.preset-summary span { margin-top: 3px; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.settings-advanced {
  margin-top: 2px;
  padding-top: 10px;
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 9%, transparent);
}

.settings-advanced summary {
  width: max-content;
  cursor: pointer;
  color: var(--muted);
  font-size: 13px;
}

.settings-advanced[open] summary { margin-bottom: 12px; color: inherit; }

.advanced-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.model-advanced-fields { grid-template-columns: repeat(3, minmax(0, 1fr)); }

.editor-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.small-btn.primary {
  background: var(--settings-control-background, #343331);
  color: var(--settings-control-text, var(--text));
}

.small-btn.quiet { background: transparent; }

.density-options {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 12%, transparent);
  border-radius: 8px;
}

.density-options button {
  min-width: 64px;
  min-height: 32px;
  border-radius: 5px;
  background: transparent;
  color: var(--settings-card-text, var(--text));
  font-size: 13px;
}

.density-options button.active {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 14%, transparent);
}

.config-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  align-items: end;
}

.config-form .field {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.config-form input,
.config-form select,
.config-form textarea {
  min-width: 0;
  min-height: 36px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: inherit;
  padding: 0 9px;
}

.config-form textarea {
  min-height: 104px;
  padding: 9px;
  resize: vertical;
}

.config-form .field-wide {
  grid-column: 1 / -1;
}

.permission-list {
  display: grid;
  gap: 12px;
}

.permission-row {
  display: flex;
  flex-direction: column;
  padding: 8px 0;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 50%, transparent);
}

.permission-row:last-child {
  border-bottom: none;
}

.permission-row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  border-radius: 8px;
  padding: 8px 10px;
  margin: -4px -10px;
  transition: background 0.12s ease;
}

.permission-row-top:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
}

.permission-row-top.active {
  background: color-mix(in srgb, var(--green) 10%, transparent);
}

.permission-row-header {
  border: 0;
  padding: 0;
  background: transparent;
  color: var(--text);
  font: inherit;
  font-size: 14px;
  font-weight: 650;
  text-align: left;
  cursor: inherit;
}

.permission-row-top:hover .permission-row-header {
  color: color-mix(in srgb, var(--blue) 70%, var(--text));
}

.permission-radio {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  background: transparent;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  cursor: default;
}

.permission-radio .permission-radio-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: transparent;
}

.permission-radio.active {
  border-color: var(--green, #4caf50);
}

.permission-radio.active .permission-radio-dot {
  background: var(--green, #4caf50);
}

.permission-radio:hover {
  border-color: color-mix(in srgb, var(--theme-main-text) 70%, transparent);
}

.permission-tools {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 4px 16px;
  padding: 8px 0 4px 0;
}

.permission-tool-row {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--muted);
  line-height: 1.6;
}

.permission-tools-full {
  margin: 0;
  font-size: 13px;
  color: var(--muted);
}

@media (max-width: 720px) {
  .config-form {
    grid-template-columns: 1fr;
  }

  .advanced-fields,
  .model-advanced-fields {
    grid-template-columns: 1fr;
  }

  .permission-tools {
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  }
}

.config-form .checkbox-field {
  display: flex;
  align-items: center;
  min-height: 36px;
}

.config-form .checkbox-field input {
  min-width: auto;
  min-height: auto;
}
</style>

<template>
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

        <article v-if="providerEditor" class="setting-card">
          <div class="subhead">
            <h3>{{ providerEditor.mode === 'create' ? '新增供应商' : '编辑供应商' }}</h3>
            <button type="button" class="small-btn" @click="providerEditor = null">取消</button>
          </div>
          <form :data-provider-form="providerEditor.mode" class="config-form" @submit.prevent="submitProvider">
            <label class="field">名称
              <input v-model.trim="providerEditor.name" data-provider-name required />
            </label>
            <label class="field">接口类型
              <select v-model="providerEditor.api_type" data-provider-api-type>
                <option value="openai">OpenAI compatible</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </label>
            <label class="field">服务地址
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
            <button class="small-btn" type="submit">{{ providerEditor.mode === 'create' ? '添加供应商' : '保存供应商' }}</button>
          </form>
        </article>

        <article v-if="modelEditor" class="setting-card">
          <div class="subhead">
            <h3>{{ modelEditor.mode === 'create' ? '新增模型' : '编辑模型' }}</h3>
            <button type="button" class="small-btn" @click="modelEditor = null">取消</button>
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
              <input v-model.trim="modelEditor.display_name" data-model-display-name />
            </label>
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
            <button class="small-btn" type="submit">{{ modelEditor.mode === 'create' ? '添加模型' : '保存模型' }}</button>
          </form>
        </article>

        <div class="provider-actions">
          <button class="small-btn" type="button" data-provider-create @click="startProviderCreate">新增供应商</button>
          <button class="small-btn" type="button" data-model-create @click="startModelCreate">新增模型</button>
        </div>

        <div v-if="providers.length" class="settings-panel">
          <article v-for="provider in providers" :key="provider.id" class="provider-card">
            <header class="provider-head">
              <div>
                <strong>{{ provider.name || provider.id }}</strong>
                <span>{{ provider.has_api_key ? '已配置密钥' : '未配置密钥' }}</span>
              </div>
              <div class="provider-actions">
                <button class="small-btn" type="button" :data-provider-edit="provider.id" @click="startProviderUpdate(provider)">编辑</button>
                <button class="small-btn" type="button" :data-provider-delete="provider.id" @click="$emit('delete-provider', provider.id)">删除</button>
              </div>
            </header>
            <div class="provider-body">
              <div class="api-fields">
                <div class="api-field">
                  <span>供应商标识</span>
                  <code>{{ provider.id }}</code>
                </div>
                <div class="api-field">
                  <span>服务地址</span>
                  <code>{{ provider.base_url || '未提供' }}</code>
                </div>
              </div>
              <div class="model-list">
                <div v-for="model in modelsForProvider(provider.id)" :key="model.id" class="model-row">
                  <div>
                    <strong>{{ model.display_name || model.model_id || model.id }}</strong>
                    <div class="model-params">
                      <span class="param">{{ model.model_id || model.id }}</span>
                      <span v-if="model.thinking_supported" class="param">支持推理</span>
                    </div>
                  </div>
                  <div class="row-actions">
                    <button class="small-btn" type="button" :data-model-edit="model.id" @click="startModelUpdate(model)">编辑</button>
                    <button class="small-btn" type="button" :data-model-delete="model.id" @click="$emit('delete-model', model.id)">删除</button>
                  </div>
                </div>
                <p v-if="!modelsForProvider(provider.id).length" class="muted">当前没有可用模型。</p>
              </div>
            </div>
          </article>
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

      <section v-else class="settings-panel">
        <header class="settings-title">
          <h1>权限策略</h1>
          <p>Core 在每次需要授权的操作前由运行时请求，不在此页面保存策略。</p>
        </header>
        <article class="setting-card">
          <h3>运行时授权</h3>
          <p>文件修改、命令执行和外部访问由运行时按请求处理。此页只说明通用策略，不提供绕过授权的写入控制。</p>
        </article>
      </section>
    </template>
  </SettingsShell>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { THEME_PRESETS } from '../data/theme-presets'
import {
  gradientFromStops,
  type ThemeArea,
  type ThemeData,
  type ThemePreset,
  type ThemeStop,
} from '../helpers/theme'
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import ThemeEditor from './ThemeEditor.vue'

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
}

export interface CoreSettingsProvider {
  id: string
  name?: string
  api_type?: string
  base_url?: string
  has_api_key?: boolean
}

export interface CoreSettingsProviderPayload {
  provider_id?: string
  name: string
  api_type: string
  base_url: string
  api_key?: string
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
}

const props = defineProps<{
  models: CoreSettingsModel[]
  providers: CoreSettingsProvider[]
  density: CoreSettingsDensity
  theme: ThemeData
}>()

const emit = defineEmits<{
  close: []
  'update:density': [density: CoreSettingsDensity]
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
}>()

const sections: SettingsSection[] = [
  { id: 'models', label: '模型与供应商', icon: '◈' },
  { id: 'appearance', label: '界面', icon: '◐' },
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
}

type ModelEditor = CoreSettingsModelPayload & { mode: 'create' | 'update' }

const providerEditor = ref<ProviderEditor | null>(null)
const modelEditor = ref<ModelEditor | null>(null)

const settingsThemeStyle = computed(() => ({
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
  '--settings-card-background': gradientFromStops(
    props.theme.composerAngle,
    props.theme.composerStops,
    props.theme.composerOpacity,
  ),
  '--settings-card-text': props.theme.composerText,
}))

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
    name: '',
    api_type: 'openai',
    base_url: '',
    api_key: '',
  }
}

function startProviderUpdate(provider: CoreSettingsProvider) {
  providerEditor.value = {
    mode: 'update',
    provider_id: provider.id,
    name: provider.name || '',
    api_type: provider.api_type || 'openai',
    base_url: provider.base_url || '',
    api_key: '',
  }
}

function submitProvider() {
  const editor = providerEditor.value
  if (!editor) return
  const payload: CoreSettingsProviderPayload = {
    ...(editor.provider_id ? { provider_id: editor.provider_id } : {}),
    name: editor.name,
    api_type: editor.api_type,
    base_url: editor.base_url,
    ...(editor.api_key.trim() ? { api_key: editor.api_key.trim() } : {}),
  }
  if (editor.mode === 'create') emit('create-provider', payload)
  else emit('update-provider', payload)
  providerEditor.value = null
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
  }
}

function submitModel() {
  const editor = modelEditor.value
  if (!editor) return
  const { mode: _mode, ...payload } = editor
  if (editor.mode === 'create') emit('create-model', payload)
  else emit('update-model', payload)
  modelEditor.value = null
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
</script>

<style scoped>
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
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  align-items: end;
}

.config-form .field {
  display: grid;
  gap: 6px;
  font-size: 13px;
}

.config-form input,
.config-form select {
  min-width: 0;
  min-height: 36px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: 6px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: inherit;
  padding: 0 9px;
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

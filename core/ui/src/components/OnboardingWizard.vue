<template>
  <Teleport to="body">
    <div
      class="onboarding-overlay"
      :style="overlayStyle"
      role="dialog"
      aria-modal="true"
      aria-label="首次使用引导"
    >
      <div class="onboarding-card">
        <!-- Step 0: 欢迎 -->
        <section v-if="step === 0" class="onboarding-step">
          <!-- PS 插画占位槽：后续插画放 core/ui/src/assets/welcome-art.png 并替换此容器内容 -->
          <div class="welcome-art" aria-hidden="true">
            <span class="welcome-art-mark">✦</span>
          </div>
          <h1 class="onboarding-title">欢迎使用 LamTools Core</h1>
          <p class="onboarding-subtitle">
            一个本地优先的 Agent 工作台：管理会话、记忆与自动化任务，
            你的数据与配置都留在本机。
          </p>
          <p class="onboarding-hint">开始前需要配置一个模型供应商，让 Agent 能思考与回复。</p>
          <div class="onboarding-actions">
            <button class="btn primary" type="button" data-onboarding-start @click="step = 1">开始配置</button>
            <button class="btn quiet" type="button" data-onboarding-skip @click="emit('skip')">跳过</button>
          </div>
        </section>

        <!-- Step 1: 配置供应商 -->
        <section v-else-if="step === 1" class="onboarding-step">
          <h2 class="onboarding-title">配置模型供应商</h2>
          <p class="onboarding-subtitle">选择官方模板，或手动填写服务信息。</p>

          <form class="onboarding-form" @submit.prevent="submitProvider">
            <label class="field">官方模板
              <select v-model="presetId" data-onboarding-preset @change="applyPreset">
                <option value="">自定义</option>
                <option v-for="preset in providerPresets" :key="preset.id" :value="preset.id">
                  {{ preset.label }}
                </option>
              </select>
            </label>

            <div v-if="presetId" class="preset-summary">
              <strong>{{ providerName }}</strong>
              <span>{{ providerBaseUrl }} · 将自动添加模板内模型</span>
            </div>

            <template v-else>
              <label class="field">名称
                <input v-model.trim="providerName" data-onboarding-provider-name type="text" required placeholder="如：我的 DeepSeek" />
              </label>
              <label class="field">服务地址
                <input v-model.trim="providerBaseUrl" data-onboarding-provider-base-url type="url" required placeholder="https://api.deepseek.com" />
              </label>
            </template>

            <label class="field">API Key
              <input
                v-model="apiKey"
                data-onboarding-api-key
                type="password"
                autocomplete="new-password"
                required
                placeholder="sk-..."
              />
            </label>

            <p v-if="error" class="onboarding-error" role="alert">{{ error }}</p>

            <div class="onboarding-actions">
              <button class="btn quiet" type="button" :disabled="loading" @click="step = 0">上一步</button>
              <button class="btn primary" type="submit" data-onboarding-submit :disabled="loading || !canSubmit">
                {{ loading ? '保存中…' : '保存并继续' }}
              </button>
            </div>
          </form>
        </section>

        <!-- Step 2: 完成 -->
        <section v-else class="onboarding-step">
          <div class="done-mark" aria-hidden="true">✓</div>
          <h2 class="onboarding-title">配置完成</h2>
          <ul class="done-summary">
            <li><span>供应商</span><strong>{{ createdProviderName || primaryProviderName }}</strong></li>
            <li><span>模型数量</span><strong>{{ models.length }} 个</strong></li>
            <li><span>默认模型</span><strong>{{ defaultModelName || '未设置（可在设置中调整）' }}</strong></li>
          </ul>
          <p class="onboarding-hint">之后可在 Core 设置中继续添加供应商、模型或调整权限模式。</p>
          <div class="onboarding-actions">
            <button class="btn primary" type="button" data-onboarding-finish @click="emit('finish')">开始使用</button>
          </div>
        </section>

        <footer class="onboarding-footer">
          <div class="step-dots" aria-label="步骤">
            <span
              v-for="i in 3"
              :key="i"
              class="step-dot"
              :class="{ active: step === i - 1 }"
              aria-hidden="true"
            ></span>
          </div>
          <button v-if="step !== 2" class="text-skip" type="button" @click="emit('skip')">跳过</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { PROVIDER_PRESETS } from '../data/provider-presets'
import { themeToCSSVars, type ThemeData } from '../helpers/theme'
import type { CoreSettingsProvider, CoreSettingsModel, CoreSettingsProviderPayload } from './CoreSettings.vue'

const props = defineProps<{
  providers: CoreSettingsProvider[]
  models: CoreSettingsModel[]
  defaultModelId?: string
  theme: ThemeData
  loading?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  'create-provider': [payload: CoreSettingsProviderPayload]
  skip: []
  finish: []
}>()

const step = ref(0)
const presetId = ref('')
const providerName = ref('')
const providerBaseUrl = ref('')
const apiKey = ref('')
const providerApiType = ref('openai')
const createdProviderName = ref('')

const providerPresets = PROVIDER_PRESETS

const overlayStyle = computed(() => ({ ...themeToCSSVars(props.theme) }))

const canSubmit = computed(() => {
  if (!apiKey.value.trim()) return false
  if (presetId.value) return true
  return Boolean(providerName.value.trim() && providerBaseUrl.value.trim())
})

const primaryProvider = computed(() => props.providers.find((p) => p.has_api_key) || props.providers[0] || null)
const primaryProviderName = computed(() => primaryProvider.value?.name || primaryProvider.value?.id || '—')
const defaultModelName = computed(() => {
  const model = props.models.find((m) => m.id === props.defaultModelId)
  return model?.display_name || model?.model_id || ''
})

function applyPreset() {
  const preset = providerPresets.find((candidate) => candidate.id === presetId.value)
  if (!preset) return
  providerName.value = preset.name
  providerBaseUrl.value = preset.baseUrl
  providerApiType.value = preset.apiType
}

function submitProvider() {
  if (!canSubmit.value) return
  createdProviderName.value = providerName.value
  const payload: CoreSettingsProviderPayload = {
    name: providerName.value,
    api_type: providerApiType.value,
    base_url: providerBaseUrl.value,
    api_key: apiKey.value.trim(),
    extra: {},
  }
  if (presetId.value) {
    const preset = providerPresets.find((candidate) => candidate.id === presetId.value)
    if (preset) {
      payload.preset_id = preset.id
      payload.extra = { ...(preset.extra || {}), adapter_profile_id: preset.adapterProfile }
      payload.models = preset.models.map((model) => ({
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
  emit('create-provider', payload)
}

// 供应商创建成功后（App.vue 完成 request + reload，loading 复位）推进到完成步
watch(
  () => props.loading,
  (loading, prev) => {
    if (prev === true && loading === false && !props.error) step.value = 2
  },
)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('skip')
}

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.onboarding-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-fullscreen, 100);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-5);
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(6px);
  animation: overlay-in 0.2s ease-out;
}

.onboarding-card {
  width: 560px;
  max-width: 100%;
  padding: var(--space-6) var(--space-6) var(--space-4);
  border: 1px solid var(--theme-main-border, color-mix(in srgb, var(--theme-main-text, #f2efeb) 10%, transparent));
  border-radius: var(--radius-lg);
  background: var(--theme-main-background, #111);
  color: var(--theme-main-text, #f2efeb);
  box-shadow: var(--shadow-lg);
  animation: card-in 0.25s ease-out;
}

.onboarding-step {
  display: grid;
  gap: var(--space-3);
}

.welcome-art {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 280px;
  height: 160px;
  margin: 0 auto;
  border: 1px dashed var(--theme-main-border, rgba(255, 255, 255, 0.1));
  border-radius: var(--radius);
  background: var(--theme-main-soft-background, rgba(255, 255, 255, 0.045));
  /* PS 插画占位：后续将背景替换为 url('../assets/welcome-art.png') 并去掉占位符号 */
}

.welcome-art-mark {
  font-size: 36px;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 24%, transparent);
}

.onboarding-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  text-align: center;
}

.onboarding-subtitle {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  text-align: center;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent);
}

.onboarding-hint {
  margin: 0;
  font-size: 13px;
  text-align: center;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 45%, transparent);
}

.onboarding-actions {
  display: flex;
  justify-content: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.onboarding-form {
  display: grid;
  gap: var(--space-3);
}

.onboarding-form .field {
  display: grid;
  gap: var(--space-1);
  font-size: 13px;
}

.onboarding-form input,
.onboarding-form select {
  width: 100%;
  min-height: 34px;
  padding: 0 var(--space-2);
  border: 1px solid color-mix(in srgb, var(--theme-control-text, #f2efeb) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-control-background, #343331) 70%, transparent);
  color: var(--theme-control-text, #f2efeb);
  font: inherit;
}

.onboarding-form input::placeholder {
  color: color-mix(in srgb, var(--theme-control-text, #f2efeb) 45%, transparent);
}

.preset-summary {
  display: grid;
  gap: 2px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--theme-main-border, rgba(255, 255, 255, 0.1));
  border-radius: var(--radius-sm);
  background: var(--theme-main-subtle-background, rgba(255, 255, 255, 0.028));
  font-size: 13px;
}

.preset-summary span {
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent);
}

.onboarding-error {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid color-mix(in srgb, var(--red, #f5555d) 40%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red, #f5555d) 12%, transparent);
  color: var(--red, #f5555d);
  font-size: 13px;
}

.done-mark {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  margin: 0 auto;
  border-radius: 50%;
  background: var(--theme-control-background, #343331);
  color: var(--theme-control-text, #f2efeb);
  font-size: 26px;
}

.done-summary {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-3);
  border: 1px solid var(--theme-main-border, rgba(255, 255, 255, 0.1));
  border-radius: var(--radius);
  background: var(--theme-main-soft-background, rgba(255, 255, 255, 0.045));
  list-style: none;
  font-size: 13px;
}

.done-summary li {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
}

.done-summary li span {
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 65%, transparent);
}

.done-summary li strong {
  font-weight: 600;
  text-align: right;
}

.onboarding-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--theme-main-border, rgba(255, 255, 255, 0.1));
}

.step-dots {
  display: flex;
  gap: var(--space-2);
}

.step-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) 24%, transparent);
  transition: background 0.15s ease-out;
}

.step-dot.active {
  background: var(--theme-control-text, #f2efeb);
}

.text-skip {
  padding: 0;
  border: 0;
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text, #f2efeb) 45%, transparent);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.text-skip:hover {
  color: var(--theme-main-text, #f2efeb);
}

/* 按钮配方（control area）：primary 填充跟随主题；quiet 透明 + alpha 悬停 */
.btn {
  min-height: 34px;
  padding: 0 var(--space-4);
  border: 0;
  border-radius: var(--radius-sm);
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.45;
  cursor: default;
}

.btn.primary {
  background: var(--theme-control-background, #343331);
  color: var(--theme-control-text, #f2efeb);
}

.btn.primary:hover:not(:disabled) {
  filter: brightness(0.94);
}

.btn.quiet {
  background: transparent;
  color: var(--theme-main-text, #f2efeb);
}

.btn.quiet:hover:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-hover, 8%), transparent);
}

.btn.quiet:active:not(:disabled) {
  background: color-mix(in srgb, var(--theme-main-text, #f2efeb) var(--alpha-active, 12%), transparent);
}

@media (prefers-reduced-motion: reduce) {
  .onboarding-overlay,
  .onboarding-card,
  .step-dot {
    animation: none;
    transition: none;
  }
}

@keyframes overlay-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes card-in {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}
</style>

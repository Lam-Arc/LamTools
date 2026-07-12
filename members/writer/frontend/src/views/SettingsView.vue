<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  CoreSettings,
  PROVIDER_PRESETS,
  useCoreUiPreferences,
  type CoreSettingsModelPayload,
  type CoreSettingsProviderPayload,
} from '@lamtools/ui'
import { useConfigStore } from '@/stores/config'

const UI_NAMESPACE = 'lamwriter.ui'
type CommandPolicy = 'auto_allow' | 'ask_user'

const router = useRouter()
const configStore = useConfigStore()
const ui = useCoreUiPreferences(UI_NAMESPACE, {
  read: async () => (await configStore.fetchAppSetting(UI_NAMESPACE)).value,
  write: async value => { await configStore.saveAppSetting(UI_NAMESPACE, { ...value }) },
})
const { density, contentWidth, theme } = ui
const commandPolicies = ref<Record<'regular' | 'dangerous', CommandPolicy>>({
  regular: 'auto_allow',
  dangerous: 'ask_user',
})

onMounted(async () => {
  await ui.load()
  await Promise.all([
    configStore.fetchProviders(),
    configStore.fetchModels(),
    configStore.fetchAdapterProfiles(),
    loadRuntimePolicies(),
  ])
})

function goBack() {
  router.push('/')
}

async function createProvider(payload: CoreSettingsProviderPayload) {
  const provider = await configStore.createProvider({
    name: payload.name,
    api_type: payload.api_type,
    base_url: payload.base_url,
    api_key: payload.api_key || '',
    extra: payload.extra,
  })
  const preset = PROVIDER_PRESETS.find(candidate => candidate.id === payload.preset_id)
  if (preset) {
    for (const model of preset.models) {
      await configStore.createModel({
        provider_id: provider.id,
        model_id: model.modelId,
        display_name: model.displayName,
        context_window: model.contextWindow,
        max_output_tokens: model.maxOutputTokens,
        thinking_supported: model.thinkingSupported,
        thinking_budget: model.thinkingBudget,
        temperature: model.temperature,
        extra: model.extra,
      })
    }
  }
}

async function updateProvider(payload: CoreSettingsProviderPayload) {
  if (!payload.provider_id) return
  await configStore.updateProvider(payload.provider_id, {
    name: payload.name,
    api_type: payload.api_type,
    base_url: payload.base_url,
    api_key: payload.api_key,
    extra: payload.extra,
  })
}

async function createModel(payload: CoreSettingsModelPayload) {
  await configStore.createModel(payload)
}

async function updateModel(payload: CoreSettingsModelPayload) {
  if (!payload.model_record_id) return
  const { model_record_id, ...update } = payload
  await configStore.updateModel(model_record_id, update)
}

async function loadRuntimePolicies() {
  try {
    const capabilities = await configStore.fetchRuntimeCapabilities()
    commandPolicies.value = {
      regular: normalizePolicy(capabilities.command_policies?.regular, 'auto_allow'),
      dangerous: normalizePolicy(capabilities.command_policies?.dangerous, 'ask_user'),
    }
  } catch {
    commandPolicies.value = { regular: 'auto_allow', dangerous: 'ask_user' }
  }
}

async function updateCommandPolicy(group: 'regular' | 'dangerous', policy: CommandPolicy) {
  commandPolicies.value = { ...commandPolicies.value, [group]: policy }
  const capabilities = configStore.runtimeCapabilities
  await configStore.saveAppSetting('lamwriter.runtimeControls', {
    agents: Object.fromEntries((capabilities?.agents || []).map(agent => [agent.name, agent.enabled])),
    tools: Object.fromEntries((capabilities?.tools || []).map(tool => [tool.name, tool.enabled])),
    command_policies: commandPolicies.value,
  })
  await loadRuntimePolicies()
}

function normalizePolicy(value: string | undefined, fallback: CommandPolicy): CommandPolicy {
  return value === 'auto_allow' || value === 'ask_user' ? value : fallback
}
</script>

<template>
  <CoreSettings
    :models="configStore.models"
    :providers="configStore.providers"
    :density="density"
    :theme="theme"
    :content-width="contentWidth"
    :allow-environment-import="true"
    :command-policies="commandPolicies"
    @close="goBack"
    @update:density="ui.setDensity"
    @update:content-width="ui.setContentWidth"
    @import-environment="configStore.importEnvConfig"
    @reset-theme="ui.resetTheme"
    @apply-preset="ui.applyThemePreset"
    @update-stops="ui.updateThemeStops"
    @update-angle="ui.updateThemeAngle"
    @update-opacity="ui.updateThemeOpacity"
    @update-text-color="ui.updateThemeText"
    @add-stop="ui.addStop"
    @remove-stop="ui.removeStop"
    @sort-stops="ui.sortStops"
    @create-provider="createProvider"
    @update-provider="updateProvider"
    @delete-provider="configStore.deleteProvider"
    @create-model="createModel"
    @update-model="updateModel"
    @delete-model="configStore.deleteModel"
    @update-command-policy="updateCommandPolicy"
  />
</template>

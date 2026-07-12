import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useCoreConfigState, type CoreConfigAdapter } from '@lamtools/ui'
import * as api from '@/api'
import type {
  Provider, ProviderCreate, ProviderUpdate, Model, ModelCreate, ModelUpdate,
  ResolvedConfig, RuntimeCapabilities, AppSetting, AdapterProfile,
  SubAgentDefinition, SubAgentDefinitionUpdate,
} from '@/types'

const MASKED_KEY = /^(?:\*{4,}|[a-zA-Z0-9]{2,8}\.\.\.[a-zA-Z0-9]{2,8})$/
const adapter: CoreConfigAdapter<Provider, Model, ProviderCreate, ProviderUpdate, ModelCreate, ModelUpdate> = {
  listProviders: api.listProviders,
  createProvider: api.createProvider,
  updateProvider: (id, data) => {
    const payload = { ...data }
    if (!payload.api_key || MASKED_KEY.test(payload.api_key)) delete payload.api_key
    return api.updateProvider(id, payload)
  },
  deleteProvider: api.deleteProvider,
  listModels: api.listModels,
  createModel: api.createModel,
  updateModel: api.updateModel,
  deleteModel: api.deleteModel,
}

export const useConfigStore = defineStore('config', () => {
  const core = useCoreConfigState(adapter)
  const resolvedConfig = ref<ResolvedConfig | null>(null)
  const runtimeCapabilities = ref<RuntimeCapabilities | null>(null)
  const adapterProfiles = ref<AdapterProfile[]>([])

  async function importEnvConfig() {
    const result = await api.importEnvConfig()
    await Promise.all([core.fetchProviders(), core.fetchModels(), fetchResolvedConfig('writer')])
    return result
  }
  async function fetchResolvedConfig(taskType = 'default') {
    resolvedConfig.value = await api.getResolvedConfig(taskType)
  }
  async function fetchRuntimeCapabilities(workRoot?: string) {
    runtimeCapabilities.value = await api.getRuntimeCapabilities(workRoot)
    return runtimeCapabilities.value
  }
  async function fetchAdapterProfiles() {
    adapterProfiles.value = await api.listAdapterProfiles()
    return adapterProfiles.value
  }
  async function fetchAppSetting(namespace: string): Promise<AppSetting> {
    return api.getAppSetting(namespace)
  }
  async function saveAppSetting(namespace: string, value: Record<string, unknown>): Promise<AppSetting> {
    return api.putAppSetting(namespace, value)
  }
  async function saveProjectSubAgent(workRoot: string, agent: SubAgentDefinitionUpdate): Promise<SubAgentDefinition> {
    const saved = await api.saveProjectSubAgent(workRoot, agent)
    await fetchRuntimeCapabilities(workRoot)
    return saved
  }
  async function deleteProjectSubAgent(workRoot: string, name: string) {
    await api.deleteProjectSubAgent(workRoot, name)
    await fetchRuntimeCapabilities(workRoot)
  }

  return {
    ...core, resolvedConfig, runtimeCapabilities, adapterProfiles, importEnvConfig,
    fetchResolvedConfig, fetchRuntimeCapabilities, fetchAdapterProfiles,
    fetchAppSetting, saveAppSetting, saveProjectSubAgent, deleteProjectSubAgent,
  }
})

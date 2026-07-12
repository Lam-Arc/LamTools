import { ref, shallowRef } from 'vue'

export interface CoreConfigEntity { id: string }
export interface CoreConfigAdapter<Provider extends CoreConfigEntity, Model extends CoreConfigEntity, ProviderCreate, ProviderUpdate, ModelCreate, ModelUpdate> {
  listProviders(): Promise<Provider[]>
  createProvider(data: ProviderCreate): Promise<Provider>
  updateProvider(id: string, data: ProviderUpdate): Promise<Provider>
  deleteProvider(id: string): Promise<void>
  listModels(providerId?: string): Promise<Model[]>
  createModel(data: ModelCreate): Promise<Model>
  updateModel(id: string, data: ModelUpdate): Promise<Model>
  deleteModel(id: string): Promise<void>
}

export function useCoreConfigState<Provider extends CoreConfigEntity, Model extends CoreConfigEntity, ProviderCreate, ProviderUpdate, ModelCreate, ModelUpdate>(
  adapter: CoreConfigAdapter<Provider, Model, ProviderCreate, ProviderUpdate, ModelCreate, ModelUpdate>,
) {
  const providers = shallowRef<Provider[]>([])
  const models = shallowRef<Model[]>([])
  const loading = ref(false)

  async function fetchProviders() {
    loading.value = true
    try { providers.value = await adapter.listProviders() } finally { loading.value = false }
  }
  async function fetchModels(providerId?: string) {
    loading.value = true
    try { models.value = await adapter.listModels(providerId) } finally { loading.value = false }
  }
  async function createProvider(data: ProviderCreate) {
    const provider = await adapter.createProvider(data)
    providers.value = upsert(providers.value, provider, true)
    return provider
  }
  async function updateProvider(id: string, data: ProviderUpdate) {
    const provider = await adapter.updateProvider(id, data)
    providers.value = upsert(providers.value, provider)
    return provider
  }
  async function deleteProvider(id: string) {
    await adapter.deleteProvider(id)
    providers.value = providers.value.filter(provider => provider.id !== id)
  }
  async function createModel(data: ModelCreate) {
    const model = await adapter.createModel(data)
    models.value = upsert(models.value, model, true)
    return model
  }
  async function updateModel(id: string, data: ModelUpdate) {
    const model = await adapter.updateModel(id, data)
    models.value = upsert(models.value, model)
    return model
  }
  async function deleteModel(id: string) {
    await adapter.deleteModel(id)
    models.value = models.value.filter(model => model.id !== id)
  }

  return { providers, models, loading, fetchProviders, fetchModels, createProvider, updateProvider, deleteProvider, createModel, updateModel, deleteModel }
}

function upsert<T extends CoreConfigEntity>(items: T[], item: T, prepend = false): T[] {
  const index = items.findIndex(candidate => candidate.id === item.id)
  if (index >= 0) return items.map(candidate => candidate.id === item.id ? item : candidate)
  return prepend ? [item, ...items] : [...items, item]
}

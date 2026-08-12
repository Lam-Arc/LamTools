import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import {
  CORE_EXECUTION_CONTROLS_STORAGE_KEYS,
  useCoreExecutionControlsState,
} from '../src/composables/useCoreExecutionControlsState'

const providers = ref([
  { id: 'provider-1', name: 'Provider One' },
  { id: 'provider-2', name: 'Provider Two' },
])

function createStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  }
}

function createDeferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve
  })
  return { promise, resolve }
}

describe('useCoreExecutionControlsState', () => {
  it('restores a valid model selection and persists later changes', async () => {
    const storage = createStorage({
      [CORE_EXECUTION_CONTROLS_STORAGE_KEYS.modelId]: 'model-2',
    })
    const models = ref([
      { id: 'model-1', provider_id: 'provider-1', thinking_supported: true, context_window: 128_000 },
      { id: 'model-2', provider_id: 'provider-2', thinking_supported: true, context_window: 256_000 },
    ])
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
      storage,
    })

    expect(state.selectedModelId.value).toBe('model-2')
    expect(state.turnOptions()).toMatchObject({ context_window_tokens: 256_000 })

    state.selectModel('model-1')
    await nextTick()
    expect(storage.getItem(CORE_EXECUTION_CONTROLS_STORAGE_KEYS.modelId)).toBe('model-1')
    expect(state.turnOptions()).toMatchObject({ context_window_tokens: 128_000 })
  })

  it('keeps a stored model selection while the model catalog is loading', async () => {
    const storage = createStorage({
      [CORE_EXECUTION_CONTROLS_STORAGE_KEYS.modelId]: 'model-2',
    })
    const models = ref<Array<{ id: string; provider_id: string; thinking_supported: boolean }>>([])
    const defaultModel = ref<{ id: string; provider_id: string; thinking_supported: boolean } | null>(null)
    const state = useCoreExecutionControlsState({ models, providers, defaultModel, storage })

    expect(state.selectedModelId.value).toBe('model-2')
    models.value = [{ id: 'model-2', provider_id: 'provider-2', thinking_supported: true }]
    defaultModel.value = models.value[0]
    await nextTick()

    expect(state.selectedModelId.value).toBe('model-2')
    expect(state.turnOptions()).toMatchObject({ model_id: 'model-2' })
  })

  it('restores thinking preferences and persists later changes', async () => {
    const storage = createStorage({
      [CORE_EXECUTION_CONTROLS_STORAGE_KEYS.thinkingMode]: 'low',
      [CORE_EXECUTION_CONTROLS_STORAGE_KEYS.shallowThinking]: '1',
    })
    const models = ref([{ id: 'model-1', provider_id: 'provider-1', thinking_supported: true }])
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
      storage,
    })

    expect(state.selectedThinkingMode.value).toBe('low')
    expect(state.shallowThinkingEnabled.value).toBe(true)

    state.selectedThinkingMode.value = 'high'
    state.shallowThinkingEnabled.value = false
    await nextTick()

    expect(storage.getItem(CORE_EXECUTION_CONTROLS_STORAGE_KEYS.thinkingMode)).toBe('high')
    expect(storage.getItem(CORE_EXECUTION_CONTROLS_STORAGE_KEYS.shallowThinking)).toBe('0')
  })

  it('keeps a valid selected model and falls back when the model list removes it', async () => {
    const models = ref([
      { id: 'model-1', provider_id: 'provider-1', thinking_supported: true, context_window: 128_000 },
      { id: 'model-2', provider_id: 'provider-2', thinking_supported: true },
    ])
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
    })

    state.selectModel('model-2')
    expect(state.selectedModelId.value).toBe('model-2')

    models.value = [models.value[1]]
    await nextTick()
    expect(state.selectedModelId.value).toBe('model-2')

    models.value = [{ id: 'model-1', provider_id: 'provider-1', thinking_supported: true }]
    await nextTick()
    expect(state.selectedModelId.value).toBe('')
    expect(state.activeModel.value?.id).toBe('model-1')
  })

  it('falls back to no thinking when the active model does not support it', async () => {
    const models = ref([{ id: 'model-1', provider_id: 'provider-1', thinking_supported: true }])
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
      initial: { thinkingMode: 'high' },
    })

    models.value = [{ id: 'model-1', provider_id: 'provider-1', thinking_supported: false }]
    await nextTick()

    expect(state.selectedThinkingMode.value).toBe('none')
    expect(state.payload.value).toEqual({
      thinking_enabled: false,
      shallow_thinking_enabled: false,
    })
  })

  it('falls back to the provider-compatible mode when the previous mode disappears', async () => {
    const models = ref([{ id: 'model-1', provider_id: 'provider-1', thinking_supported: true }])
    const selectedProviders = ref([{ id: 'provider-1', name: 'Provider One' }])
    const state = useCoreExecutionControlsState({
      models,
      providers: selectedProviders,
      defaultModel: ref(models.value[0]),
      initial: { thinkingMode: 'high' },
    })

    selectedProviders.value = [{ id: 'provider-1', name: 'xfyun', base_url: 'https://maas-coding.example.test' }]
    await nextTick()

    expect(state.thinkingModeOptions.value.map((option) => option.value)).toEqual(['high', 'medium', 'low', 'none'])
    expect(state.selectedThinkingMode.value).toBe('high')
  })

  it('builds turn payloads and keeps the newest local model after quick changes', async () => {
    const models = ref([
      {
        id: 'model-1',
        provider_id: 'provider-1',
        thinking_supported: true,
        thinking_budget: 6_000,
        context_window: 128_000,
      },
      { id: 'model-2', provider_id: 'provider-2', thinking_supported: true },
    ])
    const selected = ref<string[]>([])
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
      initial: { thinkingMode: 'high', shallowThinkingEnabled: true },
      onModelSelected: async (model) => {
        selected.value.push(model.id || '')
      },
    })

    expect(state.turnOptions()).toEqual({
      model_id: 'model-1',
      thinking_enabled: true,
      thinking_budget: 8_192,
      shallow_thinking_enabled: true,
      context_window_tokens: 128_000,
      active_mode: 'execute',
    })

    state.selectModel('model-1')
    state.selectModel('model-2')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(state.selectedModelId.value).toBe('model-2')
    expect(selected.value).toEqual(['model-2'])
  })

  it('persists the latest model after an earlier save is already in progress', async () => {
    const models = ref([
      { id: 'model-1', provider_id: 'provider-1', thinking_supported: true },
      { id: 'model-2', provider_id: 'provider-2', thinking_supported: true },
    ])
    const model1Started = createDeferred()
    const releaseModel1 = createDeferred()
    const model2Persisted = createDeferred()
    const persisted: string[] = []
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
      onModelSelected: async (model) => {
        persisted.push(model.id || '')
        if (model.id === 'model-1') {
          model1Started.resolve()
          await releaseModel1.promise
          return
        }
        model2Persisted.resolve()
      },
    })

    state.selectModel('model-1')
    await model1Started.promise
    state.selectModel('model-2')

    expect(state.selectedModelId.value).toBe('model-2')
    releaseModel1.resolve()
    await model2Persisted.promise

    expect(persisted).toEqual(['model-1', 'model-2'])
    expect(persisted.at(-1)).toBe('model-2')
    expect(state.selectedModelId.value).toBe('model-2')
  })

  it('keeps local model state when asynchronous persistence fails', async () => {
    const models = ref([{ id: 'model-1', provider_id: 'provider-1', thinking_supported: true }])
    const selected = ref<string[]>([])
    const state = useCoreExecutionControlsState({
      models,
      providers,
      defaultModel: ref(models.value[0]),
      onModelSelected: async (model) => {
        selected.value.push(model.id || '')
        throw new Error('save failed')
      },
    })

    state.selectModel('model-1')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(selected.value).toEqual(['model-1'])
    expect(state.selectedModelId.value).toBe('model-1')
    expect(state.activeModel.value?.id).toBe('model-1')
  })
})

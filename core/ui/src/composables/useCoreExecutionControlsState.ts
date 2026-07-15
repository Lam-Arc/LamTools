import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import {
  coreModelSelectOptions,
  coreThinkingModeOptions,
  coreThinkingPayload,
  normalizeCoreThinkingMode,
  readStoredCoreThinkingMode,
  selectCoreExecutionModel,
  writeStoredCoreShallowThinking,
  writeStoredCoreThinkingMode,
  type CoreExecutionModelSource,
  type CoreExecutionProviderSource,
  type CoreSelectOption,
  type CoreThinkingLabels,
  type CoreThinkingMode,
  type CoreThinkingModeOption,
  type CoreThinkingPayload,
} from '../composer/execution'

export interface CoreExecutionControlsStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export const CORE_EXECUTION_CONTROLS_STORAGE_KEYS = {
  modelId: 'lamtools.core.executionControls.modelId',
  thinkingMode: 'lamtools.core.executionControls.thinkingMode',
  shallowThinking: 'lamtools.core.executionControls.shallowThinking',
} as const

export interface CoreExecutionControlsStateInitial {
  modelId?: string
  thinkingMode?: CoreThinkingMode
  shallowThinkingEnabled?: boolean
}

export interface CoreExecutionControlsStateLabels {
  thinking?: CoreThinkingLabels
  currentModelPrefix?: string
  fallbackProviderLabel?: string
}

export interface UseCoreExecutionControlsStateOptions<
  TModel extends CoreExecutionModelSource,
  TProvider extends CoreExecutionProviderSource,
> {
  models: Readonly<Ref<TModel[]>>
  providers: Readonly<Ref<TProvider[]>>
  defaultModel: Readonly<Ref<TModel | null>>
  storage?: CoreExecutionControlsStorage | null
  storageKeys?: Partial<Record<keyof typeof CORE_EXECUTION_CONTROLS_STORAGE_KEYS, string>>
  initial?: CoreExecutionControlsStateInitial
  labels?: CoreExecutionControlsStateLabels
  onModelSelected?(model: TModel): void | Promise<void>
}

export interface CoreExecutionControlsState<TModel extends CoreExecutionModelSource, TProvider extends CoreExecutionProviderSource> {
  selectedModelId: Ref<string>
  selectedThinkingMode: Ref<CoreThinkingMode>
  shallowThinkingEnabled: Ref<boolean>
  modelOptions: ComputedRef<CoreSelectOption[]>
  thinkingModeOptions: ComputedRef<CoreThinkingModeOption[]>
  activeModel: ComputedRef<TModel | null>
  activeProvider: ComputedRef<TProvider | null>
  payload: ComputedRef<CoreThinkingPayload>
  selectModel(modelId: string): void
  selectThinkingMode(mode: string): void
  turnOptions(): Record<string, unknown>
}

export function useCoreExecutionControlsState<
  TModel extends CoreExecutionModelSource,
  TProvider extends CoreExecutionProviderSource,
>(options: UseCoreExecutionControlsStateOptions<TModel, TProvider>): CoreExecutionControlsState<TModel, TProvider> {
  const storageKeys = {
    ...CORE_EXECUTION_CONTROLS_STORAGE_KEYS,
    ...options.storageKeys,
  }
  const selectedModelId = ref(readStoredModelId(
    options.storage,
    storageKeys.modelId,
    options.initial?.modelId || '',
  ))
  const selectedThinkingMode = ref(readStoredCoreThinkingMode(
    options.storage,
    storageKeys.thinkingMode,
    normalizeCoreThinkingMode(options.initial?.thinkingMode, 'max'),
  ))
  const shallowThinkingEnabled = ref(readInitialShallowThinking(
    options.storage,
    storageKeys.shallowThinking,
    options.initial?.shallowThinkingEnabled === true,
  ))
  const activeModel = computed(() => {
    const configuredDefault = options.defaultModel.value
    const currentDefault = configuredDefault
      ? options.models.value.find((model) => model.id === configuredDefault.id) || configuredDefault
      : null
    return selectCoreExecutionModel(options.models.value, selectedModelId.value, currentDefault)
  })
  const activeProvider = computed(() => {
    const model = activeModel.value
    return model
      ? options.providers.value.find((provider) => provider.id === model.provider_id) || null
      : null
  })
  const modelOptions = computed(() => coreModelSelectOptions({
    models: options.models.value,
    providers: options.providers.value,
    defaultModel: options.defaultModel.value,
    currentLabelPrefix: options.labels?.currentModelPrefix,
    fallbackProviderLabel: options.labels?.fallbackProviderLabel,
  }))
  const thinkingModeOptions = computed(() => coreThinkingModeOptions({
    model: activeModel.value,
    provider: activeProvider.value,
    labels: options.labels?.thinking,
  }))
  const payload = computed(() => coreThinkingPayload({
    mode: selectedThinkingMode.value,
    model: activeModel.value,
    provider: activeProvider.value,
    shallow: shallowThinkingEnabled.value,
  }))

  watch(
    [
      () => options.models.value.map((model) => model.id || '').join('\u0000'),
      () => options.defaultModel.value?.id || '',
      thinkingModeOptions,
    ],
    () => {
      if (
        options.models.value.length > 0
        && selectedModelId.value
        && !options.models.value.some((model) => model.id === selectedModelId.value)
      ) {
        selectedModelId.value = ''
      }
      if (thinkingModeOptions.value.some((option) => option.value === selectedThinkingMode.value)) return
      selectedThinkingMode.value = thinkingModeOptions.value[0]?.value || 'none'
    },
    { immediate: true },
  )

  watch(selectedThinkingMode, (mode) => {
    writeStoredCoreThinkingMode(options.storage, storageKeys.thinkingMode, mode)
  })
  watch(shallowThinkingEnabled, (enabled) => {
    writeStoredCoreShallowThinking(options.storage, storageKeys.shallowThinking, enabled)
  })
  watch(selectedModelId, (modelId) => {
    writeStoredModelId(options.storage, storageKeys.modelId, modelId)
  })

  let modelSelectionGeneration = 0
  let modelPersistence = Promise.resolve()

  function selectModel(modelId: string): void {
    const model = options.models.value.find((item) => item.id === modelId)
    selectedModelId.value = model ? modelId : ''
    const generation = ++modelSelectionGeneration
    if (!model || !options.onModelSelected) return
    modelPersistence = modelPersistence.then(async () => {
      if (generation !== modelSelectionGeneration) return
      try {
        await options.onModelSelected?.(model)
      } catch {
        // Persistence is product-owned; a failed save must not undo the local selection.
      }
    })
  }

  function selectThinkingMode(mode: string): void {
    selectedThinkingMode.value = normalizeCoreThinkingMode(mode)
  }

  return {
    selectedModelId,
    selectedThinkingMode,
    shallowThinkingEnabled,
    modelOptions,
    thinkingModeOptions,
    activeModel,
    activeProvider,
    payload,
    selectModel,
    selectThinkingMode,
    turnOptions: () => ({
      ...payload.value,
      ...(activeModel.value?.id ? { model_id: activeModel.value.id } : {}),
      ...(Number(activeModel.value?.context_window || 0) > 0
        ? { context_window_tokens: Number(activeModel.value?.context_window) }
        : {}),
    }),
  }
}

function readStoredModelId(
  storage: CoreExecutionControlsStorage | null | undefined,
  key: string,
  fallback: string,
): string {
  try {
    return storage?.getItem(key) || fallback
  } catch {
    return fallback
  }
}

function writeStoredModelId(
  storage: CoreExecutionControlsStorage | null | undefined,
  key: string,
  modelId: string,
): void {
  try {
    storage?.setItem(key, modelId)
  } catch {
    // Storage can be unavailable in hardened desktop/browser contexts.
  }
}

function readInitialShallowThinking(
  storage: CoreExecutionControlsStorage | null | undefined,
  key: string,
  fallback: boolean,
): boolean {
  try {
    const value = storage?.getItem(key)
    return value === null || value === undefined ? fallback : value === '1'
  } catch {
    return fallback
  }
}

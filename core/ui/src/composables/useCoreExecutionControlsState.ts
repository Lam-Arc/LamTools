import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
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
  type CoreExecutionModelGroupSource,
  type CoreModelCatalogView,
  type CoreExecutionProviderSource,
  type CorePermissionPreset,
  type CoreSelectOption,
  type CoreThinkingLabels,
  type CoreThinkingMode,
  type CoreThinkingModeOption,
  type CoreThinkingPayload,
  normalizeCorePermissionPreset,
} from '@/composer/execution.ts'

export interface CoreExecutionControlsStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export const CORE_EXECUTION_CONTROLS_STORAGE_KEYS = {
  modelId: 'lamtools.core.executionControls.modelId',
  thinkingMode: 'lamtools.core.executionControls.thinkingMode',
  shallowThinking: 'lamtools.core.executionControls.shallowThinking',
  activeMode: 'lamtools.core.executionControls.activeMode',
} as const

export interface CoreExecutionControlsStateInitial {
  modelId?: string
  thinkingMode?: CoreThinkingMode | string
  shallowThinkingEnabled?: boolean
  activeMode?: string
  permissionPreset?: CorePermissionPreset
}

export interface CoreExecutionControlsStateLabels {
  thinking?: CoreThinkingLabels
  currentModelPrefix?: string
  fallbackProviderLabel?: string
}

/**
 * The Composer's per-session "input parameter group".
 *
 * user:“输入框的信息作为‘输入参数组’按会话持久化保存包括模式权限模型思考”
 * +(整组一起读写，避免模型、权限、模式各走一条保存路径而互相覆盖)。
 */
export interface CoreComposerControls {
  modelId: string
  thinkingMode: CoreThinkingMode
  shallowThinkingEnabled: boolean
  activeMode: string
  permissionPreset: CorePermissionPreset
}

export interface UseCoreExecutionControlsStateOptions<
  TModel extends CoreExecutionModelSource,
  TProvider extends CoreExecutionProviderSource,
> {
  models: Readonly<Ref<TModel[]>>
  providers: Readonly<Ref<TProvider[]>>
  groups?: Readonly<Ref<CoreExecutionModelGroupSource[]>>
  catalogView?: Readonly<Ref<CoreModelCatalogView>>
  defaultModel: Readonly<Ref<TModel | null>>
  storage?: CoreExecutionControlsStorage | null
  storageKeys?: Partial<Record<keyof typeof CORE_EXECUTION_CONTROLS_STORAGE_KEYS, string>>
  initial?: CoreExecutionControlsStateInitial
  labels?: CoreExecutionControlsStateLabels
  onModelSelected?(model: TModel): void | Promise<void>
  onPermissionPresetSelected?(preset: CorePermissionPreset): void | Promise<void>
  /**
   * Called with the whole group after a user change (and after automatic
   * corrections such as a thinking level the model no longer offers).
   * Session persistence belongs to the host, not to this composable.
   */
  onControlsChanged?(controls: CoreComposerControls): void | Promise<void>
  /**
   * Called when the model that was in use disappeared and the scene's
   * inherited model takes over. The replacement must always be visible —
   * never silently swapped in.
   */
  onModelAutoReplaced?(fromModelId: string, toModelId: string): void
}

export interface CoreExecutionControlsState<TModel extends CoreExecutionModelSource, TProvider extends CoreExecutionProviderSource> {
  selectedModelId: Ref<string>
  selectedThinkingMode: Ref<CoreThinkingMode>
  shallowThinkingEnabled: Ref<boolean>
  activeMode: Ref<string>
  permissionPreset: Ref<CorePermissionPreset>
  modelOptions: ComputedRef<CoreSelectOption[]>
  thinkingModeOptions: ComputedRef<CoreThinkingModeOption[]>
  activeModel: ComputedRef<TModel | null>
  activeProvider: ComputedRef<TProvider | null>
  payload: ComputedRef<CoreThinkingPayload>
  selectModel(modelId: string): void
  selectThinkingMode(mode: string): void
  selectMode(mode: string): void
  selectShallowThinking(enabled: boolean): void
  selectPermissionPreset(preset: string): void
  restorePermissionPreset(preset: unknown): void
  /** Restore the whole group without echo-writing it back to the session. */
  restoreControls(controls: Partial<CoreComposerControls> | null | undefined): void
  controls(): CoreComposerControls
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
  const activeMode = ref(options.initial?.activeMode || 'execute')
  const permissionPreset = ref<CorePermissionPreset>(normalizeCorePermissionPreset(options.initial?.permissionPreset))
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
    groups: options.groups?.value,
    view: options.catalogView?.value,
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
      const previousModelId = selectedModelId.value
      if (
        options.models.value.length > 0
        && previousModelId
        && !options.models.value.some((model) => model.id === previousModelId)
      ) {
        selectedModelId.value = ''
        // The chosen model is gone: the scene's inherited model takes over.
        // Report it so the replacement is visible instead of silent.
        const inherited = options.defaultModel.value
        if (inherited?.id && inherited.id !== previousModelId && options.onModelAutoReplaced) {
          try {
            options.onModelAutoReplaced(previousModelId, inherited.id)
          } catch {
            // Reporting must never break the control state.
          }
        }
      }
      if (thinkingModeOptions.value.some((option) => option.value === selectedThinkingMode.value)) return
      selectedThinkingMode.value = thinkingModeOptions.value[0]?.value || 'off'
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

  // user:“每个会话各自记各自的”+(任何一项变化都把整组交给宿主保存；自动降档
  // 也算一次真实变化，必须落库，否则下次切回会话会又变回不支持的档位)。
  let restoringControls = false

  function controls(): CoreComposerControls {
    return {
      modelId: selectedModelId.value,
      thinkingMode: selectedThinkingMode.value,
      shallowThinkingEnabled: shallowThinkingEnabled.value,
      activeMode: activeMode.value,
      permissionPreset: permissionPreset.value,
    }
  }

  function notifyControlsChanged(): void {
    if (restoringControls) return
    const callback = options.onControlsChanged
    if (!callback) return
    try {
      const result = callback(controls())
      if (result && typeof (result as Promise<void>).catch === 'function') {
        void (result as Promise<void>).catch(() => {
          // Persistence is product-owned; keep the local selection.
        })
      }
    } catch {
      // Persistence failure must never undo the Composer selection.
    }
  }

  watch(
    [selectedModelId, selectedThinkingMode, shallowThinkingEnabled, activeMode, permissionPreset],
    () => { notifyControlsChanged() },
  )

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

  function selectMode(mode: string): void {
    activeMode.value = mode
    try { options.storage?.setItem(storageKeys.activeMode, mode) } catch { /* noop */ }
  }

  function selectShallowThinking(enabled: boolean): void {
    shallowThinkingEnabled.value = enabled === true
  }

  function selectPermissionPreset(preset: string): void {
    const normalized = normalizeCorePermissionPreset(preset)
    if (permissionPreset.value === normalized) return
    permissionPreset.value = normalized
    try {
      const result = options.onPermissionPresetSelected?.(normalized)
      if (result && typeof (result as Promise<void>).catch === 'function') {
        void (result as Promise<void>).catch(() => {
          // Persistence is product-owned; keep the local Composer selection.
        })
      }
    } catch {
      // Keep the local selection even when the host persistence callback fails.
    }
  }

  function restorePermissionPreset(preset: unknown): void {
    permissionPreset.value = normalizeCorePermissionPreset(preset)
  }

  function restoreControls(group: Partial<CoreComposerControls> | null | undefined): void {
    const next = group || {}
    // Keep the suppression through the watcher flush triggered by this batch;
    // `nextTick` resolves after that flush, so switching sessions never writes
    // the restored values back as if the user had changed them.
    restoringControls = true
    if (typeof next.modelId === 'string') selectedModelId.value = next.modelId
    if (next.thinkingMode) selectedThinkingMode.value = normalizeCoreThinkingMode(next.thinkingMode)
    if (typeof next.shallowThinkingEnabled === 'boolean') {
      shallowThinkingEnabled.value = next.shallowThinkingEnabled
    }
    if (typeof next.activeMode === 'string' && next.activeMode) {
      activeMode.value = next.activeMode
      try { options.storage?.setItem(storageKeys.activeMode, next.activeMode) } catch { /* noop */ }
    }
    if (next.permissionPreset) {
      permissionPreset.value = normalizeCorePermissionPreset(next.permissionPreset)
    }
    void nextTick(() => { restoringControls = false })
  }

  // Restore persisted activeMode on mount
  try {
    const stored = options.storage?.getItem(storageKeys.activeMode)
    if (stored) activeMode.value = stored
  } catch { /* noop */ }

  return {
    selectedModelId,
    selectedThinkingMode,
    shallowThinkingEnabled,
    activeMode,
    permissionPreset,
    modelOptions,
    thinkingModeOptions,
    activeModel,
    activeProvider,
    payload,
    selectModel,
    selectThinkingMode,
    selectMode,
    selectShallowThinking,
    selectPermissionPreset,
    restorePermissionPreset,
    restoreControls,
    controls,
  turnOptions: () => ({
    ...payload.value,
    shallow_thinking_enabled: shallowThinkingEnabled.value,
    ...(activeModel.value?.id ? { model_id: activeModel.value.id } : {}),
      ...(Number(activeModel.value?.context_window || 0) > 0
        ? { context_window_tokens: Number(activeModel.value?.context_window) }
        : {}),
      ...(Number(activeModel.value?.max_output_tokens || 0) > 0
        ? { max_tokens: Number(activeModel.value?.max_output_tokens) }
        : {}),
      active_mode: activeMode.value,
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

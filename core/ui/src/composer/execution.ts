/** Product-level reasoning controls. Provider parameter names stay in Core's adapter profiles. */
export type CoreThinkingMode = 'off' | 'light' | 'medium' | 'high' | 'xhigh' | 'max'

export type CorePermissionPreset = 'ask' | 'auto' | 'full_access'

export const CORE_PERMISSION_PRESET_LABELS: Record<CorePermissionPreset, string> = {
  ask: '询问',
  auto: '自动',
  full_access: '完全访问',
}

export const CORE_PERMISSION_PRESET_DESCRIPTIONS: Record<CorePermissionPreset, string> = {
  ask: '工具执行前请求批准',
  auto: '在当前能力范围内自动批准',
  full_access: '完全编辑、自动批准，并允许访问工作目录外',
}

export function normalizeCorePermissionPreset(
  value: unknown,
  fallback: CorePermissionPreset = 'ask',
): CorePermissionPreset {
  return value === 'ask' || value === 'auto' || value === 'full_access' ? value : fallback
}

export function corePermissionPresetLabel(value: unknown): string {
  return CORE_PERMISSION_PRESET_LABELS[normalizeCorePermissionPreset(value)]
}

export interface CoreExecutionModelSource {
  id?: string
  provider_id?: string
  model_id?: string
  display_name?: string
  thinking_supported?: boolean
  thinking_budget?: number
  reasoning_off_supported?: boolean
  context_window?: number
  max_output_tokens?: number
}

export type CoreModelCatalogView = 'group' | 'provider'

export interface CoreExecutionModelGroupSource {
  id: string
  name?: string
  model_ids?: string[]
}

export interface CoreExecutionProviderSource {
  id?: string
  name?: string
  base_url?: string
}

export interface CoreSelectOption {
  value: string
  label: string
  selectedLabel?: string
  group?: string
  groupKey?: string
  disabled?: boolean
}

export interface CoreThinkingModeOption {
  value: CoreThinkingMode
  label: string
}

export interface CoreThinkingPayload {
  reasoning_level: CoreThinkingMode
}

export type CoreThinkingLabels = Record<CoreThinkingMode, string>

export const CORE_THINKING_LABELS: CoreThinkingLabels = {
  off: '关闭',
  light: '轻',
  medium: '中',
  high: '高',
  xhigh: '超高',
  max: '极高',
}

export const CORE_THINKING_BUDGETS: Record<Exclude<CoreThinkingMode, 'off'>, number> = {
  light: 2_048,
  medium: 4_096,
  high: 8_192,
  xhigh: 12_288,
  max: 16_384,
}

export function normalizeCoreThinkingMode(value: unknown, fallback: CoreThinkingMode = 'off'): CoreThinkingMode {
  const normalized = String(value ?? '').trim().toLowerCase()
  if (normalized === 'off' || normalized === 'none' || normalized === 'disabled') return 'off'
  if (normalized === 'light' || normalized === 'low' || normalized === 'minimal') return 'light'
  if (normalized === 'medium') return 'medium'
  if (normalized === 'high') return 'high'
  if (normalized === 'xhigh' || normalized === 'xh') return 'xhigh'
  if (normalized === 'max' || normalized === 'ultra') return 'max'
  return fallback
}

export function selectCoreExecutionModel<T extends CoreExecutionModelSource>(
  models: T[],
  selectedModelId: string,
  defaultModel: T | null,
): T | null {
  if (selectedModelId) {
    const selected = models.find((model) => model.id === selectedModelId)
    if (selected) return selected
  }
  return defaultModel
}

export function coreModelDisplayLabel(model: CoreExecutionModelSource | null | undefined): string {
  if (!model) return ''
  return String(model.display_name || model.model_id || model.id || '')
}

export function coreModelSelectOptions<TModel extends CoreExecutionModelSource, TProvider extends CoreExecutionProviderSource>(
  params: {
    models: TModel[]
    providers?: TProvider[]
    groups?: CoreExecutionModelGroupSource[]
    view?: CoreModelCatalogView
    defaultModel?: TModel | null
    currentLabelPrefix?: string
    fallbackProviderLabel?: string
  },
): CoreSelectOption[] {
  const modelsByProvider = new Map<string, TModel[]>()
  for (const model of params.models) {
    const providerId = String(model.provider_id || '')
    const list = modelsByProvider.get(providerId) || []
    list.push(model)
    modelsByProvider.set(providerId, list)
  }

  const options: CoreSelectOption[] = []
  const defaultLabel = coreModelDisplayLabel(params.defaultModel)
  if (defaultLabel) {
    options.push({
      value: '',
      label: `${params.currentLabelPrefix ?? 'Current: '}${defaultLabel}`,
      selectedLabel: defaultLabel,
      group: '',
      groupKey: 'default',
    })
  }

  if (params.view === 'group') {
    const modelById = new Map<string, TModel>()
    for (const model of params.models) {
      const recordId = String(model.id || model.model_id || '')
      if (recordId) modelById.set(recordId, model)
    }
    const groupedIds = new Set<string>()
    for (const group of params.groups ?? []) {
      for (const modelId of group.model_ids ?? []) {
        const model = modelById.get(String(modelId))
        if (!model) continue
        groupedIds.add(String(model.id || model.model_id || ''))
        const label = coreModelDisplayLabel(model)
        if (!label) continue
        options.push({
          value: String(model.id || model.model_id || label),
          label,
          selectedLabel: label,
          group: group.name || group.id,
          groupKey: `group:${group.id}`,
        })
      }
    }
    for (const model of params.models) {
      const recordId = String(model.id || model.model_id || '')
      if (!recordId || groupedIds.has(recordId)) continue
      const label = coreModelDisplayLabel(model)
      if (!label) continue
      options.push({
        value: recordId,
        label,
        selectedLabel: label,
        group: '未分组',
        groupKey: 'group:__ungrouped__',
      })
    }
    return options
  }

  const pushProviderModels = (provider: TProvider | null, models: TModel[]) => {
    for (const model of models) {
      const label = coreModelDisplayLabel(model)
      if (!label) continue
      options.push({
        value: String(model.id || model.model_id || label),
        label,
        selectedLabel: label,
        group: provider?.name || model.provider_id || params.fallbackProviderLabel || 'Provider',
        groupKey: `provider:${provider?.id || model.provider_id || '__unknown__'}`,
      })
    }
  }

  for (const provider of params.providers ?? []) {
    const providerId = String(provider.id || '')
    pushProviderModels(provider, modelsByProvider.get(providerId) || [])
    modelsByProvider.delete(providerId)
  }
  for (const models of modelsByProvider.values()) {
    pushProviderModels(null, models)
  }
  return options
}

export function coreThinkingModeOptions(
  params: {
    model?: CoreExecutionModelSource | null
    provider?: CoreExecutionProviderSource | null
    labels?: CoreThinkingLabels
  } = {},
): CoreThinkingModeOption[] {
  const labels = params.labels ?? CORE_THINKING_LABELS
  if (params.model && !params.model.thinking_supported) {
    return [{ value: 'off', label: labels.off }]
  }
  const modes: CoreThinkingMode[] = params.model?.reasoning_off_supported === false
    ? ['max', 'xhigh', 'high', 'medium', 'light']
    : ['max', 'xhigh', 'high', 'medium', 'light', 'off']
  return modes.map((value) => ({ value, label: labels[value] }))
}

export function coreThinkingPayload(params: {
  mode: CoreThinkingMode | string
  model?: CoreExecutionModelSource | null
  provider?: CoreExecutionProviderSource | null
  shallow?: boolean
  budgets?: Record<Exclude<CoreThinkingMode, 'off'>, number>
}): CoreThinkingPayload {
  let mode = normalizeCoreThinkingMode(params.mode)
  if (!params.model?.thinking_supported) {
    return { reasoning_level: 'off' }
  }
  if (mode === 'off' && params.model?.reasoning_off_supported === false) {
    mode = 'light'
  }
  if (mode === 'off') {
    return { reasoning_level: 'off' }
  }
  return { reasoning_level: mode }
}

export function readStoredCoreThinkingMode(
  storage: Pick<Storage, 'getItem'> | undefined | null,
  key: string,
  fallback: CoreThinkingMode = 'max',
): CoreThinkingMode {
  try {
    return normalizeCoreThinkingMode(storage?.getItem(key), fallback)
  } catch {
    return fallback
  }
}

export function writeStoredCoreThinkingMode(
  storage: Pick<Storage, 'setItem'> | undefined | null,
  key: string,
  mode: CoreThinkingMode | string,
): void {
  try {
    storage?.setItem(key, normalizeCoreThinkingMode(mode))
  } catch {
    // Storage can be unavailable in hardened desktop/browser contexts.
  }
}

export function readStoredCoreShallowThinking(
  storage: Pick<Storage, 'getItem'> | undefined | null,
  key: string,
): boolean {
  try {
    return storage?.getItem(key) === '1'
  } catch {
    return false
  }
}

export function writeStoredCoreShallowThinking(
  storage: Pick<Storage, 'setItem'> | undefined | null,
  key: string,
  enabled: boolean,
): void {
  try {
    storage?.setItem(key, enabled ? '1' : '0')
  } catch {
    // Storage can be unavailable in hardened desktop/browser contexts.
  }
}

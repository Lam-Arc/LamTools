export type CoreThinkingMode = 'none' | 'low' | 'medium' | 'high' | 'max'

export interface CoreExecutionModelSource {
  id?: string
  provider_id?: string
  model_id?: string
  display_name?: string
  thinking_supported?: boolean
  thinking_budget?: number
  context_window?: number
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
}

export interface CoreThinkingModeOption {
  value: CoreThinkingMode
  label: string
}

export interface CoreThinkingPayload {
  thinking_enabled: boolean
  thinking_budget?: number
  shallow_thinking_enabled?: boolean
}

export type CoreThinkingLabels = Record<CoreThinkingMode, string>

export const CORE_THINKING_LABELS: CoreThinkingLabels = {
  none: 'No thinking',
  low: 'Low thinking',
  medium: 'Medium thinking',
  high: 'High thinking',
  max: 'Max thinking',
}

export const CORE_THINKING_BUDGETS: Record<Exclude<CoreThinkingMode, 'none'>, number> = {
  low: 2_000,
  medium: 6_000,
  high: 10_000,
  max: 20_000,
}

export function normalizeCoreThinkingMode(value: unknown, fallback: CoreThinkingMode = 'none'): CoreThinkingMode {
  return value === 'low' || value === 'medium' || value === 'high' || value === 'max' || value === 'none'
    ? value
    : fallback
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
    })
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
    return [{ value: 'none', label: labels.none }]
  }
  const modes: CoreThinkingMode[] = isMaxOnlyThinkingProvider(params.provider)
    ? ['max', 'none']
    : ['max', 'high', 'medium', 'low', 'none']
  return modes.map((value) => ({ value, label: labels[value] }))
}

export function coreThinkingPayload(params: {
  mode: CoreThinkingMode | string
  model?: CoreExecutionModelSource | null
  provider?: CoreExecutionProviderSource | null
  shallow?: boolean
  budgets?: Record<Exclude<CoreThinkingMode, 'none'>, number>
}): CoreThinkingPayload {
  const mode = normalizeCoreThinkingMode(params.mode)
  const shallow = params.shallow === true
  if (mode === 'none' || !params.model?.thinking_supported) {
    return { thinking_enabled: false, shallow_thinking_enabled: shallow }
  }
  const budgets = params.budgets ?? CORE_THINKING_BUDGETS
  const modelBudget = Number(params.model.thinking_budget || 0)
  const thinking_budget = isMaxOnlyThinkingProvider(params.provider)
    ? modelBudget || budgets.max
    : Math.max(modelBudget || 0, budgets[mode])
  return { thinking_enabled: true, thinking_budget, shallow_thinking_enabled: shallow }
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

function isMaxOnlyThinkingProvider(provider: CoreExecutionProviderSource | null | undefined): boolean {
  const text = `${provider?.name || ''} ${provider?.base_url || ''}`.toLowerCase()
  return text.includes('xf-yun') || text.includes('xfyun') || text.includes('maas-coding')
}
